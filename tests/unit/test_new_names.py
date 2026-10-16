"""`to.introduces`: code on the new API beside a pin that admits only the old releases is reported.

One distribution holds both APIs, so the scan cannot tell a stale pin from a live one by whether
anything imports the module. A name only the new API defines (`openai.OpenAI`) can: code that uses
one fails on `openai==0.28.1`, and a run that said nothing read as healthy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pdf_repo import git_repo
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import Config, ScanSpec
from obelize.packs import loader
from obelize.scan import manifests, runner

OPENAI = loader.to_scan_spec(loader.load("openai/openai-0-to-1"))
LEGACY = "import openai\n\nresponse = openai.ChatCompletion.create(model='m', messages=[])\n"


def modern(source: str, spec: ScanSpec = OPENAI) -> bool:
    return manifests.uses_new_names(source.encode(), spec)


@pytest.mark.parametrize(
    "source",
    [
        "from openai import OpenAI\n",
        "from openai import OpenAI as Client\n",
        "from openai import AsyncOpenAI, ChatCompletion\n",
        "import openai\nclient = openai.OpenAI()\n",
        "import openai as oa\nclient = oa.AzureOpenAI(api_key='k')\n",
        "import openai.types\nclient = openai.AsyncOpenAI()\n",
        "import openai\nvalue = openai.OpenAI.__name__\n",
        "def build():\n    import openai\n    return openai.OpenAI()\n",
        "from openai import OpenAI\nimport openai\nopenai.ChatCompletion.create()\n",
    ],
)
def test_a_name_only_the_new_api_defines_is_found_as_written_and_through_an_alias(
    source: str,
) -> None:
    assert modern(source) is True


@pytest.mark.parametrize(
    "source",
    [
        "import openai\nopenai.ChatCompletion.create()\n",
        "import openai\nopenai.api_key = 'k'\nclient = openai.OpenAIError\n",
        "from openai import ChatCompletion, OpenAIError\n",
        "OpenAI = object\nclient = OpenAI()\n",
        "class OpenAI:\n    pass\n",
        "import other\nclient = other.OpenAI()\n",
        "from other import OpenAI\n",
        "from . import OpenAI\n",
        "from openai import *\nclient = OpenAI()\n",
        "# openai.OpenAI is the new client\nNAME = 'openai.OpenAI'\n",
        "import openai\nclient = something.openai.OpenAI()\n",
        "import openai\nclient = openai().OpenAI\n",
        "def broken(:\n",
        "",
    ],
    ids=[
        "the-old-api",
        "a-name-that-only-starts-the-same",
        "from-import-of-old-names",
        "a-local-variable",
        "a-local-class",
        "another-library",
        "another-library-from-import",
        "a-relative-import",
        "a-star-import",
        "a-mention",
        "a-longer-chain",
        "a-call-in-the-chain",
        "a-file-that-does-not-parse",
        "an-empty-file",
    ],
)
def test_a_name_that_is_not_the_new_clients_is_not_found(source: str) -> None:
    assert modern(source) is False


def test_a_pack_that_names_none_finds_none() -> None:
    plain = OPENAI.model_copy(update={"new_names": ()})
    assert modern("from openai import OpenAI\n", plain) is False


def test_a_file_that_cannot_be_parsed_deep_enough_is_not_a_guess() -> None:
    assert modern("from openai import OpenAI\n" + "x = " + "(" * 400 + ")" * 400) is False


# A repository of the bundled openai pack, scanned.


def scanned(root: Path, config: Config | None = None) -> runner.Scan:
    return runner.scan(root, config or Config(), OPENAI, jobs=1)


def rows(scan: runner.Scan) -> list[tuple[str, str | None]]:
    return [(row.scan_status, row.bail) for row in scan.manifests.findings]


def repository(root: Path, files: Mapping[str, str]) -> Path:
    return git_repo(root, files)


CLIENT = "from openai import OpenAI\n\nclient = OpenAI()\n"
STALE = [("needs_review", "manifest_code_mismatch")]


@pytest.mark.parametrize(
    "pin",
    ["openai==0.28.1", "openai<1", "openai>=0.27,<1", "openai~=0.28.0", "openai==0.27.*"],
)
def test_a_pin_that_admits_only_the_old_releases_beside_the_new_client_is_a_mismatch(
    tmp_path: Path, pin: str
) -> None:
    scan = scanned(repository(tmp_path, {"app.py": CLIENT, "requirements.txt": f"{pin}\n"}))
    assert rows(scan) == STALE
    assert scan.modern is True
    assert runner.applies(scan) is True
    assert scan.blocked == ()


@pytest.mark.parametrize(
    "pin",
    [
        "openai",
        "openai>=0.27",
        "openai>=1.109.1",
        "openai==1.109.1",
        "openai<2",
        "openai==1.30.1",
        "openai==0.28.1.*.*",
        "openai===0.28.1.corp",
        "openai==0.18.0",
        "openai<0.27",
    ],
)
def test_a_pin_of_the_new_api_or_below_the_old_range_or_that_nobody_can_read_is_no_mismatch(
    tmp_path: Path, pin: str
) -> None:
    scan = scanned(repository(tmp_path, {"app.py": CLIENT, "requirements.txt": f"{pin}\n"}))
    assert [row for row in rows(scan) if row == STALE[0]] == []


def test_a_pin_the_old_code_still_uses_is_not_a_mismatch_for_the_new_client_beside_it(
    tmp_path: Path,
) -> None:
    """The pin moves with the code, as it did: one withheld legacy row holds it, a clean one moves
    it, and in neither case is the pin said to disagree with the code."""
    files = {"old.py": LEGACY, "new.py": CLIENT, "requirements.txt": "openai==0.28.1\n"}
    scan = scanned(repository(tmp_path, files))
    assert rows(scan) == [("eligible", None)]


def test_a_pin_no_code_has_moved_past_is_still_context_only(tmp_path: Path) -> None:
    scan = scanned(
        repository(tmp_path, {"app.py": "import openai\n", "requirements.txt": "openai==0.28.1\n"})
    )
    assert (rows(scan), scan.modern) == ([("not_a_usage", None)], False)
    assert runner.applies(scan) is False


def test_new_client_code_beside_no_declaration_is_not_a_row(tmp_path: Path) -> None:
    scan = scanned(repository(tmp_path, {"app.py": CLIENT}))
    assert (rows(scan), scan.modern) == ([], False)


def test_the_files_are_read_only_where_a_declaration_could_be_at_odds_with_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = manifests.uses_new_names

    def spy(data: bytes, spec: ScanSpec) -> bool:
        seen.append("read")
        return real(data, spec)

    monkeypatch.setattr(manifests, "uses_new_names", spy)
    scanned(repository(tmp_path / "none", {"app.py": CLIENT}))
    assert seen == []
    scanned(repository(tmp_path / "declared", {"app.py": CLIENT, "requirements.txt": "openai\n"}))
    assert seen == ["read"]


def test_a_pack_that_introduces_nothing_is_scanned_as_before(tmp_path: Path) -> None:
    plain = OPENAI.model_copy(update={"new_names": ()})
    root = repository(tmp_path, {"app.py": CLIENT, "requirements.txt": "openai==0.28.1\n"})
    scan = runner.scan(root, Config(), plain, jobs=1)
    assert (rows(scan), scan.modern) == ([("not_a_usage", None)], False)


def test_a_pack_with_two_distributions_reports_the_pin_whatever_the_names(tmp_path: Path) -> None:
    """`manifest_code_mismatch` for a pin nothing imports is the other packs' row, unchanged."""
    spec = loader.to_scan_spec(loader.load("py-pdf/pypdf2-to-pypdf"))
    root = repository(
        tmp_path, {"app.py": "import pypdf\n", "requirements.txt": "PyPDF2==1.26.0\n"}
    )
    scan = runner.scan(root, Config(), spec, jobs=1)
    assert rows(scan) == STALE
    assert scan.modern is False


