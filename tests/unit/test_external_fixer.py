"""`external_fixer`: a tool's rewrite is kept only if it holds to the proof of a rule's own.

The tool is a Python one-liner standing in for ruff, started like the real one, so the suite is
offline and runs on every system; `tests/packs/test_all_packs.py` runs the real ruff over the numpy
pack. A pack of an invented library whose module keeps its name has one fixer, a `rewrite_pattern`
that writes a line and an import, and a flagged name that holds a file back (ADR-074).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import BAIL_CODES, FIXER_IDS, Config
from obelize.packs import loader
from obelize.packs.schema import (
    ExternalFixerChange,
    ExternalFixerParams,
    FlagOnlyChange,
    FlagOnlyParams,
    Legacy,
    Match,
    PackDocument,
    PackSource,
    RewritePatternChange,
    RewritePatternParams,
    Target,
)
from obelize.packtools import check
from obelize.scan import runner
from obelize.transforms import codemod, fixers
from obelize.transforms.base import BailError
from obelize.transforms.kinds import external_fixer
from support import committed, migrate

if TYPE_CHECKING:
    from obelize.models import BailCode, FixerId

FIXTURES = ("fixtures/negative/none.py", "fixtures/positive/one.before.py")
TOOL = ExternalFixerChange(
    id="tool",
    kind="external_fixer",
    citation="Acme Kit 2 notes, 'Names'",
    fixtures=FIXTURES,
    params=ExternalFixerParams(fixer="ruff:NPY201", symbols=("acme.kit.old_a", "acme.kit.old_b")),
)
DUMP = RewritePatternChange(
    id="dump",
    kind="rewrite_pattern",
    citation="Acme Kit 2 notes, 'Dumping'",
    fixtures=FIXTURES,
    params=RewritePatternParams(
        before="acme.kit.dump($x)", after="json.dumps($x)", imports=("json",)
    ),
)
GONE = FlagOnlyChange(
    id="gone",
    kind="flag_only",
    citation="Acme Kit 2 notes, 'Dropped'",
    fixtures=FIXTURES,
    params=FlagOnlyParams(
        message="acme.kit 2 dropped it.", suggestion="Port by hand.", symbols=("acme.kit.gone",)
    ),
)
PACK = PackDocument(
    id="acme/acme-kit-fixed",
    pack_version="0.1.0",
    provider="acme",
    language="python",
    source=PackSource(
        type="official_guide",
        url="https://example.invalid/acme-kit",
        retrieved_at=dt.date(2026, 10, 27),
    ),
    **{"from": Legacy(package="acme-kit", version="<2")},
    to=Target(package="acme-kit", version=">=2", requires_python=">=3.9"),
    match=Match(
        imports=("acme.kit",),
        shared=True,
        symbols=(
            "acme.kit.dump",
            "acme.kit.gone",
            "acme.kit.old_a",
            "acme.kit.old_b",
        ),
        prefilter_tokens=("dump", "gone", "old_a", "old_b"),
    ),
    changes=(TOOL, DUMP, GONE),
    limitations=("Invented for the tests; no library of this name exists.",),
)
SPEC = loader.to_scan_spec(
    loader.LoadedPack(
        pack=PACK,
        sha256="0" * 64,
        data=b"",
        reference=PACK.id,
        bundled=False,
        path=Path("pack.yaml"),
    )
)

SOURCE = "import acme.kit as kit\n\nA = kit.old_a(1)\nUNRELATED = 1\nB = kit.old_b(2)\n"
RENAMES = "out = data.replace(b'kit.old_a', b'kit.new_a').replace(b'kit.old_b', b'kit.new_b')"
FIXED = SOURCE.replace("old_a", "new_a").replace("old_b", "new_b")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def made(
    body: str = RENAMES,
    *,
    version: str = "9.9.9",
    releases: str = "==9.9.9",
    probe: str | None = None,
    record: Path | None = None,
) -> fixers.Fixer:
    """The interpreter, started as a fixer is, running `body` over `data` to make `out`."""
    script = f"import sys\ndata = sys.stdin.buffer.read()\n{body}\nsys.stdout.buffer.write(out)\n"
    if record is not None:
        script = (
            "import json, os, sys\n"
            "json.dump({'cwd': os.getcwd(), 'listing': os.listdir('.'), 'env': sorted(os.environ),"
            " 'argv': sys.argv[1:]}, open(sys.argv[1], 'w'))\n" + script
        )
    # One line, so no system reads a newline in a command line differently.
    argv = ("-c", f"exec({script!r})", str(record) if record else "unused", "{name}")
    name = Path(sys.executable).name
    return fixers.Fixer(
        name, releases, argv, f"{name}==9.9.9", ("-c", probe or f"print('fake {version}')")
    )


def tool(monkeypatch: pytest.MonkeyPatch, spec: fixers.Fixer | None = None) -> None:
    """`spec` for the one fixer the registry holds, and the interpreter's folder on the `PATH`."""
    monkeypatch.setattr(fixers, "FIXERS", {"ruff:NPY201": spec or made()})
    monkeypatch.setenv("PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")


