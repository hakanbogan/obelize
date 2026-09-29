"""The bundled pack, its fixtures, its sources, and the negative corpus that must fail.

SDK names are checked against `google.genai`'s own members (hence the dev dependency), never by
construction, which fabricates unknown enum members.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import subprocess
import sys
import typing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import libcst as cst
import pytest
from google.genai import types
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import Config, ReceiverMethods
from obelize.packs import loader, schema
from obelize.scan import manifests
from obelize.scan import runner as scanner
from obelize.transforms import codemod, registry
from obelize.transforms import manifest as manifest_rules

ROOT = Path(__file__).resolve().parents[2]
NEGATIVE = Path(__file__).resolve().parent / "_negative"
BUILDER = NEGATIVE / "_build.py"
BUNDLED_ID = "gemini/google-generativeai-to-google-genai"

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

BUNDLED = loader.load(BUNDLED_ID)
PACK = BUNDLED.pack
PACK_DIR = BUNDLED.path.parent
SOURCES = PACK_DIR / loader.SOURCES_FILENAME
CHANGES = {change.id: change for change in PACK.changes}


def _params(kind: str) -> list[Any]:
    return [change.params for change in PACK.changes if change.kind == kind]


MODEL_PARAMS = _params("generative_model_calls")
RENAME_PARAMS = _params("rename_import")
CALL_PARAMS = _params("rewrite_call")


def test_exactly_one_pack_is_bundled_and_it_validates() -> None:
    assert loader.bundled_ids() == (BUNDLED_ID,)
    assert PACK.id == BUNDLED_ID
    assert BUNDLED.sha256 == hashlib.sha256(BUNDLED.path.read_bytes()).hexdigest()


def test_the_pack_is_the_migration_adr_001_chose() -> None:
    assert PACK.from_.package == "google-generativeai"
    assert PACK.to.package == "google-genai"
    assert PACK.match.imports == ("google.generativeai",)
    assert PACK.match.prefilter_tokens == ("generativeai",)


def test_the_bundled_pack_is_the_one_the_readme_and_the_workflows_name() -> None:
    """The id is written into three files that a run never reads."""
    for relative in ("README.md", "docs/CLI.md", ".github/workflows/e2e.yml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert BUNDLED_ID in text, f"{relative} does not name the bundled pack id"


def test_every_change_names_a_positive_and_a_negative_fixture() -> None:
    """CONTRIBUTING.md's rule, which a schema cannot express."""
    for change in PACK.changes:
        positive = [name for name in change.fixtures if name.startswith("fixtures/positive/")]
        negative = [name for name in change.fixtures if name.startswith("fixtures/negative/")]
        assert positive, f"{change.id} has no positive fixture"
        assert negative, f"{change.id} has no negative fixture"


def test_the_declared_fixtures_are_exactly_the_files_on_disk() -> None:
    """Both directions; answer keys (`.after.`) are undeclared but must sit beside an input."""
    declared = {name for change in PACK.changes for name in change.fixtures}
    files = [path for path in (PACK_DIR / "fixtures").rglob("*") if path.is_file()]
    keys = {path for path in files if ".after." in path.name}
    on_disk = {str(path.relative_to(PACK_DIR).as_posix()) for path in files if path not in keys}
    assert declared == on_disk, sorted(declared ^ on_disk)
    orphans = [
        key.name
        for key in keys
        if not key.with_name(key.name.replace(".after.", ".before.")).exists()
    ]
    assert orphans == [], orphans


def migrate(work: Path) -> codemod.Run:
    """The product's driver, so this file never grades the pack against a second opinion."""
    spec = loader.to_scan_spec(BUNDLED)
    scan = scanner.scan(work, Config(), spec, jobs=1)
    sources = {result.path: (work / result.path).read_bytes() for result in scan.results}
    return codemod.run(scan, sources, PACK, spec)


@pytest.fixture(scope="module")
def migratable(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[bool, bytes]]:
    """Positive fixtures a run migrates whole, one repository each: those left on the legacy SDK
    would hold back every other fixture's `configure` (ADR-031 D11)."""
    work = tmp_path_factory.mktemp("positive")
    decided: dict[str, tuple[bool, bytes]] = {}
    for path in sorted((PACK_DIR / "fixtures" / "positive").glob("*.before.py")):
        case = work / path.stem
        case.mkdir()
        (case / path.name).write_bytes(path.read_bytes())
        decided.update({row.path: (row.written, row.after) for row in migrate(case).files})
    return decided


