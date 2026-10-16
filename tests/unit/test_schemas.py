"""The committed JSON Schemas are generated, never hand-edited: local half of `ci / schema-drift`.

`pack.schema.json` is `docs/PACK_SPEC.md` in machine form, to check a pack without obelize.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from obelize.models import (
    BAIL_CODES,
    CONFIDENCE_REASONS,
    FINDING_KINDS,
    QUALIFIED_NAME,
    SCAN_STATUSES,
    DisplayText,
    DistributionName,
    FindingsDocument,
    Instant,
    ModelDocument,
    PlainName,
    PlanDocument,
    PrefilterToken,
    ProposalRecord,
    QualifiedName,
    RelativePath,
    RunId,
    RunRecord,
    Sha256,
    UndoRecord,
)
from obelize.packs.schema import (
    CHANGE_KINDS,
    EnumMemberName,
    FixturePath,
    PackDocument,
    PackId,
    SemVer,
    Slug,
    SymbolKey,
    TrailingCharacter,
)
from obelize.schemas import generate
from platforms import text_files_as_on_windows

COMMITTED = {name: generate.HERE / name for name, _ in generate.SCHEMAS}
NAMES = [name for name, _ in generate.SCHEMAS]


def _document(name: str) -> dict[str, Any]:
    return dict(json.loads(COMMITTED[name].read_text(encoding="utf-8")))


def test_every_committed_schema_matches_its_model() -> None:
    assert not generate.stale(), (
        f"{generate.stale()} no longer match their models. Run "
        f"`uv run python src/obelize/schemas/generate.py` and commit the result."
    )


def test_the_generated_schemas_are_the_documents_that_exist() -> None:
    """`verify.json` is `run.json`'s `verify` object; `model/`'s two are unreachable from it."""
    assert NAMES == [
        "findings.schema.json",
        "model.schema.json",
        "pack.schema.json",
        "plan.schema.json",
        "proposal.schema.json",
        "run.schema.json",
        "undo.schema.json",
    ]
    assert dict(generate.SCHEMAS) == {
        "findings.schema.json": FindingsDocument,
        "model.schema.json": ModelDocument,
        "pack.schema.json": PackDocument,
        "plan.schema.json": PlanDocument,
        "proposal.schema.json": ProposalRecord,
        "run.schema.json": RunRecord,
        "undo.schema.json": UndoRecord,
    }
    assert frozenset({PackDocument}) == generate.READ
    for path in COMMITTED.values():
        assert path.exists(), path


@pytest.mark.parametrize(("name", "model"), generate.SCHEMAS, ids=NAMES)
def test_rendering_twice_produces_the_same_bytes(name: str, model: Any) -> None:
    """`sort_keys` is on so that a reordered field is not a diff."""
    once = generate.render(model)
    assert once == generate.render(model)
    assert once.endswith("}\n")
    document = json.loads(once)
    assert list(document) == sorted(document)


@pytest.mark.parametrize(
    ("name", "title"),
    [("findings.schema.json", "FindingsDocument"), ("pack.schema.json", "PackDocument")],
)
def test_the_schema_names_the_dialect_it_is_written_in(name: str, title: str) -> None:
    document = _document(name)
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["title"] == title


def _objects(document: dict[str, Any]) -> dict[str, Any]:
    """Every object definition, including the root. Enum defs are not objects."""
    found = {document["title"]: document}
    for name, definition in document.get("$defs", {}).items():
        if definition.get("type") == "object":
            found[name] = definition
    return found


# Fields a document would carry if it promised a compatibility policy.
VERSION_FIELDS = {"schema_version", "run_schema_version"}


@pytest.mark.parametrize("name", NAMES)
def test_no_document_carries_a_version_field(name: str) -> None:
    """Formats are unstable through 0.x; checked on the schema, which outside readers see."""
    document = _document(name)
    for definition_name, definition in _objects(document).items():
        assert not VERSION_FIELDS & set(definition.get("properties", {})), definition_name


# The documents obelize writes; spelled out because `generate.READ` is under test.
WRITTEN = [
    "findings.schema.json",
    "model.schema.json",
    "plan.schema.json",
    "proposal.schema.json",
    "run.schema.json",
    "undo.schema.json",
]


@pytest.mark.parametrize("name", WRITTEN)
def test_a_written_document_requires_every_field_the_writer_writes(name: str) -> None:
    """Writers dump every field, defaults included, so no field may be optional in the schema."""
    document = _document(name)
    for definition_name, definition in _objects(document).items():
        assert set(definition.get("required", [])) == set(definition["properties"]), definition_name


@pytest.mark.parametrize("name", NAMES)
def test_every_object_in_the_schema_is_closed(name: str) -> None:
    """An unknown key may mean something else to another version, so every object is closed."""
    document = _document(name)
    objects = _objects(document)
    assert len(objects) > 1, name
    for definition_name, definition in objects.items():
        assert definition["additionalProperties"] is False, definition_name


def test_the_pack_schema_publishes_the_rule_kind_registry() -> None:
    """The discriminator lets an outside validator pick a `kind`'s parameter set."""
    document = _document("pack.schema.json")
    mapping = document["properties"]["changes"]["items"]["discriminator"]["mapping"]
    assert set(mapping) == CHANGE_KINDS
    assert document["properties"]["changes"]["items"]["discriminator"]["propertyName"] == "kind"
    # The field is `from_` (a Python keyword); the schema must publish the alias pack authors write.
    assert "from" in document["properties"]
    assert "from_" not in document["properties"]


