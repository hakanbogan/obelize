"""Every bundled pack: its fixtures, its sources, and the negative corpus that must fail.

One contract, run over each pack `loader.bundled_ids()` finds. What a pack claims about its SDKs is
checked in the module of that pack (`test_gemini_facts.py`, `test_pypdf_facts.py`).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import libcst as cst
import pytest
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import Config, bounds
from obelize.packs import loader, schema
from obelize.scan import manifests
from obelize.scan import runner as scanner
from obelize.transforms import codemod, registry
from obelize.transforms import manifest as manifest_rules

ROOT = Path(__file__).resolve().parents[2]
NEGATIVE = Path(__file__).resolve().parent / "_negative"
BUILDER = NEGATIVE / "_build.py"
GEMINI_ID = "gemini/google-generativeai-to-google-genai"
OPENAI_ID = "openai/openai-0-to-1"
PYPDF_ID = "py-pdf/pypdf2-to-pypdf"
BUNDLED_IDS = loader.bundled_ids()

runner = CliRunner()


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("obelize_negative_pack_corpus", BUILDER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # No bytecode: a .pyc left in the fixture directory would travel with every copy of it.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


builder = _load_builder()

# Read from the registry: a hand-kept copy would be a second statement that can drift.
IMPLEMENTED_KINDS: frozenset[str] = registry.IMPLEMENTED


@pytest.fixture(scope="module", params=BUNDLED_IDS)
def bundled(request: pytest.FixtureRequest) -> loader.LoadedPack:
    return loader.load(request.param)


def pack_dir(bundled: loader.LoadedPack) -> Path:
    return bundled.path.parent


def test_the_bundled_packs_are_the_ones_this_release_ships() -> None:
    assert BUNDLED_IDS == (GEMINI_ID, OPENAI_ID, PYPDF_ID)


def test_a_bundled_pack_validates_under_its_own_id(bundled: loader.LoadedPack) -> None:
    assert bundled.pack.id == bundled.reference
    assert bundled.sha256 == hashlib.sha256(bundled.path.read_bytes()).hexdigest()


def test_every_bundled_pack_is_named_where_a_reader_or_a_workflow_looks(
    bundled: loader.LoadedPack,
) -> None:
    """The id is written into files that a run never reads."""
    for relative in ("README.md", "docs/CLI.md", ".github/workflows/ci.yml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert bundled.pack.id in text, f"{relative} does not name {bundled.pack.id}"


def test_every_change_names_a_positive_and_a_negative_fixture(bundled: loader.LoadedPack) -> None:
    """CONTRIBUTING.md's rule, which a schema cannot express."""
    for change in bundled.pack.changes:
        positive = [name for name in change.fixtures if name.startswith("fixtures/positive/")]
        negative = [name for name in change.fixtures if name.startswith("fixtures/negative/")]
        assert positive, f"{change.id} has no positive fixture"
        assert negative, f"{change.id} has no negative fixture"


def test_the_declared_fixtures_are_exactly_the_files_on_disk(bundled: loader.LoadedPack) -> None:
    """Both directions; answer keys (`.after.`) are undeclared but must sit beside an input."""
    declared = {name for change in bundled.pack.changes for name in change.fixtures}
    files = [path for path in (pack_dir(bundled) / "fixtures").rglob("*") if path.is_file()]
    keys = {path for path in files if ".after." in path.name}
    on_disk = {
        str(path.relative_to(pack_dir(bundled)).as_posix()) for path in files if path not in keys
    }
    assert declared == on_disk, sorted(declared ^ on_disk)
    orphans = [
        key.name
        for key in keys
        if not key.with_name(key.name.replace(".after.", ".before.")).exists()
    ]
    assert orphans == [], orphans


def migrate(bundled: loader.LoadedPack, work: Path) -> codemod.Run:
    """The product's driver, so this file never grades a pack against a second opinion."""
    spec = loader.to_scan_spec(bundled)
    scan = scanner.scan(work, Config(), spec, jobs=1)
    sources = {result.path: (work / result.path).read_bytes() for result in scan.results}
    return codemod.run(scan, sources, bundled.pack, spec)


