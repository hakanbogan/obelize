"""A repository meets the packs of the Python itself through the commands it already runs.

`scan` and `fix` choose a pack by the modules a repository imports and gate it by the Python the
repository declares, as for a library; the difference is that no dependency line moves.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

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
    assert "which allows versions its new code does not run on" in result.output
    assert (root / "app.py").read_text(encoding="utf-8") == CLOCK


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