@pytest.mark.parametrize(
    ("field", "vocabulary"),
    [
        ("kind", FINDING_KINDS),
        ("confidence_reason", CONFIDENCE_REASONS),
        ("scan_status", SCAN_STATUSES),
    ],
)
def test_the_schema_publishes_the_closed_vocabularies(
    field: str, vocabulary: frozenset[str]
) -> None:
    document = json.loads(COMMITTED["findings.schema.json"].read_text(encoding="utf-8"))
    assert set(document["$defs"]["Finding"]["properties"][field]["enum"]) == vocabulary


def test_the_nullable_fields_publish_their_vocabulary_too() -> None:
    """`bail` is `enum | null`, so the members sit one level further in."""
    document = json.loads(COMMITTED["findings.schema.json"].read_text(encoding="utf-8"))
    options = document["$defs"]["Finding"]["properties"]["bail"]["anyOf"]
    enums = [set(option["enum"]) for option in options if "enum" in option]
    assert enums == [set(BAIL_CODES)]


def _schema_accepts(schema: dict[str, Any], value: str) -> bool:
    """The keywords a validator without `format` support applies to a string."""
    pattern = schema.get("pattern")
    return (pattern is None or re.search(pattern, value) is not None) and (
        schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value))
    )


VALUE_RULES: dict[str, tuple[Any, str, list[str]]] = {
    "Sha256": (Sha256, "a" * 64, ["A" * 64, "a" * 63, ""]),
    "RunId": (RunId, "20260917T142530Z-3f9a1c72", ["20260917-142530-3f9a1c72", "x"]),
    "Instant": (
        Instant,
        "2026-09-18T09:14:07Z",
        ["2026-09-18 09:14:07", "2026-09-18T09:14:07+00:00"],
    ),
    "QualifiedName": (QualifiedName, "pkg.mod.Name", ["pkg..Name", "1pkg", "pkg."]),
    "DistributionName": (DistributionName, "google-genai", ["-genai", "genai-", "a b"]),
    "PlainName": (PlainName, "client", ["1client", "a.b", "a-b"]),
    "PackId": (PackId, "google/gemini-1", ["google", "Google/gemini", "google/gemini/x", "g.x/y"]),
    "Slug": (Slug, "py-pdf", ["Py-pdf", "py--pdf", "-py"]),
    "SemVer": (SemVer, "0.1.0-rc.1", ["1.0", "01.0.0", "1.0.0+build", "1\u0662.0.0"]),
    "EnumMemberName": (EnumMemberName, "HARM_CATEGORY_X", ["harm", "_X", "1X"]),
    "SymbolKey": (SymbolKey, "Name", ["a.b.c", "a-b", ".a"]),
    "TrailingCharacter": (TrailingCharacter, "!", ["ab", "7", "'", "\\", ""]),
    "FixturePath": (
        FixturePath,
        "fixtures/a\nb.py",
        ["fixtures/", "fixtures", "positive/a.py", ""],
    ),
    "DisplayText": (DisplayText, "x" * 500, ["x" * 501, ""]),
    "PrefilterToken": (PrefilterToken, "google", [""]),
    "RelativePath": (RelativePath, "a/b.py", [""]),
}


