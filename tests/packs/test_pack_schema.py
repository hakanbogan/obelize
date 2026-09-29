"""The MigrationPack model, field by field, and the loader that reads one.

The base document is imported from `_negative/_build.py`, not copied, so it cannot drift.
"""

from __future__ import annotations

import copy
import importlib.util
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from obelize.models import ScanSpec
from obelize.packs import loader, schema

ROOT = Path(__file__).resolve().parents[2]
NEGATIVE = Path(__file__).resolve().parent / "_negative"
BUILDER = NEGATIVE / "_build.py"
PACK_SPEC = ROOT / "docs" / "PACK_SPEC.md"
ADR_006 = ROOT / "docs" / "adr" / "ADR-006-pack-carries-no-code.md"


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("obelize_negative_pack_builder", BUILDER)
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
BUNDLED_ID = "gemini/google-generativeai-to-google-genai"


def minimal(**changed: Any) -> dict[str, Any]:
    """The smallest valid pack, with top-level keys replaced."""
    return {**copy.deepcopy(builder.MINIMAL), **changed}


def with_change(extra: dict[str, Any], **params: Any) -> dict[str, Any]:
    """`minimal()` plus one more change, with its params replaced."""
    document = minimal()
    appended = copy.deepcopy(extra)
    appended["params"] = {**appended["params"], **params}
    document["changes"].append(appended)
    return document


def with_safety(**overrides: Any) -> dict[str, Any]:
    """The model rule, with keys of its `safety` block replaced."""
    safety = {**copy.deepcopy(builder.MODEL_CHANGE)["params"]["safety"], **overrides}
    return with_change(builder.MODEL_CHANGE, safety=safety)


def build(document: dict[str, Any]) -> schema.PackDocument:
    return schema.PackDocument.model_validate(document)


def rewrite_params(pack: schema.PackDocument, index: int) -> schema.RewriteCallParams:
    """`changes` is a discriminated union, so a test has to say which member."""
    change = pack.changes[index]
    assert isinstance(change, schema.RewriteCallChange)
    return change.params


def flag_params(pack: schema.PackDocument, index: int) -> schema.FlagOnlyParams:
    change = pack.changes[index]
    assert isinstance(change, schema.FlagOnlyChange)
    return change.params


def test_the_kind_registry_is_the_one_adr_006_publishes() -> None:
    """ADR-006 lists the registry in full; a new kind is a code change."""
    text = ADR_006.read_text(encoding="utf-8")
    table = text[text.index("| kind | What it does |") :]
    documented = set()
    for line in table.splitlines()[2:]:
        if not line.startswith("|"):
            break
        documented.add(line.split("|")[1].strip().strip("`"))
    assert documented == schema.CHANGE_KINDS, sorted(documented ^ set(schema.CHANGE_KINDS))


def test_the_precondition_vocabulary_is_the_one_pack_spec_publishes() -> None:
    text = PACK_SPEC.read_text(encoding="utf-8")
    table = text[text.index("| Precondition | Holds when |") :]
    documented = set()
    for line in table.splitlines()[2:]:
        if not line.startswith("|"):
            break
        documented.add(line.split("|")[1].strip().strip("`"))
    assert documented == schema.PRECONDITIONS, sorted(documented ^ set(schema.PRECONDITIONS))


@pytest.mark.parametrize(
    ("values", "quoted"),
    [
        (schema.NEVER_IDENTITY_MAPPED, True),
        (schema.FORBIDDEN_CONFIG_KEYS, True),
        (schema.FORBIDDEN_SAFETY_CATEGORY_KEYS, False),
        (schema.FORBIDDEN_SAFETY_THRESHOLD_KEYS, False),
        (schema.FORBIDDEN_SAFETY_VALUES, False),
    ],
    ids=["identity", "config_key", "category_key", "threshold_key", "safety_value"],
)
def test_every_refusal_the_schema_hard_codes_is_named_in_pack_spec(
    values: frozenset[str], quoted: bool
) -> None:
    """Refusal data lives in code (ADR-006), so PACK_SPEC must name every value.

    Unquoted sets compare case-insensitively: PACK_SPEC's prose also writes them upper-case.
    """
    text = PACK_SPEC.read_text(encoding="utf-8")
    haystack = text if quoted else text.lower()
    for value in values:
        needle = value if quoted else value.lower()
        assert needle in haystack, f"{value} drives a refusal and PACK_SPEC.md does not name it"