def run(tmp_path: Path, source: str = SOURCE) -> codemod.Run:
    (tmp_path / "app.py").write_bytes(source.encode())
    return migrate(tmp_path, SPEC, PACK)


def codes(done: codemod.Run) -> set[BailCode]:
    return {row.reason for row in done.edits if row.reason is not None}


def test_the_registry_holds_the_ids_the_vocabulary_names() -> None:
    assert set(fixers.FIXERS) == FIXER_IDS
    assert external_fixer.BAILS <= BAIL_CODES
    for fixer in fixers.FIXERS.values():
        assert fixer.install.startswith(f"{fixer.tool}==")
        assert Version(fixer.install.partition("==")[2]) in SpecifierSet(fixer.releases)


def test_a_tool_that_changes_only_the_lines_the_scan_reported_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch)
    done = run(tmp_path)
    (outcome,) = done.files
    assert outcome.after.decode() == FIXED
    assert [(row.line, row.status, row.rule_id) for row in outcome.edits] == [
        (3, "auto", "tool"),
        (5, "auto", "tool"),
    ]
    (made,) = done.fixes
    assert (made.fixer, made.path, made.version, made.lines) == (
        "ruff:NPY201",
        "app.py",
        "9.9.9",
        2,
    )
    assert (made.before_sha256, made.after_sha256) == (sha(SOURCE.encode()), sha(FIXED.encode()))


def test_a_tool_may_add_an_import_and_the_unresolved_names_net_sees_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = (
        "out = data.replace(b'kit.old_a', b'json.loads')\n"
        "out = out if b'import json' in out else b'import json\\n' + out"
    )
    tool(monkeypatch, made(body))
    done = run(tmp_path, "import acme.kit as kit\n\nA = kit.old_a('1')\n")
    assert done.files[0].after == b"import json\nimport acme.kit as kit\n\nA = json.loads('1')\n"
    assert done.fixes[0].lines == 2
    tool(monkeypatch, made("out = data.replace(b'kit.old_a', b'json.loads')"))
    held = run(tmp_path, "import acme.kit as kit\n\nA = kit.old_a('1')\n")
    assert codes(held) == {"output_names_unresolved"}
    assert held.written == ()


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("sys.exit(3)", "external_tool_failed"),
        ("import time\ntime.sleep(30)\nout = data", "external_tool_timeout"),
        ("out = data + b'#' * 200", "external_tool_size_limit"),
        ("out = data", "external_fix_incomplete"),
        (RENAMES + ".replace(b'UNRELATED', b'CHANGED')", "external_fix_out_of_scope"),
        (
            RENAMES + ".replace(b'new_a(1)', b'new_a(' + b'1' * 90 + b')')",
            "external_fix_out_of_scope",
        ),
        (RENAMES.replace("out = ", "out = b'print(1)\\n' + "), "external_fix_out_of_scope"),
        (RENAMES.replace("out = ", "out = b'import (\\n' + "), "external_fix_out_of_scope"),
        (
            "out = data.replace(b'kit.new_b', b'kit.new_c')" + RENAMES.removeprefix("out = data"),
            "external_fix_not_idempotent",
        ),
        ("out = data.replace(b'kit.old_a', b'kit.new_a')", "external_fix_incomplete"),
        ("out = data.replace(b'kit.old_a', b'kit.old_b')", "external_fix_incomplete"),
        (RENAMES.replace("new_b'", "new_b('"), "output_does_not_parse"),
        (RENAMES.replace("kit.new_b", "missing"), "output_names_unresolved"),
    ],
    ids=[
        "exit",
        "timeout",
        "output too large",
        "nothing changed",
        "another line",
        "wider than the layout",
        "not an import",
        "not even a statement",
        "not idempotent",
        "one use left",
        "swapped for a legacy name",
        "does not parse",
        "unresolved name",
    ],
)
def test_a_tool_that_breaks_the_proof_leaves_the_file_as_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str, code: BailCode
) -> None:
    monkeypatch.setattr(fixers, "TIMEOUT_S", 1.5)
    tool(monkeypatch, made(body))
    monkeypatch.setattr(fixers, "LIMIT", len(SOURCE) + 100)
    done = run(tmp_path)
    assert done.written == ()
    assert code in codes(done)
    assert not {row.status for row in done.edits} & {"auto"}
    assert {row.scan_status for plan in done.plans for row in plan.findings} == {"needs_review"}


