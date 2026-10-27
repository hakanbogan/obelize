"""What a tool may not do to a file that still parses, and what it may not do to the machine.

The first review of `external_fixer` (ADR-074) found a rewrite the proof let through that raised
where the original ran, a block that grew by a line nobody looked at, a tool that outlived its
deadline and a pin move that harmed. Each is a case here, with the tool a Python one-liner.
"""

from __future__ import annotations

import random
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fakefixer import made, run, tool
from typer.testing import CliRunner

from obelize.cli import app
from obelize.packs import loader
from obelize.transforms import codemod, fixers
from obelize.transforms.base import BailError
from obelize.transforms.kinds import external_fixer
from platforms import SHEBANG, alive
from support import committed, migrate

if TYPE_CHECKING:
    from obelize.models import BailCode

NUMPY = "numpy/numpy-1-to-2"
LOADED = loader.load(NUMPY)
NUMPY_SPEC = loader.to_scan_spec(LOADED)
runner_ = CliRunner()

# What ruff does for `np.safe_eval`: the call becomes `literal_eval`, imported at module level.
SAFE_EVAL = (
    "out = data.replace(b'np.safe_eval(', b'literal_eval(')\n"
    "if out != data and b'from ast import literal_eval' not in out:\n"
    "    out = out.replace(b'import numpy as np\\n', b'import numpy as np\\n"
    "from ast import literal_eval\\n', 1)"
)
STUB = "import ast\nsafe_eval = ast.literal_eval\n"
RUN = (
    "import runpy, sys; sys.path.insert(0, sys.argv[1]); "
    "runpy.run_path(sys.argv[2], run_name='__main__')"
)
HEAD = "import numpy as np\n"
CALL = "np.safe_eval('[1]')"


def program(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def local(*lines: str) -> str:
    """A function that makes the call, then does what `lines` say."""
    return program(
        "def f():", f"    v = {CALL}", *(f"    {line}" for line in lines), "    return v"
    )


# Programs whose function, class or comprehension binds the name the import brings: the call the
# tool wrote reads that local, and raises where the original ran.
SHADOWED = {
    "assigned later": local("literal_eval = 5"),
    "a loop target": local("for literal_eval in range(2): pass"),
    "a with target": local("with open(__file__) as literal_eval: pass"),
    "an except target": local("try: 1/0", "except Exception as literal_eval: pass"),
    "an import": local("from ast import dump as literal_eval"),
    "a del": local("literal_eval = 1", "del literal_eval"),
    "a comprehension": program(
        "def f():", f"    r = [{CALL} for _ in range(2)]", "    literal_eval = 5", "    return r"
    ),
    "a class body": program("class A:", f"    v = {CALL}", "    literal_eval = 5"),
    "a global declaration": program(
        "def f():", "    global literal_eval", "    literal_eval = 5", f"    return {CALL}"
    ),
    "a parameter": program("def f(literal_eval=3):", f"    return {CALL}"),
}
# Programs the import serves as it was written.
SERVED = {
    "assigned at module level later": program(f"v = {CALL}", "literal_eval = 5"),
    "a function defined later": program(
        f"v = {CALL}", "", "", "def literal_eval(x): return 'mine'"
    ),
    "a lambda default": program(f"f = lambda a={CALL}: a", "literal_eval = 3"),
    "a call in a function of its own": program(
        "def f():", f"    return {CALL}", "", "", "literal_eval = 3"
    ),
}


def outcome(path: Path, stub: Path) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, "-I", "-c", RUN, str(stub), str(path)], capture_output=True, timeout=60
    )
    return done.returncode, done.stdout.decode()


@pytest.mark.parametrize("name", [*SHADOWED, *SERVED])
def test_a_rewrite_that_raises_where_the_original_ran_is_not_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    """Run before and after: what is written does what the file did."""
    tool(monkeypatch, made(SAFE_EVAL))
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "numpy.py").write_text(STUB)
    work = tmp_path / "work"
    work.mkdir()
    shadowed = name in SHADOWED
    source = HEAD + (SHADOWED if shadowed else SERVED)[name]
    (work / "app.py").write_text(source)
    before = outcome(work / "app.py", stub)
    done = migrate(work, NUMPY_SPEC, LOADED.pack)
    if shadowed:
        assert done.written == ()
        assert "external_fix_out_of_scope" in {row.reason for row in done.edits}
    else:
        assert [row.path for row in done.written] == ["app.py"]
    (work / "app.py").write_bytes(done.files[0].after)
    assert outcome(work / "app.py", stub) == before