def test_a_pack_that_names_a_schema_version_is_refused_as_an_unknown_key() -> None:
    """The format is unstable through 0.x, so a version field meets the unknown-key rule."""
    with pytest.raises(ValidationError, match="schema_version\n  Extra inputs are not permitted"):
        build(minimal(schema_version=1))


SHAPES: list[tuple[str, Any, str, str]] = [
    ("id", "Gemini/Legacy", "pack id of the form", "id-upper-case"),
    ("id", "gemini/a..b", "pack id of the form", "id-with-dots"),
    ("id", "gemini", "pack id of the form", "id-one-segment"),
    ("provider", "Demo", "lower-case, hyphen-separated", "provider-upper-case"),
    ("pack_version", "1.0", "semver", "version-two-part"),
    ("pack_version", "01.0.0", "semver", "version-leading-zero"),
]


@pytest.mark.parametrize(("field", "value", "says", "label"), SHAPES, ids=[s[3] for s in SHAPES])
def test_a_top_level_value_of_the_wrong_shape_is_refused(
    field: str, value: Any, says: str, label: str
) -> None:
    with pytest.raises(ValidationError, match=says):
        build(minimal(**{field: value}))


SOURCE_URLS = [
    ("https://example.invalid/guide", None),
    ("http://example.invalid/guide", "must be https"),
    ("https:///guide", "must name a host"),
    ("https://user:secret@example.invalid/guide", "must not carry a credential"),
    ("example.invalid/guide", "must be https"),
]


@pytest.mark.parametrize(("url", "says"), SOURCE_URLS, ids=[u[0] for u in SOURCE_URLS])
def test_a_source_url_is_provenance_that_never_carries_a_secret(url: str, says: str | None) -> None:
    """The host is copied into the run report, so a credential here leaks."""
    document = minimal()
    document["source"]["url"] = url
    if says is None:
        assert build(document).source.url == url
    else:
        with pytest.raises(ValidationError, match=says):
            build(document)


def test_a_source_hash_is_optional_and_a_fabricated_one_is_refused() -> None:
    document = minimal()
    assert build(document).source.sha256 is None
    document["source"]["sha256"] = "f" * 64
    assert build(document).source.sha256 == "f" * 64
    document["source"]["sha256"] = "not-a-digest"
    with pytest.raises(ValidationError, match="sha256"):
        build(document)


FIXTURE_PATHS = [
    ("fixtures/positive/one.before.py", None),
    ("fixtures/", "name a file or a directory"),
    ("positive/one.before.py", "must be under fixtures/"),
    ("/etc/passwd", "must be relative"),
    ("fixtures\\positive\\one.py", "forward slashes"),
]


@pytest.mark.parametrize(("path", "says"), FIXTURE_PATHS, ids=[f[0] for f in FIXTURE_PATHS])
def test_a_fixture_path_stays_inside_the_pack_directory(path: str, says: str | None) -> None:
    document = minimal()
    document["changes"][0]["fixtures"] = [path]
    if says is None:
        assert build(document).changes[0].fixtures == (path,)
    else:
        with pytest.raises(ValidationError, match=says):
            build(document)


def test_under_any_matches_on_the_dotted_path_and_never_on_the_string() -> None:
    modules = ("google.generativeai",)
    assert schema.under_any("google.generativeai", modules)
    assert schema.under_any("google.generativeai.configure", modules)
    assert not schema.under_any("google.generativeaix.configure", modules)
    assert not schema.under_any("google.genai.Client", modules)


def test_a_field_whose_order_carries_nothing_has_one_spelling() -> None:
    document = minimal()
    document["match"]["prefilter_tokens"] = ["demo_legacy", "demo_legacy"]
    with pytest.raises(ValidationError, match="sorted and de-duplicated"):
        build(document)


