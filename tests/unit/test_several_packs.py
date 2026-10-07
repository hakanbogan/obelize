"""One run with several packs: which are chosen, in what order they write, and what is recorded.

The bundled Gemini and PyPDF2 packs share files in these repositories, so the second pack reads
what the first wrote.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from obelize.cli import app
from obelize.commands import fix as fixer
from obelize.models import Config, ModelConfig
from obelize.packs import loader
from obelize.verify.runner import Mode
from platforms import PYTHON

runner = CliRunner()

GEMINI = "gemini/google-generativeai-to-google-genai"
OPENAI = "openai/openai-0-to-1"
PYPDF = "py-pdf/pypdf2-to-pypdf"

# Both libraries in one file, so what the second pack sees depends on what the first wrote.
BOTH = """import google.generativeai as genai
import PyPDF2

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def page_note(path):
    reader = PyPDF2.PdfReader(path)
    return MODEL.generate_content(reader.pages[0].extract_text()).text
"""

PDFS = """import PyPDF2


def count(path):
    return len(PyPDF2.PdfReader(path).pages)
"""

CHAT = """import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def ask(text):
    return MODEL.generate_content(text).text
"""

PINS = "google-generativeai==0.8.6\nPyPDF2==3.0.1\nrequests>=2.31\n"


def repository(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "work"], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@t.invalid")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "before"],
        check=True,
    )
    return root


@pytest.fixture
def both(tmp_path: Path) -> Path:
    return repository(
        tmp_path / "repo",
        {"app.py": BOTH, "pdfs.py": PDFS, "chat.py": CHAT, "requirements.txt": PINS},
    )


def run(tree: Path, *arguments: str) -> Result:
    return runner.invoke(app, [*arguments, "--repo", str(tree)])


def latest(tree: Path) -> Path:
    name = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return tree / ".obelize" / "runs" / name


def document(tree: Path, name: str) -> Any:
    return json.loads((latest(tree) / name).read_text(encoding="utf-8"))


def sources(tree: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(tree.iterdir())
        if path.is_file()
    }


def test_the_packs_a_repository_uses_are_the_ones_chosen(both: Path) -> None:
    result = run(both, "scan", "--json")
    assert result.exit_code == 0, result.output
    packs = json.loads(result.stdout)["packs"]
    assert [pack["id"] for pack in packs] == [GEMINI, PYPDF]


def test_a_pack_whose_library_the_repository_does_not_use_is_not_chosen(tmp_path: Path) -> None:
    tree = repository(tmp_path / "repo", {"chat.py": CHAT, "requirements.txt": PINS})
    result = run(tree, "scan", "--json")
    assert [pack["id"] for pack in json.loads(result.stdout)["packs"]] == [GEMINI]


def test_a_pack_the_user_names_runs_whether_or_not_the_repository_uses_it(tmp_path: Path) -> None:
    tree = repository(tmp_path / "repo", {"chat.py": CHAT, "requirements.txt": PINS})
    result = run(tree, "scan", "--json", "--pack", PYPDF)
    document_ = json.loads(result.stdout)
    assert [pack["id"] for pack in document_["packs"]] == [PYPDF]
    assert document_["counts"]["findings"] == 1


def test_a_repository_no_pack_applies_to_says_so_and_exits_zero(tmp_path: Path) -> None:
    tree = repository(tmp_path / "repo", {"plain.py": "print('hello')\n"})
    result = run(tree, "scan")
    assert result.exit_code == 0, result.output
    assert f"No pack applies. Checked: {GEMINI}, {OPENAI}, {PYPDF}." in result.output
    assert document(tree, "findings.json")["packs"] == []
    assert document(tree, "run.json")["packs"] == []
    fixed = run(tree, "fix")
    assert fixed.exit_code == 0, fixed.output
    assert "No pack applies" in fixed.output


def test_one_run_over_two_packs_writes_what_two_runs_one_after_the_other_write(
    tmp_path: Path,
) -> None:
    files = {"app.py": BOTH, "pdfs.py": PDFS, "chat.py": CHAT, "requirements.txt": PINS}
    together = repository(tmp_path / "together", files)
    one_by_one = repository(tmp_path / "one_by_one", files)

    assert run(together, "fix", "--apply", "--allow-dirty").exit_code in {0, 4, 6}
    for pack in (GEMINI, PYPDF):
        applied = run(one_by_one, "fix", "--apply", "--allow-dirty", "--pack", pack)
        assert applied.exit_code in {0, 4, 6}, applied.output

    assert sources(together) == sources(one_by_one)
    migrated = sources(together)
    assert "import pypdf" in migrated["app.py"]
    assert "from google import genai" in migrated["app.py"]
    assert migrated["requirements.txt"] == "google-genai>=1\npypdf>=6.19\nrequests>=2.31\n"


def test_a_second_run_changes_nothing(both: Path) -> None:
    assert run(both, "fix", "--apply", "--allow-dirty").exit_code in {0, 4, 6}
    before = sources(both)
    again = run(both, "fix", "--apply", "--allow-dirty")
    assert again.exit_code == 0, again.output
    assert "No pack applies" in again.output
    assert sources(both) == before


def test_every_document_names_each_pack_and_the_folder_keeps_a_copy_of_each(both: Path) -> None:
    assert run(both, "fix", "--apply", "--allow-dirty").exit_code in {0, 4, 6}
    for name in ("findings.json", "plan.json", "run.json"):
        assert [pack["id"] for pack in document(both, name)["packs"]] == [GEMINI, PYPDF], name
    for pack_id in (GEMINI, PYPDF):
        copy = latest(both) / "packs" / pack_id
        loaded = loader.load(pack_id)
        assert (copy / "pack.yaml").read_bytes() == loaded.data
        assert (copy / "pack.sha256").read_text(encoding="utf-8") == f"{loaded.sha256}\n"
    assert not (latest(both) / "pack.yaml").exists()


def test_an_edit_names_the_pack_that_made_it(both: Path) -> None:
    run(both, "fix", "--apply", "--allow-dirty")
    rules = {edit["rule_id"] for edit in document(both, "plan.json")["edits"] if edit["rule_id"]}
    assert {rule.partition(":")[0] for rule in rules} == {GEMINI, PYPDF}
    assert f"{PYPDF}:rename-import" in rules
    assert f"{GEMINI}:rename-import" in rules


def test_a_pack_blocked_beside_one_that_writes_still_leaves_the_run_unfinished(
    tmp_path: Path,
) -> None:
    """PyPDF2 pinned below 3 blocks only its own pack; the other writes, and the run says so."""
    tree = repository(
        tmp_path / "repo",
        {
            "chat.py": CHAT,
            "pdfs.py": PDFS,
            "requirements.txt": "google-generativeai==0.8.6\nPyPDF2==2.12.1\n",
        },
    )
    result = run(tree, "fix", "--apply", "--allow-dirty", "--verify", f"{PYTHON} -c pass")
    assert result.exit_code == 4, result.output
    record = document(tree, "run.json")
    assert {pack["id"]: pack["blocked"] for pack in record["packs"]} == {
        GEMINI: None,
        PYPDF: "legacy_version_unsupported",
    }
    assert "from google import genai" in sources(tree)["chat.py"]
    assert sources(tree)["pdfs.py"] == PDFS
    assert {row["bail"] for row in record["withheld"]} == {"legacy_version_unsupported"}
    assert record["counts"]["auto"] > 0


def test_two_packs_that_cannot_run_together_are_refused(tmp_path: Path) -> None:
    tree = repository(tmp_path / "repo", {"chat.py": CHAT})
    copy = tmp_path / "copy.yaml"
    document_ = yaml.safe_load(loader.load(GEMINI).data)
    document_["id"] = "gemini/a-copy-of-it"
    copy.write_text(yaml.safe_dump(document_, sort_keys=False), encoding="utf-8")
    result = run(tree, "scan", "--pack", GEMINI, "--pack", str(copy))
    assert result.exit_code == 2, result.output
    assert "both migrate google.generativeai" in result.output


def test_naming_a_pack_twice_is_a_usage_error(both: Path) -> None:
    result = run(both, "scan", "--pack", GEMINI, "--pack", GEMINI)
    assert result.exit_code == 2
    assert f"names {GEMINI} more than once" in result.output


def test_a_model_flag_needs_one_pack(
    both: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model is asked about one pack's rows, so asking for it with several is refused."""
    config = tmp_path / "config" / "obelize"
    config.mkdir(parents=True)
    (config / "config.yml").write_text(
        "model:\n  provider: openai_compat\n  base_url: http://127.0.0.1:9\n  model: m\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    refused = run(both, "fix", "--apply", "--accept-model", "--allow-dirty")
    assert refused.exit_code == 2, refused.output
    assert "need --pack to name one" in refused.output
    context = run(both, "fix", "--show-context")
    assert context.exit_code == 2
    assert "--show-context needs exactly one pack" in context.output


def test_a_model_only_the_users_file_configures_is_not_asked_when_several_packs_run(
    both: Path,
) -> None:
    from obelize.config import load as load_config

    loaded = load_config(both)
    outcome = fixer.run(
        fixer.Request(
            root=both,
            packs=tuple(loader.load(pack) for pack in (GEMINI, PYPDF)),
            named=False,
            config=Config(),
            source=loaded.source,
            cli_commands=(),
            mode=Mode(),
            config_dir=both.parent / "config",
            environ={},
            argv=("fix",),
            model=ModelConfig(provider="openai_compat", base_url="http://127.0.0.1:9", model="m"),
        )
    )
    assert outcome.notes == (
        "The configured model was not asked: this run uses more than one pack.",
    )
    assert outcome.record.model is None


def test_a_pack_in_a_user_directory_is_chosen_like_a_bundled_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packs = tmp_path / "packs"
    minimal = {
        "id": "demo/legacy-to-modern",
        "pack_version": "0.1.0",
        "provider": "demo",
        "language": "python",
        "source": {
            "type": "official_guide",
            "url": "https://example.invalid/guide",
            "retrieved_at": "2026-09-17",
        },
        "from": {"package": "demo-legacy", "version": "<1"},
        "to": {"package": "demo-modern", "version": ">=1", "requires_python": ">=3.9"},
        "match": {"imports": ["demo_legacy"], "prefilter_tokens": ["demo_legacy"]},
        "changes": [
            {
                "id": "configure-to-client",
                "kind": "configure_to_client",
                "citation": "Guide, Authentication",
                "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
                "params": {
                    "legacy_symbol": "demo_legacy.configure",
                    "client_symbol": "demo_modern.Client",
                    "client_name": "client",
                    "client_name_fallback": "demo_client",
                    "allowed_kwargs": ["api_key", "credentials"],
                    "credential_kwarg": "api_key",
                    "credentials_object_kwarg": "credentials",
                },
            }
        ],
        "limitations": ["Everything this pack does not list."],
    }
    where = packs / "demo" / "legacy-to-modern"
    where.mkdir(parents=True)
    (where / "pack.yaml").write_text(yaml.safe_dump(minimal, sort_keys=False), encoding="utf-8")
    config = tmp_path / "config" / "obelize"
    config.mkdir(parents=True)
    (config / "config.yml").write_text(f"pack_dirs:\n  - {packs}\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    tree = repository(
        tmp_path / "repo", {"app.py": "import demo_legacy\n\ndemo_legacy.configure(api_key='k')\n"}
    )
    result = run(tree, "scan", "--json")
    assert result.exit_code == 0, result.output
    packs_used = json.loads(result.stdout)["packs"]
    assert [pack["id"] for pack in packs_used] == ["demo/legacy-to-modern"]
    assert document(tree, "run.json")["packs"][0]["source"] == "file"


def test_a_repository_cannot_add_pack_directories(both: Path) -> None:
    (both / ".obelize.yml").write_text("pack_dirs:\n  - /tmp\n", encoding="utf-8")
    result = run(both, "scan")
    assert result.exit_code == 2
    assert "pack directories are not read from a repository" in result.output


@pytest.mark.parametrize("entry", ["relative/path", "/no/such/directory"])
def test_a_pack_directory_that_is_not_an_absolute_existing_one_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    config = tmp_path / "config" / "obelize"
    config.mkdir(parents=True)
    (config / "config.yml").write_text(f"pack_dirs:\n  - {entry}\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    tree = repository(tmp_path / "repo", {"plain.py": "x = 1\n"})
    result = run(tree, "scan")
    assert result.exit_code == 2
    assert "absolute path" in result.output