def test_a_name_an_import_binds_is_looked_for_in_every_scope_but_the_module() -> None:
    inside = b"from ast import literal_eval\ndef f():\n    literal_eval = 1\n"
    assert external_fixer._shadowed(inside, {"literal_eval"})
    assert not external_fixer._shadowed(b"from ast import literal_eval\nliteral_eval = 1\n", {"x"})
    assert not external_fixer._shadowed(b"def f(\n", {"literal_eval"})
    assert not external_fixer._shadowed(b"\xff", {"literal_eval"})
    assert external_fixer._imported(b"def f(") == []


# A block that grows by a line.

INJECTED = "import acme.kit as kit\nA = kit.old_a(1)\n"
KEEPS = "import acme.kit as kit\nimport json\nA = kit.new_a(1)\n"


@pytest.mark.parametrize(
    ("added", "kept"),
    [
        (r"b'A = kit.new_a(1)\nprint(1)\n'", False),
        (r"b'print(1)\nA = kit.new_a(1)\n'", False),
        (r"b'import json\nA = kit.new_a(1)\n'", True),
        (r"b'A = kit.new_a(1)\nimport json\n'", True),
        (r"b'# a note\nA = kit.new_a(1)\n'", True),
    ],
)
def test_a_line_a_block_adds_to_the_ones_it_replaces_is_an_import_or_it_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, added: str, kept: bool
) -> None:
    tool(monkeypatch, made(f"out = data.replace(b'A = kit.old_a(1)\\n', {added})"))
    done = run(tmp_path, INJECTED)
    assert bool(done.written) is kept
    if not kept:
        assert "external_fix_out_of_scope" in {row.reason for row in done.edits}


VOCAB = [b"import a\n", b"x = 1\n", b"y = np.float_(1)\n", b"\n", b"# c\n", b"z = 2\n", b"w = 3\n"]
NOTE = (b"import ", b"#")


def legal(old: tuple[bytes, ...], claimed: frozenset[int], new: tuple[bytes, ...]) -> bool:
    """Whether some alignment of `new` onto `old` keeps every line not claimed and adds only
    imports, blank lines and comments past the lines a gap replaces: the rule, said apart."""

    def blank_or_import(line: bytes) -> bool:
        return not line.strip() or line.startswith(NOTE)

    def gap(i: int, i2: int, j: int, j2: int) -> bool:
        replaced, added = range(i, i2), new[j:j2]
        return all(k in claimed for k in replaced) and (
            len(added) <= len(replaced)
            or sum(map(blank_or_import, added)) >= len(added) - len(replaced)
        )

    @lru_cache(None)
    def finish(i: int, j: int) -> bool:
        return gap(i, len(old), j, len(new)) or any(
            old[i2] == new[j2] and gap(i, i2, j, j2) and finish(i2 + 1, j2 + 1)
            for i2 in range(i, len(old))
            for j2 in range(j, len(new))
        )

    return finish(0, 0)


def test_every_edit_the_rule_lets_by_is_one_some_alignment_of_the_lines_allows() -> None:
    """3,000 seeded edits of small files: what `_hunks` lets by, an alignment allows."""
    rng = random.Random(7)  # noqa: S311 - a fixed seed makes the cases; nothing here is a secret
    kept = 0
    for _ in range(3000):
        old = tuple(rng.choice(VOCAB) for _ in range(rng.randint(1, 8)))
        claimed = frozenset(i for i in range(len(old)) if rng.random() < 0.3)
        claimed = claimed or frozenset({rng.randrange(len(old))})
        new: list[bytes] = []
        for line in old:
            roll = rng.random()
            if roll < 0.6:
                new.append(line)
            elif roll < 0.7:
                continue
            elif roll < 0.85:
                new.append(rng.choice(VOCAB))
            else:
                new.extend(rng.sample([line, rng.choice(VOCAB)], 2))
        _, passed = external_fixer._hunks(
            list(old), new, list(range(1, len(old) + 1)), {i + 1 for i in claimed}, 100
        )
        if passed:
            kept += 1
            assert legal(old, claimed, tuple(new)), (old, sorted(claimed), new)
    assert kept > 100


# Width.


def line_of(width: int) -> str:
    """`A = kit.old_a('...')` of `width` characters, the newline not counted."""
    fill = "x" * (width - len("A = kit.old_a('')"))
    return f"A = kit.old_a('{fill}')\n"


@pytest.mark.parametrize("width", [98, 99, 100, 140])
def test_a_line_already_at_the_layout_width_may_grow_by_a_character(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, width: int
) -> None:
    tool(monkeypatch, made("out = data.replace(b'kit.old_a', b'kit.new_a1')"))
    assert run(tmp_path, "import acme.kit as kit\n" + line_of(width)).written