def test_a_tool_that_leaves_one_use_withholds_that_use_and_holds_the_rest_by_atomicity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch, made("out = data.replace(b'kit.old_a', b'kit.new_a')"))
    (plan,) = run(tmp_path).plans
    assert [(row.line, row.symbol, row.bail) for row in plan.findings] == [
        (3, "acme.kit.old_a", "file_not_fully_migrated"),
        (5, "acme.kit.old_b", "external_fix_incomplete"),
    ]


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        ("missing", "external_tool_missing"),
        ("version", "external_tool_version_unsupported"),
        ("number", "external_tool_version_unsupported"),
        ("start", "external_tool_failed"),
        ("probe", "external_tool_failed"),
        ("silent", "external_tool_failed"),
        ("size", "external_tool_size_limit"),
    ],
)
def test_a_tool_that_cannot_run_here_leaves_the_file_and_says_which_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, setup: str, code: BailCode
) -> None:
    tool(monkeypatch)
    if setup == "missing":
        monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    elif setup == "version":
        tool(monkeypatch, made(releases="==1.0.0"))
    elif setup == "number":
        tool(monkeypatch, made(version="nightly"))
    elif setup == "start":
        # Found, and no program: a script for an interpreter that is not there, or text named .exe.
        name = "obelize-broken-tool" + (".exe" if sys.platform == "win32" else "")
        program = tmp_path / "bin" / name
        program.parent.mkdir()
        program.write_bytes(b"not a program" if sys.platform == "win32" else b"#!/no/such\n")
        program.chmod(0o755)
        tool(monkeypatch, replace(made(), tool=name))
        monkeypatch.setenv("PATH", str(program.parent))
    elif setup in {"probe", "silent"}:
        tool(monkeypatch, made(probe="raise SystemExit(4)" if setup == "probe" else "pass"))
    else:
        monkeypatch.setattr(fixers, "LIMIT", 5)
    done = run(tmp_path)
    assert done.written == ()
    assert codes(done) == {code}
    assert done.fixes == ()


def test_a_line_another_rule_wrote_is_not_the_tools_to_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The rewrite of `dump` adds an import above, so every line the tool reads has moved down; it
    is the mapping back that tells a line the scan reported from one a rule wrote."""
    tool(monkeypatch, made("out = data.replace(b'old_a', b'new_a')"))
    apart = run(tmp_path, "import acme.kit as kit\n\nA = kit.old_a(1)\nB = kit.dump([])\n")
    assert apart.files[0].after.decode() == (
        "import acme.kit as kit\nimport json\n\nA = kit.new_a(1)\nB = json.dumps([])\n"
    )
    assert apart.fixes[0].before_sha256 == sha(apart.files[0].after.replace(b"new_a", b"old_a"))
    same = run(tmp_path, "import acme.kit as kit\n\nB = kit.dump(kit.old_a(1))\n")
    assert same.written == ()
    assert "external_fix_out_of_scope" in codes(same)


def test_a_file_another_rule_withholds_is_not_given_to_the_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`dump` takes one argument, so a call that gives two is the pattern's refusal at fix time,
    when the scan has graded every row `eligible`."""
    tool(monkeypatch)
    done = run(tmp_path, SOURCE + "C = kit.dump(1, 2)\n")
    assert done.fixes == ()
    assert done.written == ()
    assert {(row.rule_id, row.status, row.reason) for row in done.edits} == {
        ("dump", "needs_review", "pattern_unmatched"),
        ("tool", "needs_review", "file_not_fully_migrated"),
    }
    assert {row.caused_by for row in done.edits if row.rule_id == "tool"} == {
        ("pattern_unmatched",)
    }


