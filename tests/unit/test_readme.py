"""README.md's example and numbers, against the command and the benchmark that produce them."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from obelize.cli import app
from obelize.packs import loader
from platforms import posix_only

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
RESULTS = ROOT / "docs" / "BENCHMARK_RESULTS.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def names_every_package(text: str, names: Iterable[str]) -> bool:
    """Whether the first 10 lines, what PyPI shows first, name each package."""
    head = "\n".join(text.splitlines()[:10])
    return all(re.search(rf"\b{name}\b", head) for name in names)


def bundled_packages() -> set[str]:
    packs = (loader.load(reference).pack for reference in loader.bundled_ids())
    return {name for pack in packs for name in (pack.from_.package, pack.to.package)}


def test_the_first_ten_lines_name_every_package_a_bundled_pack_migrates() -> None:
    assert names_every_package(_readme(), bundled_packages())


def test_a_package_named_on_the_eleventh_line_is_too_late() -> None:
    def lead(blank: int) -> str:
        return "one-package\n" + "\n" * blank + "another-package\n"

    names = ("one-package", "another-package")
    assert names_every_package(lead(8), names)
    assert not names_every_package(lead(9), names)


def shown_commands(markdown: str) -> list[list[str]]:
    """The arguments of every `uvx obelize` line in the shell blocks."""
    blocks = re.findall(r"^```bash\n(.*?)^```", markdown, re.MULTILINE | re.DOTALL)
    return [
        shlex.split(line)[2:]
        for block in blocks
        for line in block.splitlines()
        if line.startswith("uvx obelize ")
    ]


def parse(args: list[str]) -> None:
    """Parse `args` as the installed command would, without running it."""
    command = typer.main.get_command(app)
    name = "obelize"
    while children := getattr(command, "commands", None):
        name, *args = args
        command = children[name]
    command.make_context(name, args)


def test_every_command_the_quickstart_shows_parses() -> None:
    shown = shown_commands(_readme())
    assert shown
    for args in shown:
        parse(args)


def test_a_mistyped_command_or_flag_does_not_parse() -> None:
    parse(["fix", "--apply", "--verify", "pytest"])
    with pytest.raises(KeyError):
        parse(["fx"])
    with pytest.raises(Exception, match="No such option: --verfy"):
        parse(["fix", "--apply", "--verfy", "pytest"])


def _install_line() -> str:
    """The Quickstart's line that puts the new SDK into the project's environment."""
    quickstart = _readme().split("\n## Quickstart\n")[1].split("\n## ")[0]
    blocks: list[str] = re.findall(r"^```bash\n(.*?)^```", quickstart, re.MULTILINE | re.DOTALL)
    (line,) = [
        line
        for block in blocks
        for line in block.splitlines()
        if "google-genai" in line and not line.startswith("uvx obelize ")
    ]
    return line


def _wheel(directory: Path) -> Path:
    """An installable stand-in for `google-genai`: one module, no dependencies, no index."""
    files = {
        "probe.py": b"",
        "probe-1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: probe\nVersion: 1.0\n",
        "probe-1.0.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    record = "".join(
        f"{name},sha256="
        f"{base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},"
        f"{len(data)}\n"
        for name, data in files.items()
    )
    wheel = directory / "probe-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("probe-1.0.dist-info/RECORD", record + "probe-1.0.dist-info/RECORD,,\n")
    return wheel


# A project's `.venv` as each tool makes it; uv's has no pip.
MAKERS = {
    "pip": [sys.executable, "-m", "venv", ".venv"],
    "uv": ["uv", "venv", "--quiet", "--python", sys.executable, ".venv"],
}


@posix_only("the Quickstart names .venv/bin/python, which only a POSIX environment has")
@pytest.mark.parametrize("maker", sorted(MAKERS))
def test_the_quickstart_installs_the_new_sdk_into_a_venv_made_by_pip_or_by_uv(
    tmp_path: Path, maker: str
) -> None:
    """Control: uv's environment has no pip to run. Another environment is active, as the
    suite's own is, so the line has to name the project's."""
    offline = {
        **os.environ,
        "UV_OFFLINE": "1",
        "PIP_NO_INDEX": "1",
        "VIRTUAL_ENV": str(tmp_path / "active"),
    }
    subprocess.run(MAKERS[maker], cwd=tmp_path, env=offline, check=True)
    has_pip = subprocess.run(
        [".venv/bin/python", "-c", "import pip"], cwd=tmp_path, capture_output=True, check=False
    )
    assert (has_pip.returncode == 0) is (maker == "pip")
    wheel = str(_wheel(tmp_path))
    line = _install_line().replace("google-genai", wheel).replace("pypdf", wheel)
    installed = subprocess.run(
        shlex.split(line), cwd=tmp_path, env=offline, capture_output=True, text=True, check=False
    )
    assert installed.returncode == 0, installed.stderr
    subprocess.run([".venv/bin/python", "-c", "import probe"], cwd=tmp_path, check=True)


def _lines(text: str) -> list[str]:
    """pre-commit strips the one space of a blank context line; nothing else may differ."""
    return [line.rstrip() for line in text.splitlines()]


def test_the_example_diff_is_what_a_dry_run_prints_for_examples_quickstart(
    tmp_path: Path,
) -> None:
    work = tmp_path / "quickstart"
    shutil.copytree(ROOT / "examples" / "quickstart", work)
    result = CliRunner().invoke(app, ["fix", "--repo", str(work)], catch_exceptions=False)
    assert result.exit_code == 0
    run = (work / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    patch = (work / ".obelize" / "runs" / run / "patch.diff").read_text(encoding="utf-8")
    (shown,) = re.findall(r"^```diff\n(.*?)^```", _readme(), re.MULTILINE | re.DOTALL)
    assert _lines(shown) == _lines(patch)
    assert "\n".join(_lines(shown)) in "\n".join(_lines(result.stdout))


def _block(name: str) -> str:
    """One generated block of the results page; each is checked against its data elsewhere."""
    text = RESULTS.read_text(encoding="utf-8")
    return text.split(f"<!-- {name}:begin")[1].split(f"<!-- {name}:end -->")[0]


def _cells(block: str, first: str) -> list[str]:
    """The first table row whose first cell reads `first`, without emphasis or backticks."""
    for line in block.splitlines():
        cells = [cell.strip().strip("*`") for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == first:
            return cells
    raise AssertionError(f"no table row starts with {first!r}")


def published() -> list[str]:
    """The rows README's benchmark tables must hold, filled in from the results page."""
    gate1 = _block("gate1")
    _, _, labelled, found, *_, precision, recall = _cells(gate1, "Total")
    labelled_repositories = len(re.findall(r"^\| \[`", gate1, re.MULTILINE))
    errors = _block("errors")
    _, migrated, share = _cells(errors, "migrated")
    _, rows, _ = _cells(errors, "Total")
    rounds = _block("round")
    _, cases, verified, _ = _cells(rounds, "Cases")
    wrong = _cells(rounds, "wrong")[-1]
    capped = re.search(r"(\d+) no test command", _cells(rounds, "Total")[-1])
    assert capped
    comparison = _block("comparison")
    _, compared, _, compared_rows, ours, *_ = _cells(comparison, "Obelize")
    theirs = _cells(comparison, "General agent")[4]
    _, our_wrong, their_wrong = _cells(comparison, "wrong")
    return [
        f"| Scan precision | {precision} | {found} usages reported in {labelled_repositories} "
        f"repositories labelled by hand |",
        f"| Scan recall | {recall} | {labelled} usages labelled by hand |",
        f"| Usages migrated | {migrated} ({share}) | {rows} usages in {cases} public "
        f"repositories |",
        f"| Repositories with a wrong edit | {wrong} | {cases} |",
        f"| Repositories migrated and verified by their own tests | {verified} | {cases}, of "
        f"which {capped.group(1)} have no test command |",
        f"| Usages migrated | {ours} | {theirs} | {compared_rows} usages in {compared} of "
        f"those repositories |",
        f"| Repositories with a wrong edit | {our_wrong} | {their_wrong} | {compared} |",
    ]


def test_every_number_in_the_readme_benchmark_is_the_published_one() -> None:
    """Every row, so a number added to README without its source here fails too."""
    section = _readme().split("\n## Benchmark\n")[1]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("| ") and not line.startswith("|---")
    ]
    headers = {"| Measure | obelize | n |", "| Against a coding agent | obelize | The agent | n |"}
    assert [row for row in rows if row not in headers] == published()