def test_a_line_the_tool_widens_past_the_layout_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    widen = "out = data.replace(b'kit.old_a(1)', b'kit.old_a(' + b'1' * 120 + b')')"
    tool(monkeypatch, made(widen))
    done = run(tmp_path, "import acme.kit as kit\nA = kit.old_a(1)\n")
    assert done.written == ()
    assert "external_fix_out_of_scope" in {row.reason for row in done.edits}


def test_width_is_counted_in_characters_and_not_in_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch, made("out = data.replace(b'kit.old_a', b'kit.new_a1')"))
    text = line_of(90).replace("x" * 20, "é" * 20, 1)
    assert len(text) - 1 == 90
    assert len(text.encode()) - 1 == 110
    assert run(tmp_path, "import acme.kit as kit\n" + text).written


# The release a tool prints.


@pytest.mark.parametrize(
    "printed",
    ["ruff 0.16.8+dirty", "v0.16.8", "0.17.2rc1", "0.16.8-dev", "ruff 0.16", "ruff (0.16.8)"],
)
def test_only_a_release_in_its_plain_spelling_is_accepted(
    monkeypatch: pytest.MonkeyPatch, printed: str
) -> None:
    tool(monkeypatch, made(releases=">=0.6.2,<=0.17.3", probe=f"print({printed!r})"))
    with pytest.raises(BailError) as raised:
        fixers.ready("ruff:NPY201")
    assert raised.value.reason == "external_tool_version_unsupported"
    tool(monkeypatch, made(releases=">=0.6.2,<=0.17.3", probe="print('ruff 0.16.8')"))
    assert fixers.ready("ruff:NPY201")[1] == "0.16.8"


@SHEBANG
def test_a_tool_that_was_replaced_is_asked_for_its_release_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    program = tmp_path / "bin" / "obelize-replaced-tool"
    program.parent.mkdir()

    def install(release: str) -> None:
        program.write_text(f"#!{sys.executable}\nprint('tool {release}')\n")
        program.chmod(0o755)

    spec = made(releases=">=1,<3")
    probe = ("-c", "")
    tool(monkeypatch, fixers.Fixer(program.name, spec.releases, spec.argv, spec.install, probe))
    monkeypatch.setenv("PATH", str(program.parent))
    install("1.0.0")
    assert fixers.ready("ruff:NPY201")[1] == "1.0.0"
    install("2.10.0")
    assert fixers.ready("ruff:NPY201")[1] == "2.10.0"


# What a tool cannot do to the machine.

DEAD_S = 10.0


def gone(pid: int) -> bool:
    deadline = time.monotonic() + DEAD_S
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not alive(pid)


def pids(record: Path) -> list[int]:
    return [int(word) for word in record.read_text().split()]


def test_a_tool_that_prints_without_end_is_stopped_at_the_limit_and_does_not_outlive_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = tmp_path / "pid"
    body = (
        f"import os\nopen({str(record)!r}, 'w').write(str(os.getpid()))\n"
        "while True:\n    sys.stdout.buffer.write(b'#' * 65536)\n    sys.stdout.buffer.flush()\n"
    )
    tool(monkeypatch, made(body))
    monkeypatch.setattr(fixers, "LIMIT", 1 << 17)
    began = time.monotonic()
    with pytest.raises(BailError) as raised:
        fixers.run("ruff:NPY201", "a.py", b"x = 1\n")
    assert raised.value.reason == "external_tool_size_limit"
    assert time.monotonic() - began < DEAD_S
    assert gone(pids(record)[0])


def test_a_tool_past_its_deadline_takes_what_it_started_with_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = tmp_path / "pids"
    body = (
        "import os, subprocess, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(record)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
        "time.sleep(120)\n"
    )
    tool(monkeypatch, made(body))
    monkeypatch.setattr(fixers, "TIMEOUT_S", 1.5)
    with pytest.raises(BailError) as raised:
        fixers.run("ruff:NPY201", "a.py", b"x = 1\n")
    assert raised.value.reason == "external_tool_timeout"
    assert all(gone(pid) for pid in pids(record))


def test_a_tool_that_exits_leaving_a_child_on_its_pipe_does_not_hold_the_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = tmp_path / "pids"
    body = (
        "import subprocess\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(record)!r}, 'w').write(str(child.pid))\n"
        "out = data\n"
    )
    tool(monkeypatch, made(body))
    monkeypatch.setattr(fixers, "DRAIN_S", 0.5)
    began = time.monotonic()
    assert fixers.run("ruff:NPY201", "a.py", b"x = 1\n").output == b"x = 1\n"
    assert time.monotonic() - began < DEAD_S
    assert gone(pids(record)[0])


