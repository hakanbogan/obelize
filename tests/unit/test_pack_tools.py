"""`obelize pack new` and `obelize pack test`: a pack made, and a pack held to its fixtures."""

from __future__ import annotations

import datetime as dt
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner, Result

from obelize.cli import app
from obelize.packs import check, loader, scaffold
from support import commit_all, committed, write_tree

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

BUNDLED = loader.bundled_ids()
PYPDF = "py-pdf/pypdf2-to-pypdf"
NEW = ["acme/legacylib-to-modernlib", "--from", "legacylib>=1,<2", "--to", "modernlib>=2"]
GUIDE = ["--guide", "https://example.com/migrate"]


def _new(directory: Path, *extra: str) -> Result:
    return runner.invoke(app, ["pack", "new", *NEW, *GUIDE, "--dir", str(directory), *extra])


def _copy(tmp_path: Path) -> Path:
    """The PyPDF2 pack as a folder of its own, to damage."""
    source = loader.load(PYPDF).path.parent
    target = tmp_path / "py-pdf" / "pypdf2-to-pypdf"
    shutil.copytree(source, target)
    return target


def _problems(folder: Path) -> dict[str, tuple[str, ...]]:
    loaded = loader.load(str(folder / "pack.yaml"))
    return {one.name: one.problems for one in check.run(loaded) if not one.ok}


# The checks.


@pytest.mark.parametrize("reference", BUNDLED)
def test_every_bundled_pack_passes_every_check(reference: str) -> None:
    results = check.run(loader.load(reference))
    assert len(results) == 9
    assert [(one.name, one.problems) for one in results if not one.ok] == []


def test_a_fixture_that_is_not_there_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "from_import.before.py").unlink()
    found = _problems(folder)
    (name,) = [one for one in found if one.startswith("every fixture")]
    assert "fixtures/positive/from_import.before.py is named and not on disk" in found[name]


def test_a_file_no_change_names_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "negative" / "stray.py").write_text("import os\n", encoding="utf-8")
    (name,) = [one for one in _problems(folder) if one.startswith("every fixture")]
    assert "fixtures/negative/stray.py is on disk and no change names it" in _problems(folder)[name]


def test_an_answer_key_with_no_input_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "ghost.after.py").write_text("x = 1\n", encoding="utf-8")
    (name,) = [one for one in _problems(folder) if one.startswith("every fixture")]
    assert any("ghost.after.py is an answer key" in line for line in _problems(folder)[name])


def test_an_answer_key_that_differs_from_what_the_rules_write_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    key = folder / "fixtures" / "positive" / "import_module.after.py"
    key.write_text(key.read_text(encoding="utf-8") + "\nextra = 1\n", encoding="utf-8")
    found = _problems(folder)
    (name,) = [one for one in found if one.startswith("every answer key")]
    assert found[name] == (
        "import_module.after.py is not what the rules write into import_module.before.py",
    )


def test_an_answer_key_for_a_fixture_no_run_migrates_whole_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "removed_names.after.py").write_text(
        "x = 1\n", encoding="utf-8"
    )
    found = _problems(folder)
    assert any(
        line.startswith("removed_names.after.py exists while a run cannot migrate")
        for lines in found.values()
        for line in lines
    )


def test_a_migrated_fixture_with_no_key_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "import_module.after.py").unlink()
    found = _problems(folder)
    assert any(
        "import_module.after.py is missing while a run can migrate" in line
        for lines in found.values()
        for line in lines
    )


def test_a_dependency_key_that_differs_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "requirements.after.txt").write_text(
        "pypdf>=1\n", encoding="utf-8"
    )
    found = _problems(folder)
    assert any(
        "requirements.after.txt is not what the rule writes" in line
        for lines in found.values()
        for line in lines
    )


def test_a_dependency_key_that_is_missing_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "requirements.after.txt").unlink()
    found = _problems(folder)
    assert any(
        "requirements.after.txt is missing" in line for lines in found.values() for line in lines
    )


def test_a_negative_fixture_that_carries_the_token_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    negative = folder / "fixtures" / "negative" / "other_pdf_library.py"
    negative.write_text(
        negative.read_text(encoding="utf-8") + "\nimport PyPDF2\n", encoding="utf-8"
    )
    found = _problems(folder)
    (name,) = [one for one in found if one.startswith("positive fixtures reach")]
    assert "other_pdf_library.py holds ['PyPDF2']" in found[name][0]