def test_the_tool_is_started_in_an_empty_directory_with_a_few_variables_and_the_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("GITHUB_TOKEN", "RUFF_NO_CACHE", "RUFF_OUTPUT_FORMAT"):
        monkeypatch.setenv(name, "x")
    record = tmp_path / "record.json"
    tool(monkeypatch, made(record=record))
    work = tmp_path / "repo"
    work.mkdir()
    run(work)
    seen = json.loads(record.read_text())
    assert seen["listing"] == []
    assert not Path(seen["cwd"]).is_relative_to(work)
    assert seen["argv"][1:] == ["app.py"]
    assert "PATH" in seen["env"]
    assert not {"GITHUB_TOKEN", "RUFF_NO_CACHE", "RUFF_OUTPUT_FORMAT"} & set(seen["env"])
    assert fixers.environment({"HOME": "/h", "PATH": "/p", "AWS_SECRET_ACCESS_KEY": "s"}) == {
        "HOME": "/h",
        "PATH": "/p",
    }


def test_a_tool_is_found_only_among_the_absolute_entries_of_the_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch)
    here = Path(sys.executable).parent
    monkeypatch.chdir(here.parent)
    with pytest.raises(BailError) as raised:
        fixers.ready("ruff:NPY201", {"PATH": here.name})
    assert raised.value.reason == "external_tool_missing"
    assert fixers.ready("ruff:NPY201", {"PATH": f"{here.name}{os.pathsep}{here}"})[1] == "9.9.9"


def test_what_a_person_runs_to_install_a_tool_is_said_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch)
    assert fixers.problem("ruff:NPY201") is None
    monkeypatch.setenv("PATH", str(tmp_path))
    said = fixers.problem("ruff:NPY201")
    assert said is not None
    assert "external_tool_missing" in said
    assert f"uv tool install {Path(sys.executable).name}==9.9.9" in said
    loaded = loader.LoadedPack(PACK, "0" * 64, b"", PACK.id, False, Path("pack.yaml"))
    assert check._tools(loaded, tmp_path) == [said]


def test_two_fixers_run_in_turn_and_the_second_reads_what_the_first_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The registry holds one id, so a second is made up here: one tool renames `old_a` and the
    other `old_b`, and the second is handed the first's output."""
    one = made("out = data.replace(b'kit.old_a', b'kit.new_a')")
    other = made("out = data.replace(b'kit.old_b', b'kit.new_b')")
    monkeypatch.setattr(fixers, "FIXERS", {"ruff:NPY201": one, "ruff:OTHER": other})
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent))
    (tmp_path / "app.py").write_bytes(SOURCE.encode())
    (result,) = runner.scan(tmp_path, Config(), SPEC, jobs=1).results
    rules = [
        external_fixer.ExternalFixer(TOOL.model_copy(update={"params": params}))
        for params in (
            ExternalFixerParams.model_construct(fixer="ruff:NPY201", symbols=("acme.kit.old_a",)),
            ExternalFixerParams.model_construct(
                fixer=cast("FixerId", "ruff:OTHER"), symbols=("acme.kit.old_b",)
            ),
        )
    ]
    data = SOURCE.encode()
    done = external_fixer.fix(rules, result, data, data, SPEC, 100, live=True)
    assert done.after.decode() == FIXED
    assert done.withheld == {}
    assert [row.status for row in done.edits] == ["auto", "auto"]
    assert done.ran[1].before_sha256 == done.ran[0].after_sha256
    assert done.ran[1].after_sha256 == sha(done.after)


