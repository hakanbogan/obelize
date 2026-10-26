"""A repository meets the packs of the Python itself through the commands it already runs.

`scan` and `fix` choose a pack by the modules a repository imports and gate it by the Python the
repository declares, as for a library; the difference is that no dependency line moves.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from obelize.cli import app
from support import committed

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
CLOCK = (
    "from datetime import datetime\n\n\ndef stamp():\n    return datetime.utcnow().isoformat()\n"
)
PYTHON = '[project]\nname = "demo"\nversion = "0.1"\nrequires-python = "{}"\n'


def packs(root: Path, *arguments: str) -> list[str]:
    result = runner.invoke(app, ["scan", "--repo", str(root), "--json", *arguments])
    return [one["id"] for one in json.loads(result.stdout)["packs"]]


def test_a_repository_that_calls_utcnow_is_planned_for_the_datetime_pack_and_no_other(
    tmp_path: Path,
) -> None:
    root = committed(tmp_path / "repo", {"app.py": CLOCK})
    assert packs(root) == ["python/datetime-utcnow"]
    result = runner.invoke(app, ["fix", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "+from datetime import timezone" in result.output
    assert (
        "+    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()" in result.output
    )


def test_applying_it_writes_the_file_and_undo_puts_it_back(tmp_path: Path) -> None:
    root = committed(tmp_path / "repo", {"app.py": CLOCK})
    applied = runner.invoke(app, ["fix", "--repo", str(root), "--apply"])
    # Nothing was told to check the change, which ends an apply at 6 whatever the pack.
    assert applied.exit_code == 6, applied.output
    assert "install what this run wrote into the manifest" not in applied.output
    assert "obelize verify --run" in applied.output
    assert (root / "app.py").read_text(encoding="utf-8") == (
        "from datetime import datetime\nfrom datetime import timezone\n\n\ndef stamp():\n"
        "    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()\n"
    )
    run = (root / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    undone = runner.invoke(app, ["undo", "--run", run, "--repo", str(root)])
    assert undone.exit_code == 0, undone.output
    assert (root / "app.py").read_text(encoding="utf-8") == CLOCK


def test_a_repository_that_never_calls_it_is_left_to_no_pack(tmp_path: Path) -> None:
    root = committed(
        tmp_path / "repo", {"app.py": "from datetime import datetime\n\nnow = datetime.now()\n"}
    )
    assert packs(root) == []


def test_a_declared_python_the_new_spelling_does_not_run_on_blocks_the_pack(tmp_path: Path) -> None:
    root = committed(tmp_path / "repo", {"app.py": CLOCK, "pyproject.toml": PYTHON.format(">=2.7")})
    result = runner.invoke(app, ["fix", "--repo", str(root), "--apply"])
    assert "raise the minimum in pyproject.toml to >=3.2" in result.output
    assert "allows versions the new code of python/datetime-utcnow does not run on" in result.output
    assert (root / "app.py").read_text(encoding="utf-8") == CLOCK


def test_a_block_among_several_packs_names_the_pack_it_is_of(tmp_path: Path) -> None:
    source = (
        "import pipes\nfrom datetime import datetime\n\nx = pipes.quote(str(datetime.utcnow()))\n"
    )
    root = committed(
        tmp_path / "repo", {"app.py": source, "pyproject.toml": PYTHON.format(">=3.2")}
    )
    result = runner.invoke(app, ["fix", "--repo", str(root)])
    assert "the new code of python/removed-stdlib-modules does not run on" in result.output
    assert "the new code of python/datetime-utcnow" not in result.output
    assert "+from datetime import timezone" in result.output


def test_the_modules_a_pack_may_import_are_in_the_header_of_fix_and_in_pack_validate(
    tmp_path: Path,
) -> None:
    root = committed(tmp_path / "repo", {"app.py": CLOCK})
    result = runner.invoke(app, ["fix", "--repo", str(root)])
    assert "python/datetime-utcnow may import datetime, datetime.timezone.\n" in result.output
    flagged = committed(tmp_path / "other", {"app.py": "import telnetlib\n"})
    assert "may import" not in runner.invoke(app, ["fix", "--repo", str(flagged)]).output
    checked = runner.invoke(app, ["pack", "validate", "python/datetime-utcnow"])
    assert "  imports      datetime, datetime.timezone\n" in checked.output
    other = runner.invoke(app, ["pack", "validate", "python/removed-stdlib-modules"])
    assert "imports" not in other.output


def test_the_counts_of_a_run_that_no_pack_applies_to_are_the_files_that_were_parsed(
    tmp_path: Path,
) -> None:
    source = "import datetime\n\n# utcnow is gone from this code\nnow = datetime.datetime.now()\n"
    root = committed(tmp_path / "repo", {"app.py": source, "other.py": "x = 1\n"})
    result = runner.invoke(app, ["scan", "--repo", str(root), "--json"])
    report = json.loads(result.stdout)
    assert report["packs"] == []
    assert (report["counts"]["files_selected"], report["counts"]["files_parsed"]) == (2, 1)
    run = json.loads(next(root.glob(".obelize/runs/*/run.json")).read_text(encoding="utf-8"))
    assert run["counts"]["files_parsed"] == 1


# Every way a file can spell the symbol; none may be skipped for lacking the module's name.
SPELLINGS = {
    "attribute chain": "import datetime\nx = datetime.datetime.utcnow()\n",
    "module alias": "import datetime as dt\nx = dt.datetime.utcnow()\n",
    "from import": "from datetime import datetime\nx = datetime.utcnow()\n",
    "from import with as": "from datetime import datetime as D\nx = D.utcnow()\n",
    "star import": "from datetime import *\nx = datetime.utcnow()\n",
    "other symbol": "import datetime\nx = datetime.datetime.utcfromtimestamp(0)\n",
}


def scanned(root: Path) -> dict[str, Any]:
    result = runner.invoke(app, ["scan", "--repo", str(root), "--json"])
    return json.loads(result.stdout)  # type: ignore[no-any-return]


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_a_file_that_spells_a_legacy_symbol_any_way_is_found_though_the_token_is_not_the_module(
    tmp_path: Path, spelling: str
) -> None:
    report = scanned(committed(tmp_path / "repo", {"app.py": SPELLINGS[spelling]}))
    assert report["counts"]["files_parsed"] == 1
    assert [one["id"] for one in report["packs"]] == ["python/datetime-utcnow"]
    assert report["findings"], spelling


def test_a_name_given_to_getattr_is_parsed_as_it_holds_the_last_segment(tmp_path: Path) -> None:
    """The scan reports no finding for it, as with `datetime` for the token."""
    source = "import datetime\nx = getattr(datetime.datetime, 'utcnow')()\n"
    report = scanned(committed(tmp_path / "repo", {"app.py": source}))
    assert report["counts"]["files_parsed"] == 1


def test_a_file_that_only_names_the_module_is_not_parsed(tmp_path: Path) -> None:
    root = committed(
        tmp_path / "repo", {"app.py": "import datetime\n\nx = datetime.date.today()\n"}
    )
    assert scanned(root)["counts"]["files_parsed"] == 0


def test_a_declared_python_it_runs_on_does_not(tmp_path: Path) -> None:
    root = committed(tmp_path / "repo", {"app.py": CLOCK, "pyproject.toml": PYTHON.format(">=3.9")})
    result = runner.invoke(app, ["fix", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "datetime.now(timezone.utc)" in result.output


def test_pkg_resources_is_reported_with_its_replacement_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    source = (
        'import pkg_resources\n\n__version__ = pkg_resources.get_distribution("demo").version\n'
    )
    root = committed(tmp_path / "repo", {"app.py": source, "requirements.txt": "setuptools<82\n"})
    assert packs(root) == ["setuptools/pkg-resources-to-importlib"]
    result = runner.invoke(app, ["fix", "--repo", str(root), "--apply"])
    assert result.exit_code == 4, result.output
    assert (root / "app.py").read_text(encoding="utf-8") == source
    assert (root / "requirements.txt").read_text(encoding="utf-8") == "setuptools<82\n"


def test_a_pack_that_moves_no_pin_lists_the_old_distribution_as_context(tmp_path: Path) -> None:
    source = "import pkg_resources\n\nx = pkg_resources.parse_version('1')\n"
    root = committed(tmp_path / "repo", {"app.py": source, "requirements.txt": "setuptools<82\n"})
    result = runner.invoke(app, ["scan", "--repo", str(root), "--json"])
    rows = [row for row in json.loads(result.stdout)["findings"] if row["kind"] == "manifest"]
    assert [(row["symbol"], row["scan_status"]) for row in rows] == [("setuptools", "not_a_usage")]


def test_a_removed_module_is_reported_and_a_repository_on_an_older_python_is_not_blocked(
    tmp_path: Path,
) -> None:
    files = {"app.py": "import telnetlib\n\nconnection = telnetlib.Telnet('host')\n"}
    root = committed(tmp_path / "repo", {**files, "pyproject.toml": PYTHON.format(">=3.8")})
    assert packs(root) == ["python/removed-stdlib-modules"]
    result = runner.invoke(app, ["fix", "--repo", str(root)])
    assert "telnetlib3 or Exscript" in result.output


def test_two_packs_of_the_python_run_over_one_file_in_one_pass(tmp_path: Path) -> None:
    source = (
        "import pipes\nfrom datetime import datetime\n\nx = pipes.quote(str(datetime.utcnow()))\n"
    )
    root = committed(tmp_path / "repo", {"app.py": source})
    assert sorted(packs(root)) == ["python/datetime-utcnow", "python/removed-stdlib-modules"]
    result = runner.invoke(app, ["fix", "--repo", str(root), "--apply"])
    assert result.exit_code == 6, result.output
    assert (root / "app.py").read_text(encoding="utf-8") == (
        "import shlex\nfrom datetime import datetime\nfrom datetime import timezone\n\n"
        "x = shlex.quote(str(datetime.now(timezone.utc).replace(tzinfo=None)))\n"
    )