def test_a_positive_fixture_without_a_token_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "positive" / "import_module.before.py").write_text(
        "x = 1\n", encoding="utf-8"
    )
    found = _problems(folder)
    (name,) = [one for one in found if one.startswith("positive fixtures reach")]
    assert "import_module.before.py holds no prefilter token" in found[name][0]


def test_a_fixture_that_does_not_compile_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "negative" / "broken.py").write_text("def (:\n", encoding="utf-8")
    found = _problems(folder)
    (name,) = [one for one in found if one.startswith("every Python fixture")]
    assert "broken.py does not parse" in found[name][0]


def test_a_fixture_that_does_not_read_back_byte_for_byte_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "fixtures" / "negative" / "bare_cr.py").write_bytes(b"x = 1\rprint(x)\r")
    found = _problems(folder)
    assert any("bare_cr.py" in line for lines in found.values() for line in lines)


def test_a_change_without_both_kinds_of_fixture_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    pack = folder / "pack.yaml"
    both = (
        "      - fixtures/negative/already_pypdf.py\n"
        "      - fixtures/negative/other_pdf_library.py\n"
    )
    assert both in pack.read_text(encoding="utf-8")
    pack.write_text(pack.read_text(encoding="utf-8").replace(both, "", 1), encoding="utf-8")
    found = _problems(folder)
    (name,) = [one for one in found if one.startswith("every change has")]
    assert found[name] == ("rename-import names no negative fixture",)


def test_sources_that_miss_a_change_or_the_page_are_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    sources = folder / "SOURCES.md"
    text = sources.read_text(encoding="utf-8")
    text = text.replace("## rename-import", "## renamed-import")
    text = text.replace(loader.load(str(folder / "pack.yaml")).pack.source.url, "<the page>")
    sources.write_text(text, encoding="utf-8")
    (name,) = [one for one in _problems(folder) if one.startswith("SOURCES.md")]
    lines = _problems(folder)[name]
    assert "SOURCES.md has no section for rename-import" in lines
    assert "SOURCES.md has a section for renamed-import, which is no change" in lines
    assert any("does not name the source url" in line for line in lines)


def test_sources_that_do_not_record_the_hash_are_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    sources = folder / "SOURCES.md"
    digest = loader.load(str(folder / "pack.yaml")).pack.source.sha256
    assert digest is not None
    sources.write_text(
        sources.read_text(encoding="utf-8").replace(digest, "0" * 64), encoding="utf-8"
    )
    (name,) = [one for one in _problems(folder) if one.startswith("SOURCES.md")]
    assert "does not record the sha256" in _problems(folder)[name][0]


def test_a_pack_with_no_sources_file_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "SOURCES.md").unlink()
    (name,) = [one for one in _problems(folder) if one.startswith("SOURCES.md")]
    assert "SOURCES.md is missing" in _problems(folder)[name][0]


def test_a_shared_modules_negative_that_uses_the_library_is_named(tmp_path: Path) -> None:
    source = loader.load("openai/openai-0-to-1").path.parent
    folder = tmp_path / "openai" / "openai-0-to-1"
    shutil.copytree(source, folder)
    (folder / "fixtures" / "negative" / "uses_legacy.py").write_text(
        "import openai\n\nopenai.ChatCompletion.create(model='m', messages=[])\n", encoding="utf-8"
    )
    found = _problems(folder)
    assert any(
        "uses_legacy.py line 3 is a usage of the legacy API" in line
        for lines in found.values()
        for line in lines
    )