NUMPY = "numpy/numpy-1-to-2"
USES = "import numpy as np\n\nSCALAR = np.float_(1)\n"
runner_ = CliRunner()


def test_fix_says_what_it_runs_before_it_writes_and_the_record_holds_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch, made("out = data.replace(b'np.float_', b'np.float64')"))
    repo = committed(tmp_path / "repo", {"app.py": USES, "requirements.txt": "numpy==1.26.4\n"})
    dry = runner_.invoke(app, ["fix", "--repo", str(repo), "--pack", NUMPY])
    assert dry.exit_code == 0, dry.output
    assert "numpy/numpy-1-to-2 runs ruff (NPY201) on 1 file.\n" in dry.output
    assert dry.output.index("runs ruff") < dry.output.index("+SCALAR = np.float64(1)")
    assert (repo / "app.py").read_text() == USES

    applied = runner_.invoke(
        app, ["fix", "--repo", str(repo), "--pack", NUMPY, "--apply", "--json"]
    )
    assert applied.exit_code == 6, applied.output
    run_id = (repo / ".obelize" / "latest").read_text().strip()
    record = json.loads((repo / ".obelize" / "runs" / run_id / "run.json").read_text())
    assert (repo / "app.py").read_text() == USES.replace("float_", "float64")
    assert (repo / "requirements.txt").read_text() == "numpy>=2\n"
    (row,) = record["packs"][0]["fixers"]
    spec = fixers.FIXERS["ruff:NPY201"]
    assert (row["fixer"], row["tool"], row["version"], row["argv"]) == (
        "ruff:NPY201",
        spec.tool,
        "9.9.9",
        list(spec.argv),
    )
    assert row["files"] == [
        {
            "path": "app.py",
            "before_sha256": sha(USES.encode()),
            "after_sha256": sha(USES.replace("float_", "float64").encode()),
            "lines": 1,
        }
    ]
    undone = runner_.invoke(app, ["undo", "--repo", str(repo), "--run", record["run_id"]])
    assert undone.exit_code == 0, undone.output
    assert (repo / "app.py").read_text() == USES
    assert (repo / "requirements.txt").read_text() == "numpy==1.26.4\n"


def test_a_missing_tool_leaves_the_repository_and_the_report_says_which_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool(monkeypatch, replace(made(), tool="obelize-no-such-tool"))
    repo = committed(tmp_path / "repo", {"app.py": USES, "requirements.txt": "numpy==1.26.4\n"})
    result = runner_.invoke(app, ["fix", "--repo", str(repo), "--pack", NUMPY, "--apply"])
    assert result.exit_code == 4, result.output
    assert "external_tool_missing" in result.output
    assert "runs ruff" not in result.output
    assert (repo / "app.py").read_text() == USES
    assert (repo / "requirements.txt").read_text() == "numpy==1.26.4\n"


def test_pack_validate_prints_the_tool_a_fixer_runs_and_what_installs_it() -> None:
    result = runner_.invoke(app, ["pack", "validate", NUMPY])
    spec = fixers.FIXERS["ruff:NPY201"]
    assert result.exit_code == 0, result.output
    assert f"  fixer        ruff:NPY201 runs {spec.tool} {' '.join(spec.argv)}\n" in result.output
    assert f"accepts {spec.tool} {spec.releases}; obelize installs nothing: " in result.output
    assert f"uv tool install {spec.install}\n" in result.output


def test_pack_test_of_a_bundled_pack_blames_the_machine_and_not_obelize_for_a_missing_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    failed = [r for r in check.run(loader.load(NUMPY)) if not r.ok and r.setup]
    assert [r.name for r in failed] == [
        "the tools the pack's fixers run are installed at a release it accepts"
    ]
    monkeypatch.setattr(check, "run", lambda loaded: tuple(failed))
    result = runner_.invoke(app, ["pack", "test", NUMPY])
    assert result.exit_code == 7
    assert "uv tool install" in result.output
    assert "bug in obelize" not in result.output