@pytest.mark.parametrize(("kind", "valid", "invalid"), VALUE_RULES.values(), ids=VALUE_RULES)
def test_the_schema_states_the_value_rules_its_validator_checks(
    kind: Any, valid: str, invalid: list[str]
) -> None:
    """The schema never rejects what the validator accepts, and rejects what it can state."""
    adapter = TypeAdapter(kind)
    schema = adapter.json_schema()
    assert adapter.validate_python(valid) == valid
    assert _schema_accepts(schema, valid)
    for value in invalid:
        with pytest.raises(ValidationError):
            adapter.validate_python(value)
        assert not _schema_accepts(schema, value), value


def test_a_map_keyed_by_a_name_refuses_a_key_that_is_not_one() -> None:
    """`patternProperties` alone lets a key outside the pattern through unchecked."""
    transitive = _document("pack.schema.json")["$defs"]["Match"]["properties"]["transitive"]
    assert transitive["additionalProperties"] is False
    assert list(transitive["patternProperties"]) == [QUALIFIED_NAME.pattern]


def test_the_pack_schema_says_which_rules_it_leaves_to_the_validator() -> None:
    assert "`obelize pack validate`" in _document("pack.schema.json")["description"]


def test_the_generator_writes_where_it_is_told(tmp_path: Path) -> None:
    written = generate.write(tmp_path)
    assert [path.name for path in written] == NAMES
    assert written[0].read_text(encoding="utf-8") == generate.render(FindingsDocument)
    assert generate.stale(tmp_path) == []


def test_the_generator_writes_the_same_bytes_under_windows_text_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Text mode there ends each line with CRLF; the committed schemas end them with LF."""
    text_files_as_on_windows(monkeypatch)
    written = generate.write(tmp_path)
    assert {path.name: path.read_bytes() for path in written} == {
        name: generate.render(model).encode("utf-8") for name, model in generate.SCHEMAS
    }


def test_a_missing_or_edited_schema_is_drift(tmp_path: Path) -> None:
    assert generate.stale(tmp_path) == NAMES
    for name in NAMES:
        (tmp_path / name).write_text("{}\n", encoding="utf-8")
    assert generate.stale(tmp_path) == NAMES


def test_the_command_writes_reports_and_refuses_an_unknown_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(generate, "HERE", tmp_path)

    assert generate.main(["--check"]) == 1
    stale = capsys.readouterr().err
    for name in NAMES:
        assert f"stale: {name}" in stale

    assert generate.main([]) == 0
    assert capsys.readouterr().out.splitlines() == [f"wrote {name}" for name in NAMES]

    assert generate.main(["--check"]) == 0
    assert capsys.readouterr().err == ""

    assert generate.main(["--force"]) == 2
    assert "unknown argument '--force'" in capsys.readouterr().err


def test_the_command_reads_the_real_argv_when_it_is_given_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`ci / schema-drift` runs it as a script, with no arguments at all."""
    monkeypatch.setattr("sys.argv", ["generate.py", "--check"])
    assert generate.main() == 0
    assert capsys.readouterr().err == ""