def test_a_field_whose_order_is_data_refuses_only_the_duplicate() -> None:
    """`positional_to_kw` is the legacy parameter order; sorting would reorder lifted arguments."""
    document = minimal()
    document["changes"].append(
        {
            "id": "upload-file",
            "kind": "rewrite_call",
            "citation": "Guide, Files",
            "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
            "params": {
                "legacy_symbol": "demo_legacy.upload",
                "new_call": "files.upload",
                "positional_to_kw": ["path", "mime_type"],
            },
        }
    )
    assert rewrite_params(build(document), 1).positional_to_kw == ("path", "mime_type")

    document["changes"][1]["params"]["positional_to_kw"] = ["path", "path"]
    with pytest.raises(ValidationError, match="must not repeat an entry"):
        build(document)


def test_a_repeated_limitation_is_refused_and_the_order_is_kept() -> None:
    document = minimal(limitations=["Second thing.", "First thing."])
    assert build(document).limitations == ("Second thing.", "First thing.")
    with pytest.raises(ValidationError, match="must not repeat an entry"):
        build(minimal(limitations=["Same.", "Same."]))


def test_a_verification_block_with_no_suggestion_is_refused() -> None:
    with pytest.raises(ValidationError, match="drop the verification block"):
        build(minimal(verification={"suggestions": []}))


def test_a_suggestion_is_display_text_and_not_a_runnable_command() -> None:
    """Never run, so `&&` is fine; `.obelize.yml`'s `verify.commands` do run and refuse it."""
    built = build(minimal(verification={"suggestions": ["pytest -q && python -m mypy src"]}))
    assert built.verification is not None
    assert built.verification.suggestions == ("pytest -q && python -m mypy src",)


RENAME_DEFECTS = [
    ({"to_module": "demo_legacy"}, "nothing to rename"),
    ({"types_alias_fallback": "demo"}, "must differ from default_alias"),
    ({"submodule_map": {"types": "elsewhere.types"}}, "must be under to_module"),
]


@pytest.mark.parametrize(("params", "says"), RENAME_DEFECTS, ids=["same", "alias", "submodule"])
def test_the_import_rule_refuses_a_rename_that_cannot_be_performed(
    params: dict[str, Any], says: str
) -> None:
    with pytest.raises(ValidationError, match=says):
        build(with_change(builder.RENAME_CHANGE, **params))


EMPTY_VALUES = [
    ("match", "prefilter_tokens", [], "every file in the repository is parsed"),
    ("from", "version", "  ", "PEP 440 version specifier such as"),
]


@pytest.mark.parametrize(
    ("section", "key", "value", "says"),
    EMPTY_VALUES,
    ids=["no-prefilter-token", "blank-specifier"],
)
def test_a_field_left_empty_is_refused_where_emptiness_changes_the_behaviour(
    section: str, key: str, value: Any, says: str
) -> None:
    """Empty means "everything": no token parses every file; a blank specifier matches any."""
    document = minimal()
    document[section][key] = value
    with pytest.raises(ValidationError, match=says):
        build(document)


def test_an_empty_safety_table_key_is_refused() -> None:
    """The lower-case rule accepts `""` -- it equals its own `.lower()`."""
    with pytest.raises(ValidationError, match="must not be empty"):
        build(with_safety(category_map={"": "HARM_CATEGORY_HARASSMENT"}))


def test_a_client_rule_that_allows_no_keyword_refuses_every_real_call() -> None:
    document = minimal()
    document["changes"][0]["params"]["allowed_kwargs"] = []
    with pytest.raises(ValidationError, match="every call with a keyword is refused"):
        build(document)


MODEL_DEFECTS = [
    ({"methods": {}}, "no call can be rewritten"),
    ({"methods": {"demo_legacy.Model": []}}, "drop the entry instead"),
    ({"generation_config_keys": []}, "every config would be unknown"),
    ({"default_model_name": "models/demo-1"}, "bare model name"),
    ({"config_class": "types.Config()"}, "fully qualified symbol"),
]