def test_several_scans_say_the_new_api_is_used_if_any_pack_found_it(tmp_path: Path) -> None:
    root = repository(tmp_path, {"app.py": CLIENT, "requirements.txt": "openai==0.28.1\n"})
    found = scanned(root)
    pdf = loader.to_scan_spec(loader.load("py-pdf/pypdf2-to-pypdf"))
    quiet = runner.scan(root, Config(), pdf, jobs=1)
    tree = runner.read(root, Config(), (OPENAI, pdf))
    assert runner.merged([found, quiet], tree).modern is True
    assert runner.merged([quiet, quiet], tree).modern is False


def test_a_survey_carries_whether_the_new_api_is_used() -> None:
    assert manifests.survey([]).modern is False
    assert manifests.survey([], modern=True).modern is True


# From the scan to the run.

runner_ = CliRunner()


def command(tree: Path, *arguments: str) -> Any:
    return runner_.invoke(app, [*arguments, "--repo", str(tree)])


def test_the_mismatch_is_reported_by_scan_and_fix_and_nothing_is_written(tmp_path: Path) -> None:
    tree = repository(tmp_path, {"app.py": CLIENT, "requirements.txt": "openai==0.28.1\n"})
    scan = command(tree, "scan", "--json")
    assert scan.exit_code == 0, scan.output
    document = json.loads(scan.stdout)
    assert [pack["id"] for pack in document["packs"]] == ["openai/openai-0-to-1"]
    assert [(row["path"], row["scan_status"], row["bail"]) for row in document["findings"]] == [
        ("requirements.txt", "needs_review", "manifest_code_mismatch")
    ]
    fixed = command(tree, "fix", "--apply", "--allow-dirty")
    assert fixed.exit_code == 4, fixed.output
    assert "requirements.txt:1  openai  manifest_code_mismatch" in fixed.output
    assert "No pack applies" not in fixed.output
    assert (tree / "requirements.txt").read_text(encoding="utf-8") == "openai==0.28.1\n"