def test_an_answer_key_exists_for_exactly_the_fixtures_a_run_can_migrate(
    migratable: dict[str, tuple[bool, bytes]],
) -> None:
    """Computed from a run, not a list, so a kind that completes a fixture demands its key."""
    assert IMPLEMENTED_KINDS <= schema.CHANGE_KINDS
    for change in PACK.changes:
        for name in change.fixtures:
            if not name.startswith("fixtures/positive/"):
                continue
            assert ".before." in name, f"{name} is a positive fixture with no .before. in its name"
            key = PACK_DIR / name.replace(".before.", ".after.")
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
    migratable: dict[str, tuple[bool, bytes]],
) -> None:
    """PACK_SPEC's before->after contract over existing keys; the test above owns which exist."""
    keys = sorted((PACK_DIR / "fixtures" / "positive").glob("*.after.py"))
    assert keys, "no answer key exists, so this assertion proves nothing"
    for key in keys:
        source = key.name.replace(".after.", ".before.")
        _whole, produced = migratable[source]
        assert produced.decode("utf-8") == key.read_text(encoding="utf-8"), key.name


def test_the_manifest_answer_key_is_what_the_rule_writes() -> None:
    """A manifest's verdict is repo-wide, so ADR-010 F-2's clear case (something migrated, nothing
    blocks) is set up here, not surveyed from the Python fixtures."""
    name = "fixtures/positive/requirements.before.txt"
    data = (PACK_DIR / name).read_bytes()
    spec = loader.to_scan_spec(BUNDLED)
    plan = manifests.plan(
        manifests.declarations(name, data),
        manifests.Migration(migrated=("app.py",)),
        spec,
    )
    context = manifest_rules.ManifestContext.build(name, data, plan)
    edits = [row for rule in registry.manifest_rules(PACK) for row in rule.apply(context)]
    assert [row.status for row in edits] == ["auto"]
    key = PACK_DIR / "fixtures" / "positive" / "requirements.after.txt"
    assert manifest_rules.finish(context) == key.read_bytes()


def test_applying_the_pack_twice_produces_what_applying_it_once_did(
    tmp_path: Path, migratable: dict[str, tuple[bool, bytes]]
) -> None:
    """Written to disk and re-run, not compared in memory: idempotence is a repository claim."""
    for name, (_written, data) in sorted(migratable.items()):
        (tmp_path / name).write_bytes(data)
    again = migrate(tmp_path)
    assert [row for row in again.edits if row.status == "auto"] == []
    assert again.written == ()


def test_two_runs_over_the_same_input_write_the_same_bytes(tmp_path: Path) -> None:
    """libcst hands references over as an identity-hashed `set`, so order varies per process."""
    work = tmp_path / "once"
    work.mkdir()
    for path in sorted((PACK_DIR / "fixtures" / "positive").glob("*.before.py")):
        (work / path.name).write_bytes(path.read_bytes())
    first, second = migrate(work), migrate(work)
    assert [(row.path, row.after) for row in first.outcomes] == [
        (row.path, row.after) for row in second.outcomes
    ]
    assert first.edits == second.edits


@pytest.mark.parametrize(
    "path",
    sorted((PACK_DIR / "fixtures").rglob("*.py")),
    ids=lambda path: str(path.name),
)
def test_every_python_fixture_parses_and_compiles(path: Path) -> None:
    data = path.read_bytes()
    assert cst.parse_module(data).bytes == data
    compile(data, path.name, "exec")


def test_a_positive_fixture_survives_the_prefilter_and_a_negative_one_does_not() -> None:
    """Negatives carry no prefilter token, so are never parsed; positives must, or prove nothing."""
    tokens = PACK.match.prefilter_tokens
    for path in sorted((PACK_DIR / "fixtures" / "positive").glob("*.before.py")):
        data = path.read_bytes()
        assert any(token.encode("ascii") in data for token in tokens), (
            f"{path.name} contains no prefilter token, so the scan would skip it unparsed"
        )
    for path in sorted((PACK_DIR / "fixtures" / "negative").glob("*.py")):
        data = path.read_bytes()
        found = [token for token in tokens if token.encode("ascii") in data]
        assert not found, f"{path.name} carries {found}, so it is not eliminated by the prefilter"


def test_the_manifest_fixtures_declare_the_two_sides_of_the_migration() -> None:
    """Manifests are not `.py`, so the prefilter never sees them."""
    before = (PACK_DIR / "fixtures" / "positive" / "requirements.before.txt").read_text("utf-8")
    after = (PACK_DIR / "fixtures" / "negative" / "requirements_already_new.txt").read_text("utf-8")
    assert PACK.from_.package in before
    assert PACK.to.package not in before
    assert PACK.to.package in after
    assert PACK.from_.package not in after.replace(PACK.to.package, "")