def test_a_tool_that_closes_its_output_and_keeps_running_is_past_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool(monkeypatch, made("import os, time\nos.close(1)\ntime.sleep(120)\nout = b''"))
    monkeypatch.setattr(fixers, "TIMEOUT_S", 1.5)
    with pytest.raises(BailError) as raised:
        fixers.run("ruff:NPY201", "a.py", b"x = 1\n")
    assert raised.value.reason == "external_tool_timeout"


# The pin.

ONE = "import numpy as np\n\nSCALAR = np.float_(1)\n"
FLOAT = "out = data.replace(b'np.float_', b'np.float64')"


def pinned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: dict[str, str]) -> codemod.Run:
    tool(monkeypatch, made(FLOAT))
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return migrate(tmp_path, NUMPY_SPEC, LOADED.pack)


@pytest.mark.parametrize("requirement", ["numpy>=1.22", "numpy>=1.22,<3", "numpy", "numpy>=2"])
def test_a_requirement_that_admits_numpy_2_is_left_as_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requirement: str
) -> None:
    done = pinned(monkeypatch, tmp_path, {"app.py": ONE, "requirements.txt": f"{requirement}\n"})
    assert [row.path for row in done.written] == ["app.py"]


@pytest.mark.parametrize("requirement", ["numpy==1.26.4", "numpy<2", "numpy~=1.22"])
def test_a_requirement_that_excludes_numpy_2_is_moved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requirement: str
) -> None:
    done = pinned(monkeypatch, tmp_path, {"app.py": ONE, "requirements.txt": f"{requirement}\n"})
    assert {row.path: row.after for row in done.written}["requirements.txt"] == b"numpy>=2\n"


def test_a_requirement_with_an_environment_marker_is_reported_and_holds_the_repository_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text = "numpy<1.22; python_version < '3.9'\nnumpy>=1.22; python_version >= '3.9'\n"
    done = pinned(monkeypatch, tmp_path, {"app.py": ONE, "requirements.txt": text})
    assert done.written == ()
    held = {row.rule_id for row in done.edits if row.reason == "manifest_pin_shape_unsupported"}
    assert held == {"dependency"}


def test_a_pin_that_excludes_numpy_2_is_moved_and_the_pins_beside_it_are_not_judged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml = '[project]\ndependencies = ["numpy==1.26.4", "pandas==1.5.3", "scipy==1.10.1"]\n'
    done = pinned(monkeypatch, tmp_path, {"app.py": ONE, "pyproject.toml": toml})
    after = {row.path: row.after for row in done.written}["pyproject.toml"]
    assert after.decode() == toml.replace("numpy==1.26.4", "numpy>=2")


def test_a_version_nobody_can_read_is_reported_and_not_rewritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    toml = '[tool.poetry.dependencies]\nnumpy = "whatever"\n'
    done = pinned(monkeypatch, tmp_path, {"app.py": ONE, "pyproject.toml": toml})
    assert done.written == ()
    assert "manifest_pin_shape_unsupported" in {row.reason for row in done.edits}


# `pack test` and `scan` on a machine without the tool.


def failed(reason: BailCode) -> None:
    result = runner_.invoke(app, ["pack", "test", NUMPY])
    assert result.exit_code == 7, result.output
    assert "bug in obelize" not in result.output
    assert f"uv tool install {fixers.FIXERS['ruff:NPY201'].install}" in result.output
    assert reason in result.output
    assert result.output.count("FAIL") == 5
    assert result.output.count("not run: it needs the tool above") == 4


def test_pack_test_without_the_tool_exits_seven_and_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    failed("external_tool_missing")


def test_pack_test_with_a_release_it_has_not_measured_exits_seven_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = fixers.FIXERS["ruff:NPY201"]
    name = Path(sys.executable).name
    probe = ("-c", "print('ruff 0.17.4')")
    tool(monkeypatch, fixers.Fixer(name, real.releases, real.argv, real.install, probe))
    failed("external_tool_version_unsupported")


def test_scan_says_when_what_it_found_cannot_be_written_for_want_of_a_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = committed(tmp_path / "repo", {"app.py": ONE})
    tool(monkeypatch, made(releases="==1.0.0"))
    result = runner_.invoke(app, ["scan", "--repo", str(repo), "--pack", NUMPY])
    assert result.exit_code == 0, result.output
    assert "found what it can write only with a tool that cannot run here" in result.output
    assert "external_tool_version_unsupported" in result.output
    tool(monkeypatch, made(releases="==9.9.9"))
    quiet = runner_.invoke(app, ["scan", "--repo", str(repo), "--pack", NUMPY])
    assert "cannot run here" not in quiet.output
