"""A notebook is read for the legacy API, cell by cell, and never written.

Under the default `include` a notebook was `unanalysed` as soon as its bytes named the library, so
it held the pin whether or not it called the old API: three of the five notebooks in the openai
frame only installed a package or used the new client. Its code cells are now run as the one module
they are, and it holds the pin only where a row of the legacy API appears, with the cell named.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pdf_repo import git_repo
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import Config
from obelize.packs import loader
from obelize.scan import analysis, parse, runner
from platforms import PYTHON

OPENAI = loader.to_scan_spec(loader.load("openai/openai-0-to-1"))
OLD = "import openai\nr = openai.ChatCompletion.create(model='m', messages=[])\n"
NEW = "from openai import OpenAI\nclient = OpenAI()\n"


def cell(source: str | list[str], kind: str = "code") -> dict[str, Any]:
    return {"cell_type": kind, "metadata": {}, "source": source}


def book(*cells: dict[str, Any]) -> bytes:
    document = {"cells": list(cells), "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(document, indent=1).encode()


# The cells as one module.


def test_the_code_cells_are_one_module_and_each_is_found_by_its_place_among_all_cells() -> None:
    data = book(
        cell("# Title", "markdown"),
        cell(["import openai\n", "x = 1"]),
        cell("raw text", "raw"),
        cell("y = x + 1\nz = y\n"),
    )
    found = parse.notebook(data)
    assert found is not None
    assert found.source == b"import openai\nx = 1\ny = x + 1\nz = y\n\n"
    assert found.cells == ((1, 2), (3, 4))
    assert [found.cell(line) for line in (1, 2, 3, 4, 5)] == [2, 2, 4, 4, 4]


def test_a_line_magic_stays_as_a_line_that_does_nothing_and_keeps_its_indent() -> None:
    data = book(
        cell("%matplotlib inline\n!pip install openai\nimport openai"),
        cell("for item in range(2):\n    %time item\n    !echo $item\n"),
    )
    found = parse.notebook(data)
    assert found is not None
    assert found.source == (
        b"pass\npass\nimport openai\nfor item in range(2):\n    pass\n    pass\n\n"
    )
    assert parse.gates("n.ipynb", found.source).status == "parsed"


def test_a_cell_magic_is_no_python_and_leaves_its_cell_out() -> None:
    data = book(cell("%%bash\npip install openai\n"), cell("import openai\n"))
    found = parse.notebook(data)
    assert found is not None
    assert found.source == b"import openai\n\n"
    assert found.cells == ((1, 2),)


def test_a_notebook_with_no_code_is_an_empty_module() -> None:
    found = parse.notebook(book(cell("# only prose", "markdown")))
    assert found is not None
    assert (found.source, found.cells) == (b"\n", ())


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b"\xff\xfe\x00",
        b"[]",
        b'{"cells": {"a": 1}}',
        b'{"worksheets": []}',
        b'{"cells": [1]}',
        b'{"cells": [{"cell_type": "code", "source": 5}]}',
        b'{"cells": [{"cell_type": "code", "source": ["a", 3]}]}',
        b"[" * 100_000,
    ],
    ids=[
        "not-json",
        "not-text",
        "a-list",
        "cells-not-a-list",
        "nbformat-3",
        "a-cell-that-is-not-a-mapping",
        "a-source-that-is-a-number",
        "a-source-part-that-is-a-number",
        "nested-too-deep",
    ],
)
def test_what_is_not_a_list_of_cells_with_text_sources_is_not_read(data: bytes) -> None:
    assert parse.notebook(data) is None


def test_a_cell_may_await_at_its_top_level_where_a_module_may_not() -> None:
    source = b"import asyncio\nawait asyncio.sleep(0)\n"
    assert parse.gates("n.ipynb", source).status == "does_not_parse"
    assert parse.gates("n.ipynb", source, notebook=True).status == "parsed"


# What a scan makes of them.


def scanned(root: Path, config: Config | None = None) -> runner.Scan:
    return runner.scan(root, config or Config(), OPENAI, jobs=1)


def repository(root: Path, files: Mapping[str, str | bytes]) -> Path:
    return git_repo(root, {"requirements.txt": "openai==0.28.1\n", **files})


def test_a_notebook_that_calls_the_legacy_api_holds_the_pin_and_names_its_cell(
    tmp_path: Path,
) -> None:
    data = book(cell("# Ask", "markdown"), cell(NEW), cell(OLD))
    scan = scanned(repository(tmp_path, {"n.ipynb": data}))
    assert scan.unwritten == (("n.ipynb", (3,)),)
    assert scan.unanalysed == ("n.ipynb",)
    assert scan.manifests.blocking == ("n.ipynb",)
    assert [(row.scan_status, row.bail) for row in scan.manifests.findings] == [
        ("needs_review", "repo_not_fully_migrated")
    ]
    assert scan.findings == scan.manifests.findings
    assert runner.applies(scan) is True
    assert scan.limitations == ()


def test_every_cell_that_calls_it_is_named_once_in_order(tmp_path: Path) -> None:
    data = book(cell(OLD), cell(NEW), cell(OLD + OLD), cell("# done", "markdown"))
    scan = scanned(repository(tmp_path, {"n.ipynb": data}))
    assert scan.unwritten == (("n.ipynb", (1, 3)),)


@pytest.mark.parametrize(
    "data",
    [
        book(cell(NEW)),
        book(cell("!pip install git+https://github.com/openai/CLIP.git\n"), cell("import clip\n")),
        book(cell("This notebook once called openai.ChatCompletion.", "markdown"), cell("x = 1")),
        book(cell("%%bash\npip install openai==0.28.1\n")),
        book(cell("# openai.ChatCompletion.create was removed\n", "code")),
        book(cell("import openai\nopenai.api_key = 'k'\n")),
    ],
    ids=["the-new-client", "a-shell-line", "prose", "a-cell-magic", "a-comment", "only-settings"],
)
def test_a_notebook_that_names_the_library_and_does_not_call_the_old_api_holds_nothing(
    tmp_path: Path, data: bytes
) -> None:
    scan = scanned(repository(tmp_path, {"n.ipynb": data}))
    assert (scan.unwritten, scan.unanalysed, scan.manifests.blocking) == ((), (), ())
    assert scan.limitations == ()
    assert [row.scan_status for row in scan.manifests.findings] == ["not_a_usage"]


def test_a_repository_whose_only_notebook_is_clean_is_migrated_whole(tmp_path: Path) -> None:
    files: dict[str, str | bytes] = {"app.py": OLD, "n.ipynb": book(cell(NEW))}
    scan = scanned(repository(tmp_path, files))
    assert [row.scan_status for row in scan.manifests.findings] == ["eligible"]
    assert scan.unanalysed == ()


def test_a_notebook_that_awaits_at_the_top_is_read_like_the_rest(tmp_path: Path) -> None:
    code = "import openai\nresponse = await openai.ChatCompletion.acreate(model='m', messages=[])\n"
    scan = scanned(repository(tmp_path, {"n.ipynb": book(cell(code))}))
    assert scan.unwritten == (("n.ipynb", (1,)),)


def test_a_notebook_that_is_no_notebook_is_a_limitation_and_still_holds_the_pin(
    tmp_path: Path,
) -> None:
    text = '{"not": "cells", "text": "openai.ChatCompletion"}'
    scan = scanned(repository(tmp_path, {"n.ipynb": text}))
    assert scan.limitations == (
        parse.Limitation(path="n.ipynb", code="input_does_not_parse", detail=parse.NOTEBOOK),
    )
    assert scan.unanalysed == ("n.ipynb",)
    assert scan.unwritten == (("n.ipynb", ()),)


def test_a_notebook_with_no_name_of_the_api_is_held_and_not_named(tmp_path: Path) -> None:
    scan = scanned(repository(tmp_path, {"n.ipynb": '{"source": "import openai"}'}))
    assert scan.unanalysed == ("n.ipynb",)
    assert scan.unwritten == ()
    assert [row.code for row in scan.limitations] == ["input_does_not_parse"]


def test_a_cell_that_does_not_compile_is_a_limitation_that_names_the_cell(tmp_path: Path) -> None:
    data = book(cell("import openai\n"), cell("x = 1\n"), cell("def broken(:\n    pass\n"))
    scan = scanned(repository(tmp_path, {"n.ipynb": data}))
    [row] = scan.limitations
    assert (row.path, row.code) == ("n.ipynb", "input_does_not_parse")
    assert row.detail.startswith("Not valid Python for this interpreter")
    assert row.detail.endswith("It is in cell 3.")
    assert scan.unanalysed == ("n.ipynb",)
    assert scan.manifests.blocking == ("n.ipynb",)


def test_a_notebook_obelize_raises_on_is_a_defect_and_holds_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_arguments: object) -> object:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(analysis, "analyse", broken)
    scan = scanned(repository(tmp_path, {"n.ipynb": book(cell(OLD))}))
    [row] = scan.limitations
    assert (row.code, "RuntimeError" in row.detail, "secret" in row.detail) == (
        "internal_error",
        True,
        False,
    )
    assert scan.unanalysed == ("n.ipynb",)


def test_under_a_narrower_include_a_notebook_is_the_users_choice_and_is_not_read(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path, {"app.py": OLD, "n.ipynb": book(cell(OLD))})
    scan = scanned(root, Config(include="*.py"))
    assert (scan.unwritten, scan.unanalysed, scan.manifests.blocking) == ((), (), ())
    assert scan.manifests.excluded == ("n.ipynb",)


def test_a_notebook_the_user_excludes_is_not_read_either(tmp_path: Path) -> None:
    root = repository(tmp_path, {"app.py": OLD, "n.ipynb": book(cell(OLD))})
    scan = scanned(root, Config(exclude=("*.ipynb",)))
    assert (scan.unwritten, scan.unanalysed) == ((), ())
    assert scan.manifests.excluded == ("n.ipynb",)


def test_a_stub_or_a_script_that_names_the_old_api_is_named_and_one_that_does_not_is_only_held(
    tmp_path: Path,
) -> None:
    files: dict[str, str | bytes] = {
        "typing/openai_stubs.pyi": "import openai\nChat = openai.ChatCompletion\n",
        "gui.pyw": "import openai\n",
        "app.py": OLD,
    }
    scan = scanned(repository(tmp_path, files))
    assert scan.unanalysed == ("gui.pyw", "typing/openai_stubs.pyi")
    assert scan.unwritten == (("typing/openai_stubs.pyi", ()),)


def test_a_pack_whose_module_is_all_legacy_names_a_file_by_the_module(tmp_path: Path) -> None:
    spec = loader.to_scan_spec(loader.load("gemini/google-generativeai-to-google-genai"))
    root = git_repo(tmp_path, {"stubs.pyi": "import google.generativeai\n", "gui.pyw": "x = 1\n"})
    assert runner.scan(root, Config(), spec, jobs=1).unwritten == (("stubs.pyi", ()),)


def test_a_file_that_only_names_the_api_where_nothing_is_declared_is_a_pack_that_applies(
    tmp_path: Path,
) -> None:
    root = git_repo(tmp_path, {"n.ipynb": book(cell(OLD))})
    scan = scanned(root)
    assert scan.findings == ()
    assert runner.applies(scan) is True
    assert runner.applies(scanned(git_repo(tmp_path / "other", {"app.py": NEW}))) is False


def test_the_scans_of_several_packs_name_each_file_once(tmp_path: Path) -> None:
    root = repository(tmp_path, {"n.ipynb": book(cell(OLD))})
    first = scanned(root)
    tree = runner.read(root, Config(), (OPENAI,))
    assert runner.merged([first, first], tree).unwritten == (("n.ipynb", (1,)),)


# What the report says of them.

runner_ = CliRunner()
QUIET = f"{PYTHON} -c pass"


def command(tree: Path, *arguments: str) -> Any:
    return runner_.invoke(app, [*arguments, "--repo", str(tree)])


def raw(data: str | bytes) -> bytes:
    return data if isinstance(data, bytes) else data.encode()


def committed(root: Path, files: Mapping[str, str | bytes]) -> Path:
    root.mkdir(parents=True)
    for name, data in files.items():
        (root / name).write_bytes(raw(data))
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "work"], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@t.invalid")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "before"],
        check=True,
    )
    return root


def latest(tree: Path) -> Path:
    name = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return tree / ".obelize" / "runs" / name


SAYS = "use the legacy API and obelize does not write them"


def test_a_notebook_beside_a_pin_that_has_arrived_is_named_where_the_run_used_to_say_nothing(
    tmp_path: Path,
) -> None:
    files: dict[str, str | bytes] = {
        "requirements.txt": "openai>=1.109.1\n",
        "app.py": NEW,
        "n.ipynb": book(cell(NEW), cell(OLD)),
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "scan")
    assert result.exit_code == 0, result.output
    assert "No pack applies" not in result.output
    assert f"{SAYS}: n.ipynb (cell 2)." in result.output
    fixed = command(tree, "fix")
    assert fixed.exit_code == 0, fixed.output
    assert f"{SAYS}: n.ipynb (cell 2)." in fixed.output
    report = (latest(tree) / "REPORT.md").read_text(encoding="utf-8")
    assert f"Every selected path was read.\n\nThese files {SAYS}: `n.ipynb` (cell 2)." in report


def test_several_cells_and_a_stub_are_listed_in_one_sentence(tmp_path: Path) -> None:
    files: dict[str, str | bytes] = {
        "requirements.txt": "openai>=1.109.1\n",
        "n.ipynb": book(cell(OLD), cell(OLD)),
        "stubs.pyi": "import openai\nChat = openai.ChatCompletion\n",
    }
    result = command(committed(tmp_path / "repo", files), "scan")
    assert f"{SAYS}: n.ipynb (cells 1, 2), stubs.pyi." in result.output


def test_a_notebook_that_holds_the_pin_is_one_of_the_files_the_fix_names_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    files: dict[str, str | bytes] = {
        "app.py": OLD,
        "requirements.txt": "openai==0.28.1\n",
        "n.ipynb": book(cell(OLD)),
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert result.exit_code == 4, result.output
    assert "Not migrated by obelize, so they hold the pin: n.ipynb." in result.output
    assert f"{SAYS}: n.ipynb (cell 1)." in result.output
    for name, data in files.items():
        assert (tree / name).read_bytes() == raw(data), name


def test_a_notebook_obelize_never_writes_is_left_byte_for_byte_when_the_rest_migrates(
    tmp_path: Path,
) -> None:
    files: dict[str, str | bytes] = {
        "app.py": OLD,
        "requirements.txt": "openai==0.28.1\n",
        "n.ipynb": book(cell(NEW)),
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert result.exit_code == 0, result.output
    assert (tree / "requirements.txt").read_text(encoding="utf-8") == "openai>=1.109.1\n"
    assert (tree / "n.ipynb").read_bytes() == raw(files["n.ipynb"])