def test_sources_has_a_section_for_every_change_and_no_orphans() -> None:
    """ADR-006: no citable source, no rule. A heading may list several comma-separated ids."""
    headings = re.findall(r"^## (.+)$", SOURCES.read_text(encoding="utf-8"), re.MULTILINE)
    cited = {
        identifier.strip()
        for heading in headings
        for identifier in heading.split(",")
        if identifier.strip() in CHANGES
    }
    assert cited == set(CHANGES), sorted(cited ^ set(CHANGES))
    prose = {"The two retrieved pages", "The measurement, and why it outranks the page"}
    unaccounted = [
        heading
        for heading in headings
        if heading not in prose and not all(part.strip() in CHANGES for part in heading.split(","))
    ]
    assert unaccounted == [], unaccounted


def test_sources_records_the_hash_of_the_page_the_pack_cites() -> None:
    assert PACK.source.sha256 is not None
    assert PACK.source.sha256 in SOURCES.read_text(encoding="utf-8")
    assert PACK.source.url in SOURCES.read_text(encoding="utf-8")


def test_the_safety_tables_are_asserted_against_members_and_not_construction() -> None:
    """The control: construction accepts invented names with only a warning."""
    with pytest.warns(UserWarning, match="is not a valid") as captured:
        fabricated = types.SafetySetting(
            category="HARM_CATEGORY_HATE",
            threshold="BLOCK_EVERYTHING",
        )
    assert [str(warning.message) for warning in captured] == [
        "HARM_CATEGORY_HATE is not a valid HarmCategory",
        "BLOCK_EVERYTHING is not a valid HarmBlockThreshold",
    ]
    assert fabricated.category is not None
    assert "HARM_CATEGORY_HATE" not in types.HarmCategory.__members__
    assert "BLOCK_EVERYTHING" not in types.HarmBlockThreshold.__members__

    for params in MODEL_PARAMS:
        for value in params.safety.category_map.values():
            assert value in types.HarmCategory.__members__, value
        for value in params.safety.threshold_map.values():
            assert value in types.HarmBlockThreshold.__members__, value
        # `OFF` is a member of both enums but never a string the legacy lookup took.
        for member in params.safety.category_members:
            assert member in types.HarmCategory.__members__, member
        for member in params.safety.threshold_members:
            assert member in types.HarmBlockThreshold.__members__, member
        assert "OFF" in params.safety.threshold_members
        assert "off" not in params.safety.threshold_map


def test_the_safety_tables_refuse_what_the_legacy_lookup_refused() -> None:
    """The three keys PACK_SPEC names, and the canonical long forms it requires."""
    for params in MODEL_PARAMS:
        assert "dangerous_content" not in params.safety.category_map
        assert "off" not in params.safety.threshold_map
        assert "none" not in params.safety.threshold_map
        # Long forms are keys too: code writes them and the legacy SDK looked up `value.lower()`.
        for member in types.HarmCategory.__members__:
            if member in set(params.safety.category_map.values()):
                assert member.lower() in params.safety.category_map, member


def test_the_generation_config_keys_are_the_fifteen_that_exist_on_both_sides() -> None:
    fields = types.GenerateContentConfig.model_fields
    for params in MODEL_PARAMS:
        assert len(params.generation_config_keys) == 15
        missing = [key for key in params.generation_config_keys if key not in fields]
        assert missing == [], missing
        # `seed` exists on the new config, so mapping it looks free, but it was never a legacy key.
        assert "seed" in fields
        assert "seed" not in params.generation_config_keys


def test_every_class_the_pack_names_on_the_new_side_exists() -> None:
    """Attribute lookup, not construction, for the same reason as the safety tables."""
    named = {params.config_class for params in MODEL_PARAMS}
    named |= {
        symbol
        for params in MODEL_PARAMS
        for symbol in (
            params.safety.setting_class,
            params.safety.category_class,
            params.safety.threshold_class,
        )
    }
    named |= {params.config_class for params in CALL_PARAMS if params.config_class}
    for params in RENAME_PARAMS:
        named |= set(params.submodule_map.values())
        for target in params.types_symbol_map.values():
            named.add(f"{params.submodule_map['types']}.{target}")
    for symbol in sorted(named):
        module_path, _, attribute = symbol.rpartition(".")
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            module = importlib.import_module(symbol)
            continue
        assert hasattr(module, attribute), f"{symbol} does not exist in the installed SDK"


def test_the_new_module_the_import_rule_targets_is_importable() -> None:
    for params in RENAME_PARAMS:
        assert importlib.import_module(params.to_module) is not None


def test_generation_config_is_never_mapped_to_itself() -> None:
    """Both names exist in the new SDK, so the class check above cannot catch an identity map."""
    assert hasattr(types, "GenerationConfig")
    assert hasattr(types, "GenerateContentConfig")
    assert "generation_config" not in types.GenerateContentConfig.model_fields
    for params in RENAME_PARAMS:
        assert params.types_symbol_map["GenerationConfig"] == "GenerateContentConfig"