@pytest.fixture(scope="module")
def migratable(
    bundled: loader.LoadedPack, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, tuple[bool, bytes]]:
    """Positive fixtures a run migrates whole, one repository each: those left on the legacy SDK
    would hold back every other fixture's `configure` (ADR-031 D11)."""
    work = tmp_path_factory.mktemp("positive")
    decided: dict[str, tuple[bool, bytes]] = {}
    for path in sorted((pack_dir(bundled) / "fixtures" / "positive").glob("*.before.py")):
        case = work / path.stem
        case.mkdir()
        (case / path.name).write_bytes(path.read_bytes())
        decided.update({row.path: (row.written, row.after) for row in migrate(bundled, case).files})
    return decided


def test_an_answer_key_exists_for_exactly_the_fixtures_a_run_can_migrate(
    bundled: loader.LoadedPack, migratable: dict[str, tuple[bool, bytes]]
) -> None:
    """Computed from a run, not a list, so a kind that completes a fixture demands its key."""
    assert IMPLEMENTED_KINDS <= schema.CHANGE_KINDS
    for change in bundled.pack.changes:
        for name in change.fixtures:
            if not name.startswith("fixtures/positive/"):
                continue
            assert ".before." in name, f"{name} is a positive fixture with no .before. in its name"
            key = pack_dir(bundled) / name.replace(".before.", ".after.")
            if name.endswith(".py"):
                expected = migratable[Path(name).name][0]
            else:
                # A manifest's verdict is repo-wide (ADR-010 F-2); its key comes with its rule.
                expected = "manifest_dependency" in IMPLEMENTED_KINDS
            assert key.exists() is expected, (
                f"{key.name} {'is missing' if expected else 'exists'} while a run "
                f"{'can' if expected else 'cannot'} migrate {Path(name).name} whole. "
                f"An answer key no code can produce is a claim no test can check."
            )


def test_every_answer_key_is_what_the_rules_write_into_its_fixture(
    bundled: loader.LoadedPack, migratable: dict[str, tuple[bool, bytes]]
) -> None:
    """PACK_SPEC's before->after contract over existing keys; the test above owns which exist."""
    keys = sorted((pack_dir(bundled) / "fixtures" / "positive").glob("*.after.py"))
    assert keys, "no answer key exists, so this assertion proves nothing"
    for key in keys:
        source = key.name.replace(".after.", ".before.")
        _whole, produced = migratable[source]
        assert produced.decode("utf-8") == key.read_text(encoding="utf-8"), key.name


def test_the_manifest_answer_key_is_what_the_rule_writes(bundled: loader.LoadedPack) -> None:
    """A manifest's verdict is repo-wide, so ADR-010 F-2's clear case (something migrated, nothing
    blocks) is set up here, not surveyed from the Python fixtures."""
    name = "fixtures/positive/requirements.before.txt"
    data = (pack_dir(bundled) / name).read_bytes()
    spec = loader.to_scan_spec(bundled)
    plan = manifests.plan(
        manifests.declarations(name, data),
        manifests.Migration(migrated=("app.py",)),
        spec,
    )
    context = manifest_rules.ManifestContext.build(name, data, plan)
    edits = [row for rule in registry.manifest_rules(bundled.pack) for row in rule.apply(context)]
    assert [row.status for row in edits] == ["auto"]
    key = pack_dir(bundled) / "fixtures" / "positive" / "requirements.after.txt"
    assert manifest_rules.finish(context) == key.read_bytes()


def test_applying_the_pack_twice_produces_what_applying_it_once_did(
    bundled: loader.LoadedPack, tmp_path: Path, migratable: dict[str, tuple[bool, bytes]]
) -> None:
    """Written to disk and re-run, not compared in memory: idempotence is a repository claim."""
    for name, (_written, data) in sorted(migratable.items()):
        (tmp_path / name).write_bytes(data)
    again = migrate(bundled, tmp_path)
    assert [row for row in again.edits if row.status == "auto"] == []
    assert again.written == ()


def test_two_runs_over_the_same_input_write_the_same_bytes(
    bundled: loader.LoadedPack, tmp_path: Path
) -> None:
    """libcst hands references over as an identity-hashed `set`, so order varies per process."""
    work = tmp_path / "once"
    work.mkdir()
    for path in sorted((pack_dir(bundled) / "fixtures" / "positive").glob("*.before.py")):
        (work / path.name).write_bytes(path.read_bytes())
    first, second = migrate(bundled, work), migrate(bundled, work)
    assert [(row.path, row.after) for row in first.outcomes] == [
        (row.path, row.after) for row in second.outcomes
    ]
    assert first.edits == second.edits