def test_a_positive_fixture_named_without_before_is_named(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    pack = folder / "pack.yaml"
    positive = folder / "fixtures" / "positive"
    (positive / "from_import.before.py").rename(positive / "from_import.py")
    pack.write_text(
        pack.read_text(encoding="utf-8").replace(
            "fixtures/positive/from_import.before.py", "fixtures/positive/from_import.py"
        ),
        encoding="utf-8",
    )
    found = _problems(folder)
    assert any(
        "from_import.py is a positive fixture with no .before." in line
        for lines in found.values()
        for line in lines
    )


def test_a_pack_with_no_answer_keys_and_no_dependency_fixture_is_still_checked(
    tmp_path: Path,
) -> None:
    folder = _copy(tmp_path)
    for key in (folder / "fixtures" / "positive").glob("*.after.*"):
        key.unlink()
    (folder / "fixtures" / "positive" / "requirements.before.txt").unlink()
    found = _problems(folder)
    assert any(
        "is missing while a run can migrate" in line for lines in found.values() for line in lines
    )
    assert not any("requirements.after" in line for lines in found.values() for line in lines)


def test_a_second_run_that_writes_again_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Row:
        path, status = "a.py", "auto"

    class Run:
        files = ()
        edits = written = (Row(),)

    folder = _copy(tmp_path)
    loaded = loader.load(str(folder / "pack.yaml"))
    monkeypatch.setattr(check, "migrate", lambda *_args: Run())
    assert check._idempotent(loaded, folder) == [
        "a.py is migrated again by a second run",
        "a second run writes a.py",
    ]


def test_two_runs_that_disagree_are_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Row:
        def __init__(self, after: bytes) -> None:
            self.path, self.after, self.status = "a.py", after, "auto"

    class Run:
        def __init__(self, after: bytes) -> None:
            self.outcomes = (Row(after),)
            self.edits = ()

    runs = iter([Run(b"one"), Run(b"two")])
    folder = _copy(tmp_path)
    loaded = loader.load(str(folder / "pack.yaml"))
    monkeypatch.setattr(check, "migrate", lambda *_args: next(runs))
    assert check._deterministic(loaded, folder) == [
        "two runs over the same files wrote different bytes"
    ]


# `obelize pack test`.


def test_pack_test_passes_a_bundled_pack_by_id() -> None:
    result = runner.invoke(app, ["pack", "test", PYPDF])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(f"{PYPDF} 0.")
    assert "All 9 checks passed." in result.stdout
    assert "FAIL" not in result.stdout


def test_pack_test_takes_the_folder_that_holds_a_pack(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    assert runner.invoke(app, ["pack", "test", str(folder)]).exit_code == 0
    assert runner.invoke(app, ["pack", "test", str(folder / "pack.yaml")]).exit_code == 0


def test_pack_test_names_what_failed_and_exits_seven(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "SOURCES.md").unlink()
    result = runner.invoke(app, ["pack", "test", str(folder)])
    assert result.exit_code == 7, result.output
    assert "  FAIL  SOURCES.md has a section for every change" in result.stdout
    assert "          - SOURCES.md is missing" in result.stdout
    assert "1 of 9 checks failed." in result.stderr


def test_pack_test_exits_two_when_there_is_no_pack(tmp_path: Path) -> None:
    assert runner.invoke(app, ["pack", "test", str(tmp_path / "nothing")]).exit_code == 2


def test_pack_test_exits_seven_for_a_pack_that_is_not_valid(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    write_tree(folder, {"pack.yaml": "language: klingon\n"})
    assert runner.invoke(app, ["pack", "test", str(folder)]).exit_code == 7


def test_a_bundled_pack_that_fails_a_check_is_a_defect_in_obelize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check, "run", lambda _loaded: (check.Check("x", ("broken",)),))
    result = runner.invoke(app, ["pack", "test", PYPDF])
    assert result.exit_code == 1
    assert "a bug in obelize" in result.output


def test_a_bundled_pack_that_does_not_validate_is_a_defect_in_obelize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo" / "legacy-to-modern" / loader.PACK_FILENAME
    write_tree(target.parent, {loader.PACK_FILENAME: "language: klingon\n"})
    monkeypatch.setattr(loader, "BUNDLED", tmp_path)
    result = runner.invoke(app, ["pack", "test", "demo/legacy-to-modern"])
    assert result.exit_code == 1
    assert "a bug in obelize" in result.output


# `obelize pack new`.


def test_a_pack_made_by_pack_new_passes_pack_test(tmp_path: Path) -> None:
    made = _new(tmp_path)
    assert made.exit_code == 0, made.output
    folder = tmp_path / "acme" / "legacylib-to-modernlib"
    assert f"Made acme/legacylib-to-modernlib in {folder}:" in made.stdout
    assert (
        f"Next: edit pack.yaml and SOURCES.md, then run obelize pack test {folder}" in made.stdout
    )
    tested = runner.invoke(app, ["pack", "test", str(folder)])
    assert tested.exit_code == 0, tested.output


def test_the_files_pack_new_lists_are_the_files_it_made(tmp_path: Path) -> None:
    made = _new(tmp_path)
    folder = tmp_path / "acme" / "legacylib-to-modernlib"
    listed = sorted(line.strip() for line in made.stdout.splitlines() if line.startswith("  "))
    on_disk = sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )
    assert listed == on_disk
    assert "fixtures/positive/import_module.after.py" in listed
    assert "fixtures/positive/requirements.after.txt" in listed


def test_a_dotted_module_is_renamed_to_its_new_home(tmp_path: Path) -> None:
    made = runner.invoke(
        app,
        [
            "pack",
            "new",
            "acme/gen-to-genai",
            "--from",
            "google-generativeai>=0.8,<1",
            "--to",
            "google-genai>=1",
            *GUIDE,
            "--module",
            "google.generativeai",
            "--to-module",
            "google.genai",
            "--dir",
            str(tmp_path),
        ],
    )
    assert made.exit_code == 0, made.output
    folder = tmp_path / "acme" / "gen-to-genai"
    after = (folder / "fixtures" / "positive" / "import_module.after.py").read_text(
        encoding="utf-8"
    )
    assert "from google import genai" in after
    assert runner.invoke(app, ["pack", "test", str(folder)]).exit_code == 0


def test_the_pack_pack_new_makes_migrates_a_repository(tmp_path: Path) -> None:
    _new(tmp_path / "packs")
    repo = committed(
        tmp_path / "repo",
        {
            "app.py": "import legacylib\n\nVALUE = legacylib.example()\n",
            "requirements.txt": "legacylib==1.4\n",
        },
    )
    pack = str(tmp_path / "packs" / "acme" / "legacylib-to-modernlib" / "pack.yaml")
    result = runner.invoke(
        app, ["fix", "--repo", str(repo), "--pack", pack, "--apply", "--allow-dirty"]
    )
    assert result.exit_code in (0, 6), result.output
    assert (repo / "app.py").read_text(
        encoding="utf-8"
    ) == "import modernlib\n\nVALUE = modernlib.example()\n"
    assert "modernlib>=2" in (repo / "requirements.txt").read_text(encoding="utf-8")
    commit_all(repo)


def test_pack_new_never_writes_into_a_folder_that_exists(tmp_path: Path) -> None:
    assert _new(tmp_path).exit_code == 0
    again = _new(tmp_path)
    assert again.exit_code == 2
    assert "exists already" in again.output


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["Bad_Id", "--from", "a>=1", "--to", "b>=1"], "is not a pack id"),
        (["acme/x", "--from", "a", "--to", "b>=1"], "names no versions"),
        (["acme/x", "--from", "a>=1", "--to", "b"], "names no versions"),
        (["acme/x", "--from", "not a requirement", "--to", "b>=1"], "is not a requirement"),
        (["acme/x", "--from", "a<2", "--to", "b>=1"], "needs a range with a lower bound"),
        (["acme/x", "--from", "a>1,<2", "--to", "b>=1"], "needs a range with a lower bound"),
        (
            ["acme/x", "--from", "a>=1", "--to", "b>=1", "--requires-python", "three"],
            "not a PEP 440",
        ),
    ],
    ids=["id", "from-bare", "to-bare", "from-garbled", "no-floor", "exclusive-floor", "python"],
)
def test_a_request_that_does_not_make_a_pack_is_refused_and_leaves_nothing(
    tmp_path: Path, argv: list[str], message: str
) -> None:
    result = runner.invoke(app, ["pack", "new", *argv, *GUIDE, "--dir", str(tmp_path)])
    assert result.exit_code == 2
    assert message in result.output
    assert list(tmp_path.iterdir()) == []


def test_a_guide_that_is_not_https_is_refused_and_the_folder_is_removed(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["pack", "new", *NEW, "--guide", "http://example.com/migrate", "--dir", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "must be https" in result.output
    assert not (tmp_path / "acme" / "legacylib-to-modernlib").exists()


def test_the_default_modules_are_the_distribution_names() -> None:
    made = scaffold.plan(
        "acme/x", "my-lib>=1", "other.lib>=2", "https://example.com/g", today=dt.date(2026, 10, 18)
    )
    assert (made.module, made.to_module) == ("my_lib", "other_lib")
    assert made.retrieved == dt.date(2026, 10, 18)
    assert (made.provider, made.slug) == ("acme", "x")


def test_the_date_a_pack_was_read_defaults_to_today() -> None:
    made = scaffold.plan("acme/x", "a>=1", "b>=1", "https://example.com/g")
    assert made.retrieved == dt.datetime.now(dt.UTC).date()