def test_the_new_call_returns_one_model_class_where_the_legacy_one_returned_two() -> None:
    """A tuned name comes back as the wrong class without error, so only `models/` carries."""
    from google.genai import _api_client, _transformers, models

    # `t_model` reads only `vertexai`; a real client would need a key and a network.
    client = cast("_api_client.BaseApiClient", SimpleNamespace(vertexai=False))
    assert _transformers.t_model(client, "models/gemini-1.5-flash") == "models/gemini-1.5-flash"
    assert _transformers.t_model(client, "tunedModels/mine") == "tunedModels/mine"
    assert typing.get_type_hints(models.Models.get)["return"] is types.Model
    assert hasattr(types, "TunedModel"), "the class exists; models.get is just never it"
    prefixes = {
        parameter: values
        for params in CALL_PARAMS
        for parameter, values in params.dispatch_prefixes.items()
    }
    assert prefixes == {"name": ("models/",)}


def test_the_files_calls_take_a_handle_as_well_as_a_name() -> None:
    """`t_file_name` reads `.name` off a `types.File`; other handles fail, hence the limitation."""
    from google.genai import _transformers

    assert _transformers.t_file_name(types.File(name="files/abc123")) == "abc123"
    assert _transformers.t_file_name("files/abc123") == "abc123"

    class Foreign:
        """Shaped like the legacy proto-plus File."""

        name = "files/legacy1"
        uri = "https://generativelanguage.googleapis.com/v1beta/files/legacy1"

    with pytest.raises(ValueError, match="Could not convert object of type"):
        _transformers.t_file_name(cast("types.File", Foreign()))
    text = " ".join(PACK.limitations)
    assert "legacy File, which the new call rejects" in text


def test_the_chat_object_has_no_history_attribute_which_is_why_it_is_flagged() -> None:
    from google.genai import chats

    assert not hasattr(chats.Chat, "history")
    assert hasattr(chats.Chat, "get_history")
    removed = {
        attribute
        for change in PACK.changes
        if isinstance(change, schema.FlagOnlyChange)
        for attribute in change.params.attributes
    }
    assert "google.generativeai.ChatSession.history" in removed


def test_the_hand_written_scan_specs_agree_with_the_bundled_pack() -> None:
    """Two test modules hand-write a `ScanSpec`; this checks their assumptions against the pack."""
    spec = loader.to_scan_spec(BUNDLED)
    assert spec.pack_id == BUNDLED_ID
    assert spec.client_symbol == "google.generativeai.configure"
    assert spec.constructor_symbols == ("google.generativeai.GenerativeModel",)
    assert spec.legacy_distribution == "google-generativeai"
    assert spec.new_distribution == "google-genai"
    assert spec.prefilter_tokens == ("generativeai",)
    model_methods = spec.methods_for("google.generativeai.GenerativeModel")
    assert set(model_methods) >= {
        "count_tokens",
        "generate_content",
        "generate_content_async",
        "start_chat",
    }
    assert ReceiverMethods(
        receiver="google.generativeai.ChatSession",
        methods=("send_message", "send_message_async"),
    ) in list(spec.supported_methods)


def test_the_limitations_say_which_surfaces_the_corpus_never_exercised() -> None:
    """PACK_SPEC requires it: four rule groups ship verified but never field-exercised."""
    text = " ".join(PACK.limitations).lower()
    assert "exercised them zero times" in text
    for surface in ("function calling", "embed_content", "files surface", "models surface"):
        assert surface.lower() in text, surface


def test_the_pack_declares_every_kind_and_the_registry_says_which_one_runs() -> None:
    """The scanner reads every declared kind; only the registry says which ones can apply."""
    assert (
        frozenset(
            {
                "configure_to_client",
                "flag_only",
                "generative_model_calls",
                "manifest_dependency",
                "rename_import",
                "rewrite_call",
            }
        )
        == IMPLEMENTED_KINDS
    )
    # `registry.RULES` holds only parsed-file kinds; the manifest kind is in `MANIFEST_RULES`.
    assert IMPLEMENTED_KINDS == schema.CHANGE_KINDS
    assert frozenset(registry.RULES) < schema.CHANGE_KINDS
    assert {change.kind for change in PACK.changes} == schema.CHANGE_KINDS


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


def test_pack_validate_accepts_the_bundled_pack_by_id_and_by_path() -> None:
    for reference in (BUNDLED_ID, str(BUNDLED.path)):
        result = runner.invoke(app, ["pack", "validate", reference])
        assert result.exit_code == 0, result.output
        assert "is a valid migration pack." in result.output
        assert BUNDLED.sha256 in result.output


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
    result = runner.invoke(app, ["pack", "validate", BUNDLED_ID])
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