FIXTURES = [
    path
    for reference in BUNDLED_IDS
    for path in sorted((loader.load(reference).path.parent / "fixtures").rglob("*.py"))
]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: f"{path.parts[-5]}-{path.name}")
def test_every_python_fixture_parses_and_compiles(path: Path) -> None:
    data = path.read_bytes()
    assert cst.parse_module(data).bytes == data
    compile(data, path.name, "exec")


def test_a_positive_fixture_survives_the_prefilter_and_a_negative_one_does_not(
    bundled: loader.LoadedPack,
) -> None:
    """Negatives carry no prefilter token, so are never parsed; positives must, or prove nothing.

    A shared module's token is the new SDK's name too, so its negatives are read instead, and must
    come out with nothing to migrate: `test_a_negative_fixture_of_a_shared_module_has_no_usage`.
    """
    tokens = bundled.pack.match.prefilter_tokens
    for path in sorted((pack_dir(bundled) / "fixtures" / "positive").glob("*.before.py")):
        data = path.read_bytes()
        assert any(token.encode("ascii") in data for token in tokens), (
            f"{path.name} contains no prefilter token, so the scan would skip it unparsed"
        )
    if bundled.pack.match.shared:
        pytest.skip("a shared module's negatives name the module, and are scanned instead")
    for path in sorted((pack_dir(bundled) / "fixtures" / "negative").glob("*.py")):
        data = path.read_bytes()
        found = [token for token in tokens if token.encode("ascii") in data]
        assert not found, f"{path.name} carries {found}, so it is not eliminated by the prefilter"


def test_a_negative_fixture_of_a_shared_module_has_no_usage(
    bundled: loader.LoadedPack, tmp_path: Path
) -> None:
    """What a prefilter proves for another pack, a scan proves here: nothing is left to migrate."""
    if not bundled.pack.match.shared:
        pytest.skip("this pack's negatives are eliminated before the parse")
    for path in sorted((pack_dir(bundled) / "fixtures" / "negative").glob("*.py")):
        work = tmp_path / path.stem
        work.mkdir()
        (work / path.name).write_bytes(path.read_bytes())
        found = scanner.scan(work, Config(), loader.to_scan_spec(bundled), jobs=1).findings
        assert [row for row in found if row.scan_status != "not_a_usage"] == [], path.name


def test_the_manifest_fixtures_declare_the_two_sides_of_the_migration(
    bundled: loader.LoadedPack,
) -> None:
    """Manifests are not `.py`, so the prefilter never sees them."""
    pack, fixtures = bundled.pack, pack_dir(bundled) / "fixtures"
    before = (fixtures / "positive" / "requirements.before.txt").read_text("utf-8")
    after = (fixtures / "negative" / "requirements_already_new.txt").read_text("utf-8")
    if canonicalize_name(pack.from_.package) == canonicalize_name(pack.to.package):
        # One name on both sides: the versions are what tell them apart.
        for name, text, side in (
            ("requirements.before.txt", before, pack.from_),
            ("requirements_already_new.txt", after, pack.to),
        ):
            declared = manifests.declarations(name, text.encode())[0]
            assert declared.name == canonicalize_name(pack.to.package), name
            assert declared.spec is not None, name
            floor = bounds(SpecifierSet(declared.spec))[0]
            assert floor is not None
            assert floor in SpecifierSet(side.version), name
        return
    assert pack.from_.package in before
    assert pack.to.package not in before
    assert pack.to.package in after
    assert pack.from_.package not in after.replace(pack.to.package, "")


def test_sources_has_a_section_for_every_change_and_no_orphans(bundled: loader.LoadedPack) -> None:
    """ADR-006: no citable source, no rule. A heading may list several comma-separated ids.

    The headings above the first `---` are prose; every one below it is a list of change ids.
    """
    changes = {change.id for change in bundled.pack.changes}
    text = (pack_dir(bundled) / loader.SOURCES_FILENAME).read_text(encoding="utf-8")
    _prose, _, sections = text.partition("\n---\n")
    headings = re.findall(r"^## (.+)$", sections, re.MULTILINE)
    cited = {part.strip() for heading in headings for part in heading.split(",")}
    assert cited == changes, sorted(cited ^ changes)