@pytest.mark.parametrize(
    ("params", "says"),
    MODEL_DEFECTS,
    ids=[
        "no-methods",
        "empty-method-list",
        "no-config-keys",
        "prefixed-model",
        "config-class-is-a-call",
    ],
)
def test_the_model_rule_refuses_parameters_it_could_not_act_on(
    params: dict[str, Any], says: str
) -> None:
    with pytest.raises(ValidationError, match=says):
        build(with_change(builder.MODEL_CHANGE, **params))


SAFETY_DEFECTS = [
    ({"category_map": {}}, "no safety setting could be mapped"),
    ({"threshold_map": {}}, "no safety setting could be mapped"),
    ({"category_members": []}, "no enum member could be recognised"),
    ({"threshold_members": []}, "no enum member could be recognised"),
    ({"category_map": {"harassment": "harm_category_harassment"}}, "UPPER_SNAKE"),
    ({"category_members": ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HARASSMENT"]}, "de-duplic"),
]


@pytest.mark.parametrize(
    ("params", "says"),
    SAFETY_DEFECTS,
    ids=[
        "no-categories",
        "no-thresholds",
        "no-category-members",
        "no-threshold-members",
        "lower-case-member",
        "repeated-member",
    ],
)
def test_the_safety_table_refuses_what_it_could_not_act_on(
    params: dict[str, Any], says: str
) -> None:
    with pytest.raises(ValidationError, match=says):
        build(with_safety(**params))


def test_a_history_shape_with_no_roles_refuses_every_entry() -> None:
    document = with_change(builder.MODEL_CHANGE)
    document["changes"][1]["params"]["history"] = {
        "role_key": "role",
        "parts_key": "parts",
        "text_key": "text",
        "roles": [],
    }
    with pytest.raises(ValidationError, match="every history entry would be refused"):
        build(document)


CONFIG_TRIPLE = [
    ({"config_class": "demo_modern.types.Config"}, "go together"),
    ({"config_kwargs": ["title"]}, "go together"),
    ({"config_kwarg": "config"}, "go together"),
]


def _call_change(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "embed-content",
        "kind": "rewrite_call",
        "citation": "Guide, Embed content",
        "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
        "params": {
            "legacy_symbol": "demo_legacy.embed",
            "new_call": "models.embed_content",
            **params,
        },
    }


@pytest.mark.parametrize(
    ("params", "says"), CONFIG_TRIPLE, ids=["class-only", "kwargs-only", "kwarg-only"]
)
def test_a_config_class_its_keywords_and_its_name_arrive_together(
    params: dict[str, Any], says: str
) -> None:
    """The new call needs `config_kwarg`, the keyword to pass the config under."""
    document = minimal()
    document["changes"].append(_call_change(params))
    with pytest.raises(ValidationError, match=says):
        build(document)


def test_the_three_configuration_fields_are_accepted_together() -> None:
    """The control: without it the cases above could fail for another reason."""
    document = minimal()
    document["changes"].append(
        _call_change(
            {
                "config_class": "demo_modern.types.Config",
                "config_kwargs": ["title"],
                "config_kwarg": "config",
            }
        )
    )
    params = rewrite_params(build(document), 1)
    assert (params.config_class, params.config_kwargs, params.config_kwarg) == (
        "demo_modern.types.Config",
        ("title",),
        "config",
    )


NEW_CALLS = [
    ("models.embed_content", None),
    ("embed_content", "a service and a method"),
    (".models.embed", "dotted path under the client"),
    ("models.embed()", "dotted path under the client"),
]


@pytest.mark.parametrize(("new_call", "says"), NEW_CALLS, ids=[c[0] for c in NEW_CALLS])
def test_a_new_call_is_a_path_under_the_client(new_call: str, says: str | None) -> None:
    document = minimal()
    document["changes"].append(
        {
            "id": "embed-content",
            "kind": "rewrite_call",
            "citation": "Guide, Embed content",
            "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
            "params": {"legacy_symbol": "demo_legacy.embed", "new_call": new_call},
        }
    )
    if says is None:
        assert rewrite_params(build(document), 1).new_call == new_call
    else:
        with pytest.raises(ValidationError, match=says):
            build(document)


FLAG_DEFECTS = [
    ({"symbols": []}, "must name a symbol, a pattern or an attribute"),
    ({"attributes": ["demo_legacy"]}, "a dotted path"),
    (
        {"symbols": ["demo_legacy.protos"], "attributes": ["demo_legacy.protos"]},
        "both a symbol and an attribute",
    ),
    ({"patterns": ["regular_expression"]}, "Input should be"),
]


@pytest.mark.parametrize(
    ("params", "says"), FLAG_DEFECTS, ids=["nothing", "bare-name", "both", "unknown-pattern"]
)
def test_the_flag_rule_refuses_a_refusal_that_names_nothing_usable(
    params: dict[str, Any], says: str
) -> None:
    with pytest.raises(ValidationError, match=says):
        build(with_change(builder.FLAG_CHANGE, **params))


def test_the_three_channels_of_a_flag_rule_produce_two_different_bails() -> None:
    """Symbols and shapes bail `flag_only_surface`, attributes `attribute_removed`: two fields."""
    document = with_change(
        builder.FLAG_CHANGE,
        symbols=["demo_legacy.protos"],
        patterns=["mock_patch_target"],
        attributes=["demo_legacy.Chat.history"],
    )
    params = flag_params(build(document), 1)
    assert params.symbols == ("demo_legacy.protos",)
    assert params.patterns == ("mock_patch_target",)
    assert params.attributes == ("demo_legacy.Chat.history",)


def test_a_manifest_rule_that_rewrites_a_name_to_itself_is_refused() -> None:
    """Canonicalised, so `Demo_Legacy` and `demo-legacy` are one distribution."""
    with pytest.raises(ValidationError, match="canonicalise to the same distribution"):
        build(with_change(builder.MANIFEST_CHANGE, to_name="Demo_Legacy"))


def test_a_pack_with_no_changes_describes_no_migration() -> None:
    with pytest.raises(ValidationError, match="must declare at least one change"):
        build(minimal(changes=[]))


def test_two_rules_cannot_declare_the_supported_methods_of_one_receiver() -> None:
    document = with_change(builder.MODEL_CHANGE)
    document["changes"].append({**copy.deepcopy(builder.MODEL_CHANGE), "id": "model-calls-again"})
    with pytest.raises(ValidationError, match="declare the supported methods"):
        build(document)


def test_two_rewrite_rules_cannot_claim_one_symbol() -> None:
    document = minimal()
    call = {
        "id": "embed-content",
        "kind": "rewrite_call",
        "citation": "Guide, Embed content",
        "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
        "params": {"legacy_symbol": "demo_legacy.embed", "new_call": "models.embed_content"},
    }
    document["changes"].extend([call, {**copy.deepcopy(call), "id": "embed-content-again"}])
    with pytest.raises(ValidationError, match="which one applies"):
        build(document)


def test_a_symbol_cannot_be_both_renamed_and_refused() -> None:
    document = with_change(builder.FLAG_CHANGE, symbols=["demo_legacy.types.GenerationConfig"])
    document["changes"].append(copy.deepcopy(builder.RENAME_CHANGE))
    with pytest.raises(ValidationError, match="renamed or refused, not both"):
        build(document)


def test_the_bounds_of_two_ranges_over_one_distribution_are_compared() -> None:
    """Bounds compare only within one distribution: `A 0.5` to `B 0.5` is a legitimate rename."""
    document = minimal()
    document["from"] = {"package": "demo-legacy", "version": "<1"}
    document["to"] = {"package": "demo-legacy", "version": ">=1"}
    assert build(document).to.version == ">=1"

    document["to"]["version"] = ">=0.5"
    with pytest.raises(ValidationError, match="both sides of the migration"):
        build(document)

    document["from"]["version"] = ">=2"
    document["to"]["version"] = "<1"
    with pytest.raises(ValidationError, match="move backwards"):
        build(document)

    # A wildcard names no single version, so it is skipped rather than guessed at.
    document["from"]["version"] = "==0.*"
    document["to"]["version"] = "==1.*"
    assert build(document).from_.version == "==0.*"

    document["from"] = {"package": "demo-legacy", "version": "<1"}
    document["to"] = {"package": "demo-modern", "version": "<1"}
    assert build(document).to.package == "demo-modern"


def test_a_bundled_id_resolves_inside_the_packs_directory() -> None:
    path, bundled = loader.resolve(BUNDLED_ID)
    assert bundled is True
    assert path == loader.BUNDLED / "gemini" / BUNDLED_ID.split("/")[1] / loader.PACK_FILENAME
    assert loader.bundled_ids() == (BUNDLED_ID,)


def test_an_id_shaped_reference_with_no_bundled_pack_is_tried_as_a_path() -> None:
    path, bundled = loader.resolve("gemini/nothing-here")
    assert bundled is False
    assert path == Path("gemini/nothing-here")


def test_a_reference_cannot_climb_out_of_the_packs_directory(tmp_path: Path) -> None:
    """TM-1: the id shape admits no dot, so `..` never joins.

    The escape target exists on purpose: without it the test passes even with no shape check.
    """
    root = tmp_path / "packs"
    (root / "gemini" / "real").mkdir(parents=True)
    (root / "gemini" / "real" / loader.PACK_FILENAME).write_bytes(b"")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / loader.PACK_FILENAME).write_bytes(b"")

    for reference in ("gemini/../../outside", "../outside", "/etc/passwd", "gemini/../outside"):
        path, bundled = loader.resolve(reference, root)
        assert bundled is False, reference
        assert path == Path(reference)

    # The control.
    path, bundled = loader.resolve("gemini/real", root)
    assert bundled is True
    assert path.is_relative_to(root)


def test_a_directory_that_is_not_an_id_is_not_a_bundled_pack(tmp_path: Path) -> None:
    """`bundled_ids` reads directory names, so it filters what it finds."""
    for name in ("gemini/Legacy-To-Modern", "demo/legacy-to-modern"):
        target = tmp_path / name / loader.PACK_FILENAME
        target.parent.mkdir(parents=True)
        target.write_bytes(b"")
    assert loader.bundled_ids(tmp_path) == ("demo/legacy-to-modern",)


def test_a_missing_pack_is_a_usage_error_and_not_an_invalid_one(tmp_path: Path) -> None:
    with pytest.raises(loader.PackNotFoundError, match="no pack at"):
        loader.load(str(tmp_path / "absent.yaml"))
    with pytest.raises(loader.PackNotFoundError, match="or a path to a pack file"):
        loader.load(str(tmp_path), tmp_path)


DOCUMENT_DEFECTS = [
    (b"\xff\xfe\x00i\x00d", "not UTF-8"),
    (b"id: [unclosed\n", "line 2, column 1"),
    (b"id: \x01demo\n", "not valid YAML: unacceptable character"),
    (b"- one\n- two\n", "this one is a list"),
    (b"# nothing but a comment\n", "the file is empty"),
    (b"provider: demo\nprovider: demo\n", "duplicate key 'provider'"),
]


@pytest.mark.parametrize(
    ("data", "says"),
    DOCUMENT_DEFECTS,
    ids=["not-utf8", "not-yaml", "unreadable-character", "not-a-mapping", "empty", "duplicate-key"],
)
def test_bytes_that_are_not_a_pack_document_are_refused_with_a_reason(
    tmp_path: Path, data: bytes, says: str
) -> None:
    path = tmp_path / "pack.yaml"
    path.write_bytes(data)
    with pytest.raises(loader.PackInvalidError) as excinfo:
        loader.load(str(path))
    assert any(says in problem for problem in excinfo.value.problems), excinfo.value.problems
    assert excinfo.value.bundled is False


def test_an_invalid_bundled_pack_says_so_because_the_exit_code_differs(tmp_path: Path) -> None:
    """A bundled pack that does not validate is an obelize defect, and exits `1`."""
    target = tmp_path / "demo" / "legacy-to-modern" / loader.PACK_FILENAME
    target.parent.mkdir(parents=True)
    target.write_text("language: klingon\n", encoding="utf-8")
    with pytest.raises(loader.PackInvalidError) as excinfo:
        loader.load("demo/legacy-to-modern", tmp_path)
    assert excinfo.value.bundled is True
    assert excinfo.value.reference == "demo/legacy-to-modern"


def test_the_hash_is_of_the_bytes_on_disk_and_not_of_a_reparse(tmp_path: Path) -> None:
    """`pack.yaml` is copied verbatim into the run folder, so this is its hash."""
    import hashlib

    source = loader.load(BUNDLED_ID)
    assert source.sha256 == hashlib.sha256(source.path.read_bytes()).hexdigest()
    assert source.sha256 == hashlib.sha256(source.data).hexdigest()

    # A comment is not part of the document and is part of the artefact.
    copied = tmp_path / "pack.yaml"
    copied.write_bytes(source.data + b"\n# one more comment\n")
    assert loader.load(str(copied)).sha256 != source.sha256


def test_loading_a_pack_contacts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """PACK_SPEC hard rule 1: `source.url` is never fetched; blocked sockets prove it."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("loading a pack opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    loaded = loader.load(BUNDLED_ID)
    assert loaded.pack.source.url.startswith("https://")


# Every `ScanSpec` field, closed-world: one with no source in the pack is read and never filled.
PROJECTED = {
    "transitive_modules",
    "pack_id",
    "pack_version",
    "pack_sha256",
    "legacy_modules",
    "legacy_distribution",
    "new_distribution",
    "prefilter_tokens",
    "symbols",
    "client_symbol",
    "constructor_symbols",
    "supported_methods",
    "method_returns",
    "removed_attributes",
    "flag_only_symbols",
    "flag_only_patterns",
}


def test_the_projection_fills_every_field_of_the_scan_spec() -> None:
    assert set(ScanSpec.model_fields) == PROJECTED
    spec = loader.to_scan_spec(loader.load(BUNDLED_ID))
    empty = [name for name in PROJECTED if not getattr(spec, name)]
    assert empty == [], f"the bundled pack leaves {empty} empty, so nothing exercises them"


def test_the_projection_carries_nothing_that_describes_a_rewrite() -> None:
    """The scan uses no rewrite data; carrying it would void the findings cache on rewording."""
    spec = loader.to_scan_spec(loader.load(BUNDLED_ID))
    dumped = spec.model_dump_json()
    for leaked in ("HARM_CATEGORY", "GenerateContentConfig", "suggestion", "temperature"):
        assert leaked not in dumped, f"{leaked} crossed the ScanSpec seam"


def test_the_projection_digest_ignores_the_pack_identity_and_nothing_else() -> None:
    """A digest blind to a field the scanner reads would pass a stale measurement."""
    spec = loader.to_scan_spec(loader.load(BUNDLED_ID))
    baseline = loader.spec_digest(spec)
    identity = {"pack_id": "other/pack", "pack_version": "9.9.9", "pack_sha256": "f" * 64}
    assert loader.spec_digest(spec.model_copy(update=identity)) == baseline
    for field in spec.model_dump():
        if field in identity:
            continue
        value = getattr(spec, field)
        assert value, f"{field} is empty, so emptying it proves nothing"
        emptied = () if isinstance(value, tuple) else ""
        assert loader.spec_digest(spec.model_copy(update={field: emptied})) != baseline, field


def test_a_pack_with_no_model_rule_projects_an_empty_method_table() -> None:
    """The minimal pack is the case: a projection is not required to be full."""
    document = minimal()
    spec = loader.to_scan_spec(
        loader.LoadedPack(
            pack=build(document),
            sha256="a" * 64,
            data=b"",
            reference="demo/legacy-to-modern",
            bundled=False,
            path=Path("pack.yaml"),
        )
    )
    assert spec.constructor_symbols == ()
    assert spec.supported_methods == ()
    assert spec.methods_for("demo_legacy.Model") == ()
    assert spec.client_symbol == "demo_legacy.configure"