def test_sources_records_the_hash_of_the_page_the_pack_cites(bundled: loader.LoadedPack) -> None:
    text = (pack_dir(bundled) / loader.SOURCES_FILENAME).read_text(encoding="utf-8")
    assert bundled.pack.source.sha256 is not None
    assert bundled.pack.source.sha256 in text
    assert bundled.pack.source.url in text


def test_the_bundled_packs_use_every_kind_and_the_registry_says_which_one_runs() -> None:
    """The scanner reads every declared kind; only the registry says which ones can apply."""
    declared = {
        change.kind for reference in BUNDLED_IDS for change in loader.load(reference).pack.changes
    }
    assert declared == IMPLEMENTED_KINDS == schema.CHANGE_KINDS
    # `registry.RULES` holds only parsed-file kinds; the manifest kind is in `MANIFEST_RULES`.
    assert frozenset(registry.RULES) < schema.CHANGE_KINDS


def test_the_committed_negative_corpus_is_what_the_generator_produces() -> None:
    assert builder.verify(builder.build()) is True


def test_every_negative_case_has_a_file_and_every_file_has_a_case() -> None:
    expected = {f"{case.name}.yaml" for case in builder.CASES}
    on_disk = {path.name for path in NEGATIVE.glob("*.yaml")}
    assert expected == on_disk, sorted(expected ^ on_disk)


@pytest.mark.parametrize("case", builder.CASES, ids=[case.name for case in builder.CASES])
def test_every_negative_pack_is_rejected_at_the_field_it_names(case: Any) -> None:
    """PACK_SPEC hard rule 4; the expectation is the generator's table, which writes each header."""
    path = NEGATIVE / f"{case.name}.yaml"
    with pytest.raises(loader.PackInvalidError) as excinfo:
        loader.load(str(path))
    prefix = f"{case.path}: " if case.path else ""
    assert any(
        problem.startswith(prefix) and case.says in problem for problem in excinfo.value.problems
    ), f"expected {prefix + case.says!r}, got {excinfo.value.problems}"
    header = path.read_text(encoding="utf-8")
    assert case.says in header
    assert excinfo.value.bundled is False


def test_a_negative_pack_that_is_repaired_is_accepted() -> None:
    """The control: an invalid minimal document would make every case above pass."""
    assert schema.PackDocument.model_validate(builder.MINIMAL).id == "demo/legacy-to-modern"


def test_pack_validate_accepts_a_bundled_pack_by_id_and_by_path(bundled: loader.LoadedPack) -> None:
    for reference in (bundled.pack.id, str(bundled.path)):
        result = runner.invoke(app, ["pack", "validate", reference])
        assert result.exit_code == 0, result.output
        assert "is a valid migration pack." in result.output
        assert bundled.sha256 in result.output


@pytest.mark.parametrize("case", builder.CASES, ids=[case.name for case in builder.CASES])
def test_pack_validate_exits_seven_on_every_negative_pack(case: Any) -> None:
    result = runner.invoke(app, ["pack", "validate", str(NEGATIVE / f"{case.name}.yaml")])
    assert result.exit_code == 7, result.output


def test_pack_validate_exits_two_when_there_is_nothing_to_read(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pack", "validate", str(tmp_path / "absent.yaml")])
    assert result.exit_code == 2, result.output


def test_pack_validate_exits_one_on_a_bundled_pack_that_does_not_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bundled pack is obelize's own input, so this is obelize's own defect."""
    target = tmp_path / "demo" / "legacy-to-modern" / loader.PACK_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text("language: klingon\n", encoding="utf-8")
    monkeypatch.setattr(loader, "BUNDLED", tmp_path)
    result = runner.invoke(app, ["pack", "validate", "demo/legacy-to-modern"])
    assert result.exit_code == 1, result.output
    assert "a bug in obelize" in result.output


def test_pack_validate_says_out_loud_what_it_did_not_check() -> None:
    result = runner.invoke(app, ["pack", "validate", GEMINI_ID])
    assert "  fixtures     not checked by this command" in result.output


def test_the_generator_check_mode_fails_on_a_damaged_corpus(tmp_path: Path) -> None:
    original = builder.HERE
    try:
        builder.HERE = tmp_path
        assert builder.verify(builder.build()) is False
    finally:
        builder.HERE = original


def test_the_generator_refuses_an_unknown_argument() -> None:
    completed = subprocess.run(
        [sys.executable, str(BUILDER), "--rewrite"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 2
    assert "unknown argument" in completed.stderr
