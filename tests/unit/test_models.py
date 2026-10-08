"""`docs/SCAN_VOCABULARY.md` tables equal the models' `Literal`s; the models enforce its rules."""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from obelize.fsutil import WRITE_REFUSALS
from obelize.models import (
    ATOMICITY_BAIL,
    BAIL_CODES,
    BINDING_KINDS,
    CONFIDENCE_REASONS,
    CONFIG_ORIGINS,
    DISPLAY_TEXT_LIMIT,
    EDIT_STATUSES,
    EXIT_CODES,
    FINDING_KINDS,
    FLAG_ONLY_PATTERNS,
    IMPORT_BAILS,
    IMPORT_KINDS,
    LIMITATION_CODES,
    PATH_REFUSALS,
    PROPOSAL_HELD,
    PROPOSAL_OUTCOMES,
    REFUSAL_CODES,
    REPO_ATOMICITY_BAIL,
    SCAN_STATUSES,
    SKIP_REASONS,
    VERDICTS,
    WARNING_CODES,
    WITHHELD,
    Binding,
    CommandRecord,
    CommandResult,
    ConsultationSkip,
    DisplayText,
    DistributionName,
    Edit,
    EditProposal,
    FileEdit,
    Finding,
    FindingsDocument,
    ImpactPlan,
    ManifestPlan,
    MethodReturn,
    ModelDocument,
    PackRef,
    PlainName,
    PlanDocument,
    ProposalRecord,
    ProvidedModule,
    QualifiedName,
    ReceiverMethods,
    RefusalCode,
    RunCounts,
    RunLimitation,
    RunModel,
    RunPlatform,
    RunPython,
    RunRecord,
    RunRefusal,
    RunTimings,
    ScanCounts,
    ScanSpec,
    UndoFile,
    UndoRecord,
    VerifyPhaseRecord,
    VerifyRecord,
    Withheld,
)
from obelize.native import processes

ROOT = Path(__file__).resolve().parents[2]
VOCABULARY = ROOT / "docs" / "SCAN_VOCABULARY.md"
PACK_SPEC = ROOT / "docs" / "PACK_SPEC.md"
TEXT = VOCABULARY.read_text(encoding="utf-8")

_SECTION = re.compile(r"^## (\d+)\. ", re.MULTILINE)
_FIRST_CELL = re.compile(r"^\| `([a-z_]+)` \|", re.MULTILINE)
_HEADING_COUNT = re.compile(r"\((\d+) values\)")


def _sections() -> dict[str, tuple[str, set[str]]]:
    """Section number -> (heading line, its tables' first-column values)."""
    starts = [(m.group(1), m.start()) for m in _SECTION.finditer(TEXT)]
    out: dict[str, tuple[str, set[str]]] = {}
    for index, (number, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(TEXT)
        body = TEXT[start:end]
        out[number] = (body.splitlines()[0], set(_FIRST_CELL.findall(body)))
    return out


def _by_number(section: str) -> int:
    """Numeric sort key, named so mypy can type it."""
    return int(section)


SECTIONS = _sections()
DECLARED_OVERLAPS = SECTIONS["7"][1]

# Section 12 is closed in obelize.fsutil, where it is raised. Section 7 has no set: it is a fact
# about sections 1-5, asserted below.
DECLARED_IN_CODE: dict[str, frozenset[str]] = {
    "1": FINDING_KINDS,
    "2": CONFIDENCE_REASONS,
    "3": VERDICTS,
    "4": BAIL_CODES,
    "5": WARNING_CODES,
    "6": IMPORT_BAILS,
    "8": EDIT_STATUSES,
    "9": BINDING_KINDS,
    "10": SCAN_STATUSES,
    "11": SKIP_REASONS,
    "12": WRITE_REFUSALS,
    "13": REFUSAL_CODES,
}

# Hoisted and annotated: inside `parametrize` mypy infers `object` for `sorted`'s key.
ALL_SECTIONS: list[str] = sorted(SECTIONS, key=_by_number)
DECLARED_SECTIONS: list[str] = sorted(DECLARED_IN_CODE, key=_by_number)


def test_the_document_parses_into_the_thirteen_sections_it_claims() -> None:
    """Guards the parser: an empty parse would pass every other test vacuously."""
    assert [str(n) for n in range(1, 14)] == ALL_SECTIONS, ALL_SECTIONS
    assert set(DECLARED_IN_CODE) | {"7"} == set(SECTIONS)
    for number, (_, values) in SECTIONS.items():
        assert values, f"section {number} parsed as empty"


@pytest.mark.parametrize("section", DECLARED_SECTIONS)
def test_the_document_and_the_code_hold_the_same_members(section: str) -> None:
    heading, documented = SECTIONS[section]
    in_code = DECLARED_IN_CODE[section]
    assert documented == set(in_code), (
        f"docs/SCAN_VOCABULARY.md section {section} ({heading.strip('# ')}) and "
        f"src/obelize/models.py disagree. Only in the document: "
        f"{sorted(documented - set(in_code))}. Only in the code: "
        f"{sorted(set(in_code) - documented)}. A member is added to both, in one commit."
    )


@pytest.mark.parametrize("section", ALL_SECTIONS)
def test_a_heading_that_counts_its_members_counts_them_correctly(section: str) -> None:
    heading, values = SECTIONS[section]
    match = _HEADING_COUNT.search(heading)
    if match is None:
        return
    assert int(match.group(1)) == len(values), f"{heading}: the table has {len(values)}"


def test_only_the_declared_values_belong_to_more_than_one_set() -> None:
    """Section 7 lists the deliberate overlaps in 1-5; 8-10 are excluded by its own text."""
    named = {section: DECLARED_IN_CODE[section] for section in ("1", "2", "3", "4", "5")}
    observed: set[str] = set()
    for left, right in itertools.combinations(sorted(named), 2):
        observed |= set(named[left]) & set(named[right])
    assert observed == DECLARED_OVERLAPS, (
        "docs/SCAN_VOCABULARY.md section 7 must list exactly the values that belong to more "
        f"than one of sections 1-5. Undeclared: {sorted(observed - DECLARED_OVERLAPS)}. "
        f"Declared but no longer shared: {sorted(DECLARED_OVERLAPS - observed)}."
    )


def test_the_run_status_set_and_the_fixture_verdict_set_differ_only_as_declared() -> None:
    """Section 8: `not_a_usage` edits nothing; a hand-written key cannot predict a proposal."""
    assert {"not_a_usage"} == VERDICTS - EDIT_STATUSES
    assert {"model_proposed"} == EDIT_STATUSES - VERDICTS


def test_the_scan_status_set_and_the_fixture_verdict_set_differ_only_as_declared() -> None:
    """Section 10: a scan runs no rule, so it says `eligible` and never promises `auto`."""
    assert {"auto"} == VERDICTS - SCAN_STATUSES
    assert {"eligible"} == SCAN_STATUSES - VERDICTS
    assert SCAN_STATUSES & EDIT_STATUSES - {"auto"} == WITHHELD


def test_a_binding_kind_never_spells_a_finding_vocabulary() -> None:
    for section in ("1", "2", "3", "4", "5", "8", "10", "11"):
        assert not BINDING_KINDS & DECLARED_IN_CODE[section], section


def test_a_skip_reason_never_spells_a_finding_vocabulary() -> None:
    """A shared word would hide whether the file was read; section 12 overlaps by design."""
    for section in ("1", "2", "3", "4", "5", "6", "8", "9", "10"):
        assert not SKIP_REASONS & DECLARED_IN_CODE[section], section


def test_a_write_refusal_never_spells_a_finding_vocabulary_either() -> None:
    """Section 12 borrows section 11's path refusals (one guard, one word) and nothing else."""
    for section in ("1", "2", "3", "4", "5", "6", "8", "9", "10"):
        assert not WRITE_REFUSALS & DECLARED_IN_CODE[section], section
    assert WRITE_REFUSALS & SKIP_REASONS == PATH_REFUSALS


def test_the_import_bail_list_is_a_pinned_subset_of_the_bail_codes() -> None:
    """Pinned by name too: widening the list is the easy way to silence a failure."""
    assert IMPORT_BAILS <= BAIL_CODES, sorted(IMPORT_BAILS - BAIL_CODES)
    assert ATOMICITY_BAIL in IMPORT_BAILS
    assert {
        "roundtrip_mismatch",
        "output_does_not_parse",
        "output_names_unresolved",
        "flag_only_surface",
        "module_alias_rebound",
        "conditional_binding",
        "star_import",
        "local_import",
        "alias_collision",
        "type_symbol_unmapped",
        "from_import_unmigrated_symbol",
        "file_not_fully_migrated",
        "repo_not_fully_migrated",
        "usage_unmapped",
        "runtime_unsupported",
        "legacy_version_unsupported",
    } == IMPORT_BAILS
    assert {"import", "star_import"} == IMPORT_KINDS
    assert IMPORT_KINDS <= FINDING_KINDS


def test_the_flag_only_pattern_ids_are_the_ones_the_pack_specification_lists() -> None:
    """ADR-006 bars behaviour-driving regexes, so a pack names shapes from this closed set."""
    spec = PACK_SPEC.read_text(encoding="utf-8")
    table = spec[spec.index("| Pattern id | Matches |") :]
    documented = set()
    for line in table.splitlines()[2:]:
        if not line.startswith("|"):
            break
        documented.update(re.findall(r"^\| `([a-z_]+)` \|", line))
    assert documented == FLAG_ONLY_PATTERNS, sorted(documented ^ set(FLAG_ONLY_PATTERNS))
    # Every other pattern id reuses a `confidence_reason` for the same fact.
    assert {"sys_modules_stub"} == FLAG_ONLY_PATTERNS - CONFIDENCE_REASONS


# Value shapes shared with `obelize.packs.schema` and `ScanSpec` (PACK_SPEC hard rule 3).


class _Shapes(BaseModel):
    """Exercises each shared annotated type as a model field."""

    model_config = ConfigDict(extra="forbid")

    symbol: QualifiedName = "a.b"
    distribution: DistributionName = "a-b"
    name: PlainName = "a"
    prose: DisplayText = "A sentence."


SHAPE_CASES = [
    ("symbol", "google.generativeai.configure", None),
    ("symbol", "genai.Client(api_key=K)", "fully qualified symbol"),
    ("symbol", "google..generativeai", "fully qualified symbol"),
    ("symbol", "1generativeai", "fully qualified symbol"),
    ("distribution", "google-generativeai", None),
    ("distribution", "google.generativeai", None),
    ("distribution", "not a name", "distribution name"),
    ("distribution", "-leading-hyphen", "distribution name"),
    ("name", "genai_types", None),
    ("name", "genai.types", "single Python identifier"),
    ("name", "client; curl x | sh", "single Python identifier"),
    ("prose", "Automatic function calling differs.", None),
    ("prose", "   ", "must not be empty"),
    ("prose", "a" * (DISPLAY_TEXT_LIMIT + 1), f"at most {DISPLAY_TEXT_LIMIT} characters"),
]


@pytest.mark.parametrize(
    ("field", "value", "says"),
    SHAPE_CASES,
    ids=[f"{field}-{value[:18]}" for field, value, _ in SHAPE_CASES],
)
def test_a_shared_value_shape_accepts_and_refuses_what_pack_spec_says(
    field: str, value: str, says: str | None
) -> None:
    if says is None:
        assert getattr(_Shapes(**{field: value}), field) == value
    else:
        with pytest.raises(ValidationError, match=says):
            _Shapes(**{field: value})


REFUSED_CHARACTERS = [
    ("\x1b[2K", "Cc", "an ANSI sequence that repaints the line"),
    ("\r", "Cc", "a carriage return that overwrites what was printed"),
    ("\u202e", "Cf", "a bidirectional override that reverses the reading order"),
    ("\n", "Cc", "a newline, which turns one report row into two"),
    ("\udfff", "Cs", "a lone surrogate, which no terminal can render"),
]


@pytest.mark.parametrize(
    ("character", "category", "why"),
    REFUSED_CHARACTERS,
    ids=[c[1] + "-" + c[0].encode("unicode_escape").decode() for c in REFUSED_CHARACTERS],
)
def test_display_text_refuses_what_a_terminal_would_act_on(
    character: str, category: str, why: str
) -> None:
    """Pack text is untrusted and shown to a person, so the display itself is the attack."""
    with pytest.raises(ValidationError, match="control, format or surrogate"):
        _Shapes(prose=f"Refused.{character}Migrated.")


@pytest.mark.parametrize("character", ["\u2028", "\u2029"], ids=["Zl", "Zp"])
def test_display_text_is_one_line(character: str) -> None:
    """A tool that splits on these sees a line a person's terminal does not."""
    with pytest.raises(ValidationError, match="one line"):
        _Shapes(prose=f"One.{character}Two.")


def test_display_text_leaves_alone_the_two_categories_that_render_harmlessly() -> None:
    """`Co`/`Cn` render as a glyph; refusing them would pin a Unicode revision."""
    for character in ("\ue000", "\U000e0000"):
        assert _Shapes(prose=f"Fine {character} here.").prose.endswith("here.")


FINDING: dict[str, Any] = {
    "path": "app.py",
    "line": 7,
    "column": 0,
    "kind": "call",
    "confidence_reason": "alias_resolved",
    "symbol": "google.generativeai.configure",
    "scan_status": "eligible",
}


def finding(**overrides: Any) -> Finding:
    return Finding(**{**FINDING, **overrides})


def test_a_finding_records_where_and_what_it_found() -> None:
    found = finding(evidence="genai.configure(api_key=key)")
    assert found.sort_key == ("app.py", 7, 0, "call", "google.generativeai.configure")
    assert found.bail is None
    assert found.caused_by is None
    with pytest.raises(ValidationError, match="frozen"):
        found.line = 8  # type: ignore[misc]


def test_a_parse_error_sorts_without_a_symbol() -> None:
    broken = finding(kind="parse_error", confidence_reason="parse_error", symbol=None)
    assert broken.sort_key == ("app.py", 7, 0, "parse_error", "")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"path": ""}, "must not be empty"),
        ({"path": "src\\app.py"}, "forward slashes"),
        ({"path": "/etc/passwd"}, "must be relative"),
        ({"path": "../outside.py"}, "climb out"),
        ({"line": 0}, "greater than or equal to 1"),
        ({"column": -1}, "greater than or equal to 0"),
        ({"kind": "invented"}, "kind"),
        ({"confidence_reason": "manifest_declaration"}, "confidence_reason"),
        ({"scan_status": "auto"}, "scan_status"),
        ({"bail": "not_a_bail"}, "bail"),
    ],
)
def test_a_finding_refuses_a_value_outside_its_vocabulary(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        finding(**overrides)


def test_a_withheld_finding_must_name_the_code_that_withheld_it() -> None:
    with pytest.raises(ValidationError, match="must name a bail code"):
        finding(scan_status="needs_review")


def test_an_eligible_finding_must_not_name_one() -> None:
    with pytest.raises(ValidationError, match="not withheld"):
        finding(bail="client_source_unresolved")


def test_an_import_finding_only_carries_a_bail_about_the_import() -> None:
    with pytest.raises(ValidationError, match="which an import may not carry"):
        finding(
            kind="import",
            symbol="google.generativeai",
            scan_status="needs_review",
            bail="model_object_escapes",
        )
    withheld = finding(
        kind="import",
        symbol="google.generativeai",
        scan_status="needs_review",
        bail=ATOMICITY_BAIL,
        caused_by=("model_object_escapes",),
    )
    assert withheld.caused_by == ("model_object_escapes",)


@pytest.mark.parametrize(
    ("caused_by", "message"),
    [
        ((), "must name the ones that do"),
        (("file_not_fully_migrated",), "must not name"),
        (("model_object_escapes", "client_source_unresolved"), "sorted and de-duplicated"),
        (("model_object_escapes", "model_object_escapes"), "sorted and de-duplicated"),
    ],
)
def test_caused_by_is_the_whole_cause_set_in_a_canonical_order(
    caused_by: tuple[str, ...], message: str
) -> None:
    """Refused, not sorted: sorting on the way in would hide a nondeterministic emitter."""
    with pytest.raises(ValidationError, match=message):
        finding(scan_status="needs_review", bail=ATOMICITY_BAIL, caused_by=caused_by)


def test_only_atomicity_carries_a_cause_list() -> None:
    with pytest.raises(ValidationError, match="must not carry caused_by"):
        finding(
            scan_status="needs_review",
            bail="model_object_escapes",
            caused_by=("client_source_unresolved",),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"kind": "parse_error"}, "one fact"),
        ({"confidence_reason": "parse_error"}, "one fact"),
        ({"kind": "star_import", "symbol": "google.generativeai"}, "resolves as `star_import`"),
        ({"kind": "manifest", "symbol": "google-generativeai"}, "manifest_dependency"),
        ({"confidence_reason": "manifest_dependency"}, "manifest_dependency"),
        ({"kind": "text_mention"}, "from a string"),
        ({"confidence_reason": "string_or_comment_mention"}, "from a string"),
        ({"confidence_reason": "mock_patch_target"}, "from a string"),
    ],
)
def test_a_kind_and_its_reason_may_not_disagree(overrides: dict[str, Any], message: str) -> None:
    """Section 7 records which words do two jobs; these are the pairs that do one."""
    with pytest.raises(ValidationError, match=message):
        finding(**overrides)


def test_not_a_usage_is_only_for_something_that_is_not_an_edit() -> None:
    with pytest.raises(ValidationError, match="not for kind"):
        finding(scan_status="not_a_usage")
    assert (
        finding(
            kind="text_mention",
            confidence_reason="string_or_comment_mention",
            scan_status="not_a_usage",
        ).scan_status
        == "not_a_usage"
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"kind": "parse_error", "confidence_reason": "parse_error", "symbol": "except E, e:"},
            "names no symbol",
        ),
        ({"symbol": None}, "must name the symbol"),
        ({"symbol": '"google.generativeai.GenerativeModel"'}, "qualified name"),
        ({"symbol": "google-generativeai"}, "qualified name"),
        (
            {"kind": "manifest", "confidence_reason": "manifest_dependency", "symbol": "a b"},
            "distribution name",
        ),
    ],
)
def test_a_symbol_is_a_resolved_name_and_never_a_source_excerpt(
    overrides: dict[str, Any], message: str
) -> None:
    """ADR-008: no source in evidence, though the `encoding/python2.py` key has one as `symbol`."""
    with pytest.raises(ValidationError, match=message):
        finding(**overrides)


BINDING: dict[str, Any] = {
    "kind": "module_const",
    "name": "MODEL",
    "scope": "module",
    "ctor_line": 9,
    "use_lines": (14, 21),
    "scan_status": "eligible",
}


def binding(**overrides: Any) -> Binding:
    return Binding(**{**BINDING, **overrides})


def test_a_binding_records_its_constructor_and_every_use() -> None:
    assert binding().use_lines == (14, 21)
    assert binding(path="pkg/app.py").path == "pkg/app.py"
    attribute = binding(kind="self_attr", name="self.model", scope="class:Assistant")
    assert attribute.name == "self.model"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"kind": "group"}, "kind"),
        ({"scope": "method:run"}, "`module`, `function:<name>` or `class:<name>`"),
        ({"kind": "name", "scope": "module"}, "lives in 'function:'"),
        ({"kind": "self_attr", "name": "self.model", "scope": "module"}, "lives in 'class:'"),
        ({"kind": "self_attr", "name": "model", "scope": "class:C"}, "is named"),
        ({"name": "self.model"}, "is named"),
        ({"use_lines": (21, 14)}, "sorted and de-duplicated"),
        ({"use_lines": (14, 14)}, "sorted and de-duplicated"),
        ({"use_lines": (0,)}, "1-based"),
        ({"ctor_line": 0}, "greater than or equal to 1"),
        ({"scan_status": "needs_review", "bail": ATOMICITY_BAIL}, "never carries"),
        ({"scan_status": "needs_review"}, "must name a bail code"),
    ],
)
def test_a_binding_refuses_a_row_that_grades_nothing(
    overrides: dict[str, Any], message: str
) -> None:
    """Kind and scope are one fact; atomicity grades a file, so no binding row carries it."""
    with pytest.raises(ValidationError, match=message):
        binding(**overrides)


def test_an_applied_edit_names_the_rule_that_produced_it() -> None:
    assert Edit(path="app.py", line=5, status="auto", rule_id="rename_import").rule_id
    with pytest.raises(ValidationError, match="must name the pack rule"):
        Edit(path="app.py", line=5, status="auto")


def test_a_model_proposal_keeps_the_reason_the_rules_refused() -> None:
    """It exists only where a rule refused; dropping that bail blurs the two benchmark arms."""
    proposed = Edit(
        path="app.py", line=5, status="model_proposed", reason="client_source_unresolved"
    )
    assert proposed.reason == "client_source_unresolved"
    assert proposed.rule_id is None
    with pytest.raises(ValidationError, match="rule_id stays unset"):
        Edit(
            path="app.py",
            line=5,
            status="model_proposed",
            reason="client_source_unresolved",
            rule_id="configure_to_client",
        )
    with pytest.raises(ValidationError, match="what they refused"):
        Edit(path="app.py", line=5, status="model_proposed")


def test_an_edit_carries_its_warnings_in_a_canonical_order() -> None:
    edit = Edit(
        path="app.py",
        line=5,
        status="auto",
        rule_id="configure_to_client",
        warnings=("client_constructed_eagerly", "count_tokens_config_dropped"),
    )
    assert edit.warnings[0] == "client_constructed_eagerly"
    with pytest.raises(ValidationError, match="sorted and de-duplicated"):
        Edit(
            path="app.py",
            line=5,
            status="auto",
            rule_id="configure_to_client",
            warnings=("count_tokens_config_dropped", "client_constructed_eagerly"),
        )
    with pytest.raises(ValidationError, match="warnings"):
        Edit(path="app.py", line=5, status="auto", rule_id="r", warnings=("not_a_warning",))


def test_an_edit_that_bails_obeys_the_same_biconditional_a_finding_does() -> None:
    with pytest.raises(ValidationError, match="must name a bail code"):
        Edit(path="app.py", line=5, status="needs_review")
    with pytest.raises(ValidationError, match="must not carry"):
        Edit(path="app.py", line=5, status="auto", rule_id="r", reason="local_import")
    withheld = Edit(
        path="app.py",
        line=5,
        status="needs_review",
        reason=ATOMICITY_BAIL,
        caused_by=("client_source_unresolved", "model_object_escapes"),
    )
    assert withheld.caused_by == ("client_source_unresolved", "model_object_escapes")


SPEC: dict[str, Any] = {
    "pack_id": "gemini/google-generativeai-to-google-genai",
    "pack_version": "0.1.0",
    "pack_sha256": "a" * 64,
    "legacy_modules": ("google.generativeai",),
    "legacy_distribution": "google-generativeai",
    "new_distribution": "google-genai",
    "prefilter_tokens": ("generativeai",),
    "client_symbol": "google.generativeai.configure",
    "requires_python": ">=3.10",
    "constructor_symbols": ("google.generativeai.GenerativeModel",),
    "supported_methods": (
        ReceiverMethods(
            receiver="google.generativeai.GenerativeModel",
            methods=("count_tokens", "generate_content", "generate_content_async", "start_chat"),
        ),
    ),
}


def spec(**overrides: Any) -> ScanSpec:
    return ScanSpec(**{**SPEC, **overrides})


def test_the_scan_spec_answers_what_a_receiver_supports() -> None:
    built = spec()
    assert built.methods_for("google.generativeai.GenerativeModel")[0] == "count_tokens"
    assert built.methods_for("google.generativeai.ChatSession") == ()
    assert built.flag_only_patterns == ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"legacy_modules": ()}, "must name at least one module"),
        ({"prefilter_tokens": ()}, "every file in the repository is parsed"),
        ({"prefilter_tokens": ("",)}, "must not be empty"),
        ({"prefilter_tokens": ("généra",)}, "must be ASCII"),
        ({"prefilter_tokens": ("zz", "aa")}, "sorted and de-duplicated"),
        ({"legacy_modules": ("google-generativeai",)}, "qualified names"),
        ({"symbols": ("b", "a")}, "sorted and de-duplicated"),
        ({"legacy_distribution": "not a name"}, "distribution name"),
        ({"new_distribution": "not a name"}, "distribution name"),
        ({"client_symbol": "genai.configure()"}, "qualified name"),
        ({"pack_sha256": "abc"}, "sha256"),
        ({"flag_only_patterns": ("regex",)}, "flag_only_patterns"),
    ],
)
def test_the_scan_spec_refuses_a_projection_that_cannot_be_scanned(
    overrides: dict[str, Any], message: str
) -> None:
    """Prefilter tokens match raw bytes, hence non-empty ASCII."""
    with pytest.raises(ValidationError, match=message):
        spec(**overrides)


def test_two_entries_for_one_receiver_is_a_projection_bug() -> None:
    duplicate = ReceiverMethods(receiver="google.generativeai.ChatSession", methods=("a",))
    with pytest.raises(ValidationError, match="sorted and de-duplicated"):
        spec(supported_methods=(duplicate, duplicate))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"receiver": "not a name", "methods": ("a",)}, "qualified name"),
        ({"receiver": "pkg.Model", "methods": ()}, "supports no methods"),
        ({"receiver": "pkg.Model", "methods": ("b", "a")}, "sorted and de-duplicated"),
    ],
)
def test_a_receiver_entry_is_a_closed_sorted_set(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ReceiverMethods(**kwargs)


CHAT = ReceiverMethods(receiver="google.generativeai.ChatSession", methods=("send_message",))
START_CHAT = MethodReturn(
    method="google.generativeai.GenerativeModel.start_chat",
    receiver="google.generativeai.ChatSession",
)


def test_a_receiver_a_method_returns_is_reachable_and_one_nothing_returns_is_not() -> None:
    """`ChatSession` has no constructor: without `start_chat`'s entry its file scans clean."""
    built = spec(supported_methods=(CHAT, *SPEC["supported_methods"]), method_returns=(START_CHAT,))
    assert built.methods_for("google.generativeai.ChatSession") == ("send_message",)

    with pytest.raises(ValidationError, match="nothing in this spec can produce"):
        spec(supported_methods=(CHAT, *SPEC["supported_methods"]))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "method_returns": (
                    MethodReturn(
                        method="google.generativeai.GenerativeModel.rewind",
                        receiver="google.generativeai.ChatSession",
                    ),
                )
            },
            "not a supported method",
        ),
        (
            {
                "method_returns": (
                    MethodReturn(
                        method="google.generativeai.GenerativeModel.start_chat",
                        receiver="google.generativeai.Corpus",
                    ),
                )
            },
            "supports no methods",
        ),
        (
            {
                "method_returns": (
                    MethodReturn(
                        method="google.generativeai.GenerativeModel.start_chat",
                        receiver="google.generativeai.ChatSession",
                    ),
                    MethodReturn(
                        method="google.generativeai.GenerativeModel.count_tokens",
                        receiver="google.generativeai.ChatSession",
                    ),
                )
            },
            "sorted and de-duplicated",
        ),
    ],
    ids=["unknown-method", "receiver-with-no-methods", "unsorted"],
)
def test_the_scan_spec_refuses_a_return_that_leads_nowhere(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        spec(supported_methods=(CHAT, *SPEC["supported_methods"]), **overrides)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"method": "not a method", "receiver": "pkg.Session"}, "method must be a qualified name"),
        ({"method": "pkg.Model.open", "receiver": "not a name"}, "receiver must be a qualified"),
        ({"method": "pkg.Model.open", "receiver": "pkg.Model"}, "needs no entry"),
    ],
    ids=["method", "receiver", "self-returning"],
)
def test_a_method_return_names_two_qualified_names_that_differ(
    kwargs: dict[str, str], message: str
) -> None:
    """A method that returns its own receiver adds nothing and would loop."""
    with pytest.raises(ValidationError, match=message):
        MethodReturn(**kwargs)


def test_the_counts_are_a_summary_and_have_to_add_up() -> None:
    counts = ScanCounts(
        files_selected=3,
        files_parsed=2,
        findings=2,
        eligible=1,
        needs_review=1,
        unsupported=0,
        not_a_usage=0,
    )
    assert counts.findings == 2
    with pytest.raises(ValidationError, match="more files were parsed"):
        ScanCounts(
            files_selected=1,
            files_parsed=2,
            findings=0,
            eligible=0,
            needs_review=0,
            unsupported=0,
            not_a_usage=0,
        )
    with pytest.raises(ValidationError, match="the status split sums to"):
        ScanCounts(
            files_selected=1,
            files_parsed=1,
            findings=5,
            eligible=1,
            needs_review=0,
            unsupported=0,
            not_a_usage=0,
        )


PACK = PackRef(id="gemini/google-generativeai-to-google-genai", version="0.1.0", sha256="b" * 64)


def _document(rows: tuple[Finding, ...], **overrides: int) -> FindingsDocument:
    """Counts derive from `rows` unless overridden."""
    split = {"eligible": 0, "needs_review": 0, "unsupported": 0, "not_a_usage": 0}
    for found in rows:
        split[found.scan_status] += 1
    split.update(overrides)
    return FindingsDocument(
        obelize_version="0.1.0.dev0",
        packs=(PACK,),
        counts=ScanCounts(files_selected=1, files_parsed=1, findings=sum(split.values()), **split),
        findings=rows,
    )


def test_a_findings_document_carries_nothing_time_derived() -> None:
    """docs/CLI.md promises two `scan --json` runs are byte-identical."""
    document = _document((finding(),))
    payload = document.model_dump()
    assert set(payload) == {"obelize_version", "packs", "counts", "findings"}


def test_a_findings_document_is_written_in_document_order() -> None:
    """libcst yields references in an order that varies per process."""
    first = finding(line=7)
    second = finding(line=21, kind="method_call", confidence_reason="receiver_bound_module_const")
    assert _document((first, second)).findings[0].line == 7
    with pytest.raises(ValidationError, match="document order"):
        _document((second, first))


def test_a_findings_document_recomputes_its_own_counts() -> None:
    with pytest.raises(ValidationError, match="do not describe"):
        _document((finding(),), eligible=0, needs_review=1)


def row(**overrides: Any) -> Binding:
    """A `binding()` in `finding()`'s file, as a plan requires."""
    return binding(path="app.py", **overrides)


def test_a_plan_is_one_file_s() -> None:
    assert ImpactPlan(path="app.py", findings=(finding(),), bindings=(row(),)).path == "app.py"
    with pytest.raises(ValidationError, match="one file's"):
        ImpactPlan(path="other.py", findings=(finding(),))
    with pytest.raises(ValidationError, match="one file's"):
        ImpactPlan(path="app.py", bindings=(binding(),))


def test_a_manifest_row_does_not_belong_to_a_file_s_plan() -> None:
    """ADR-010 F-2 grades a manifest's two halves repo-wide; together they would break F-1."""
    with pytest.raises(ValidationError, match="does not belong"):
        ImpactPlan(
            path="requirements.txt",
            findings=(
                finding(
                    path="requirements.txt",
                    kind="manifest",
                    confidence_reason="manifest_dependency",
                    symbol="google-generativeai",
                ),
            ),
        )


def test_a_plan_is_written_in_document_order() -> None:
    first, second = finding(line=7), finding(line=21)
    assert ImpactPlan(path="app.py", findings=(first, second)).findings[0].line == 7
    with pytest.raises(ValidationError, match="document order"):
        ImpactPlan(path="app.py", findings=(second, first))
    with pytest.raises(ValidationError, match="constructor order"):
        ImpactPlan(path="app.py", bindings=(row(ctor_line=9), row(ctor_line=5)))


def test_an_atomic_plan_never_leaves_half_a_file_eligible() -> None:
    """ADR-010 F-1, refused at construction so no planner caller can build the shape."""
    withheld = finding(line=12, scan_status="needs_review", bail="model_object_escapes")
    stamped = finding(
        bail=ATOMICITY_BAIL, scan_status="needs_review", caused_by=("model_object_escapes",)
    )
    assert (
        ImpactPlan(path="app.py", findings=(stamped, withheld)).findings[0].bail == ATOMICITY_BAIL
    )
    with pytest.raises(ValidationError, match="eligible while"):
        ImpactPlan(path="app.py", findings=(finding(), withheld))


def pin(**overrides: Any) -> Finding:
    """One manifest row: the shape `scan/manifests.py` emits."""
    return finding(
        **{
            "path": "requirements.txt",
            "line": 1,
            "kind": "manifest",
            "confidence_reason": "manifest_dependency",
            "symbol": "google-generativeai",
            **overrides,
        }
    )


def test_a_manifest_plan_grades_declarations_and_nothing_else() -> None:
    """The mirror of `ImpactPlan`'s refusal, so a row cannot land in both."""
    assert ManifestPlan(findings=(pin(),)).findings[0].symbol == "google-generativeai"
    with pytest.raises(ValidationError, match="and nothing else"):
        ManifestPlan(findings=(finding(),))


def test_the_two_halves_of_f_2_may_sit_on_one_line() -> None:
    """`ImpactPlan` refuses this; both pins keep a partial migration installable (F-2)."""
    plan = ManifestPlan(
        findings=(
            pin(symbol="google-genai"),
            pin(scan_status="needs_review", bail=REPO_ATOMICITY_BAIL),
        ),
        blocking=("app.py",),
    )
    assert [row.scan_status for row in plan.findings] == ["eligible", "needs_review"]


def test_a_manifest_is_never_withheld_by_a_file_s_atomicity() -> None:
    """`file_not_fully_migrated` is a property of the file a finding sits in."""
    with pytest.raises(ValidationError, match="parsed source file"):
        ManifestPlan(
            findings=(
                pin(
                    scan_status="needs_review",
                    bail=ATOMICITY_BAIL,
                    caused_by=("client_source_unresolved",),
                ),
            )
        )


def test_a_manifest_plan_is_written_in_document_order() -> None:
    first, second = pin(line=1), pin(line=4)
    assert ManifestPlan(findings=(first, second)).findings[0].line == 1
    with pytest.raises(ValidationError, match="document order"):
        ManifestPlan(findings=(second, first))


def test_the_two_evidence_lists_are_sorted_and_de_duplicated() -> None:
    with pytest.raises(ValidationError, match="blocking"):
        ManifestPlan(blocking=("b.py", "a.py"))
    with pytest.raises(ValidationError, match="excluded"):
        ManifestPlan(excluded=("a.py", "a.py"))


def test_repo_atomicity_may_not_be_claimed_with_no_file_behind_it() -> None:
    """ADR-010 F-2 requires the report to name the files that still import the module."""
    with pytest.raises(ValidationError, match="none is named"):
        ManifestPlan(findings=(pin(scan_status="needs_review", bail=REPO_ATOMICITY_BAIL),))


# RunRecord's own rules; field lists vs `docs/RUN_FOLDER.md` are in test_run_folder_contract.py.


def record(**changes: object) -> RunRecord:
    """A minimal valid scan record."""
    arguments: dict[str, object] = {
        "run_id": "20260918T091407Z-3f9a1c72",
        "obelize_version": "0.1.0.dev0",
        "mode": "scan",
        "exit_code": 0,
        "python": RunPython(version="3.12.9", implementation="CPython"),
        "platform": RunPlatform(system="Linux", release="6.8.0", machine="x86_64"),
        "packs": (
            {
                "id": "gemini/google-generativeai-to-google-genai",
                "pack_version": "0.1.0",
                "sha256": "0" * 64,
                "source": "bundled",
            },
        ),
        "config": {
            "source": "defaults",
            "include": "**/*.py",
            "exclude": (),
            "max_file_bytes": 2_000_000,
        },
        "counts": RunCounts(
            files_selected=1,
            files_parsed=1,
            findings=1,
            eligible=1,
            needs_review=0,
            unsupported=0,
            not_a_usage=0,
        ),
        "timings": RunTimings(
            started_at="2026-09-18T09:14:07Z",
            finished_at="2026-09-18T09:14:08Z",
            total_ms=1000,
            scan_ms=900,
        ),
    }
    arguments.update(changes)
    return RunRecord(**arguments)


def test_the_limitation_codes_are_exactly_the_two_halves_that_are_already_closed() -> None:
    """Written out, not derived: `obelize.scan.parse` imports models. RUN_FOLDER.md says nine."""
    from obelize.scan.parse import READ_REFUSALS

    assert LIMITATION_CODES == SKIP_REASONS | READ_REFUSALS
    assert len(LIMITATION_CODES) == 9


def test_the_path_refusals_are_the_skip_reasons_one_path_can_produce() -> None:
    """The two left out are walker-only; the writer must cover every word the guard returns."""
    assert PATH_REFUSALS < SKIP_REASONS
    assert {"submodule", "unusable_name"} == SKIP_REASONS - PATH_REFUSALS
    assert PATH_REFUSALS < WRITE_REFUSALS
    assert {"file_changed_since_read"} == WRITE_REFUSALS - PATH_REFUSALS


def test_the_run_refusals_are_the_write_refusals_plus_the_one_about_the_tree() -> None:
    """Section 13 is 12 plus the tree codes, written out in models because fsutil imports it."""
    assert WRITE_REFUSALS | {"tree_dirty", "tree_unknown"} == REFUSAL_CODES
    assert len(REFUSAL_CODES) == 8


def test_the_configuration_origins_are_the_ones_the_loader_reports() -> None:
    """Declared twice for the same import-direction reason."""
    from typing import get_args

    from obelize.config import ConfigSource

    assert frozenset(get_args(ConfigSource)) == CONFIG_ORIGINS


def test_a_run_id_that_is_not_the_published_pattern_is_refused() -> None:
    """`verify --run <id>` takes one back from a script, so the shape is a contract."""
    with pytest.raises(ValidationError, match="is not a run id"):
        record(run_id="2026-09-18T09:14:07Z-3f9a1c72")


def test_a_timestamp_without_its_zone_is_refused() -> None:
    with pytest.raises(ValidationError, match="ISO 8601 UTC timestamp"):
        record(
            timings=RunTimings(
                started_at="2026-09-18 09:14:07",
                finished_at="2026-09-18T09:14:08Z",
                total_ms=1,
            )
        )


def test_a_scan_that_claims_a_warning_is_refused() -> None:
    """Warnings belong to edits, and a scan plans none."""
    counts = RunCounts(
        files_selected=1,
        files_parsed=1,
        findings=1,
        eligible=1,
        needs_review=0,
        unsupported=0,
        not_a_usage=0,
        warnings=1,
    )
    with pytest.raises(ValidationError, match="can carry no warning"):
        record(counts=counts)


def test_the_withheld_rows_follow_the_findings() -> None:
    """They duplicate part of `findings.json`, so they keep its document order."""
    rows = (
        Withheld(path="b.py", line=1, symbol="acme.sdk", bail="star_import"),
        Withheld(path="a.py", line=9, symbol="acme.sdk", bail="star_import"),
    )
    assert record(withheld=rows[::-1]).withheld == rows[::-1]
    with pytest.raises(ValidationError, match="document order"):
        record(withheld=rows)


def test_the_limitations_are_written_sorted() -> None:
    """Runs are compared byte for byte, so no array may follow set iteration order."""
    rows = (
        RunLimitation(code="unreadable", path="b.py", detail="no"),
        RunLimitation(code="unreadable", path="a.py", detail="no"),
    )
    assert record(limitations=rows[::-1]).limitations == rows[::-1]
    with pytest.raises(ValidationError, match="written sorted"):
        record(limitations=rows)


def test_a_withheld_row_obeys_the_same_caused_by_rule_a_finding_does() -> None:
    with pytest.raises(ValidationError, match="caused_by"):
        Withheld(path="a.py", line=1, bail="star_import", caused_by=("local_import",))
    with pytest.raises(ValidationError, match="caused_by"):
        Withheld(path="a.py", line=1, bail=ATOMICITY_BAIL)
    row = Withheld(path="a.py", line=1, bail=ATOMICITY_BAIL, caused_by=("local_import",))
    assert row.caused_by == ("local_import",)


def test_a_withheld_row_can_only_be_made_from_a_finding_that_was_withheld() -> None:
    """Checks the status, not the bail: `Finding` ties them, so a bail check could never fail."""
    refused = Finding(
        path="a.py",
        line=1,
        column=0,
        kind="import",
        confidence_reason="direct_import_resolved",
        symbol="acme.sdk",
        scan_status="needs_review",
        bail="star_import",
    )
    assert Withheld.of(refused) == Withheld(
        path="a.py", line=1, symbol="acme.sdk", bail="star_import"
    )
    with pytest.raises(ValueError, match="withholds nothing"):
        Withheld.of(refused.model_copy(update={"scan_status": "eligible", "bail": None}))


def test_the_exit_codes_are_the_ones_the_command_line_contract_publishes() -> None:
    table = ROOT / "docs" / "CLI.md"
    text = table.read_text(encoding="utf-8")
    block = text.split("| Code | Meaning |", 1)[1].split("\n\n", 1)[0]
    published = {int(match) for match in re.findall(r"^\| `(\d+)` \|", block, re.MULTILINE)}
    assert published == EXIT_CODES


# Plan and apply records: which mode may claim what.


def counts(**changes: object) -> RunCounts:
    """The counts a plan or an apply reports: `auto`, and never `eligible`."""
    arguments: dict[str, object] = {
        "files_selected": 1,
        "files_parsed": 1,
        "findings": 1,
        "eligible": 0,
        "auto": 1,
        "needs_review": 0,
        "unsupported": 0,
        "not_a_usage": 0,
    }
    arguments.update(changes)
    return RunCounts(**arguments)


def edit(**changes: object) -> FileEdit:
    arguments: dict[str, object] = {
        "path": "a.py",
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "hunks": 1,
        "rules": ("rename-import",),
    }
    arguments.update(changes)
    return FileEdit(**arguments)


DRY_RUN = VerifyRecord(status="not_run", reason="dry_run")
NOTHING_TO_VERIFY = VerifyRecord(status="not_run", reason="no_changes_to_verify")
PASSED = VerifyRecord(
    status="pass",
    commands=(
        CommandRecord(command="pytest -q", source="cli", status="pass", exit_code=0, duration_ms=1),
    ),
)


def fix(**changes: object) -> RunRecord:
    """A minimal valid `plan` record."""
    arguments: dict[str, object] = {
        "mode": "plan",
        "counts": counts(),
        "verify": DRY_RUN,
        "timings": RunTimings(
            started_at="2026-09-18T09:14:07Z",
            finished_at="2026-09-18T09:14:08Z",
            total_ms=1000,
            scan_ms=900,
            plan_ms=50,
        ),
    }
    arguments.update(changes)
    return record(**arguments)


def applied(**changes: object) -> RunRecord:
    """A minimal valid `apply` record that wrote one file."""
    arguments: dict[str, object] = {
        "mode": "apply",
        "file_edits": (edit(),),
        "idempotent": False,
        "verify": NOTHING_TO_VERIFY,
        "timings": RunTimings(
            started_at="2026-09-18T09:14:07Z",
            finished_at="2026-09-18T09:14:08Z",
            total_ms=1000,
            scan_ms=900,
            plan_ms=50,
            apply_ms=20,
        ),
    }
    arguments.update(changes)
    return fix(**arguments)


def test_a_command_row_that_printed_something_has_to_say_where_it_went() -> None:
    """`run.json` points at output and never carries it, so output without a path is lost."""
    noisy = CommandResult(
        command="pytest -q", source="cli", status="pass", exit_code=0, duration_ms=1, output="ok\n"
    )
    with pytest.raises(ValueError, match="printed something"):
        CommandRecord.of(noisy, log=None, junit=None)
    row = CommandRecord.of(noisy, log="verify/after/1.log", junit=None)
    assert row.log == "verify/after/1.log"
    assert not hasattr(row, "output")
    quiet = noisy.model_copy(update={"output": ""})
    assert CommandRecord.of(quiet, log=None, junit=None).log is None


def test_a_recorded_command_stays_valid_on_a_system_that_would_read_it_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only configuration asks; a run folder written on POSIX must load on Windows."""
    monkeypatch.setattr(processes, "command_problem", lambda text: f"{text!r} reads otherwise")
    result = CommandResult(
        command="pytest tests\\unit", source="cli", status="pass", exit_code=0, duration_ms=1
    )
    assert CommandRecord.of(result, log=None, junit=None).command == "pytest tests\\unit"


def test_a_file_edit_is_a_file_whose_bytes_changed_and_a_rule_that_changed_them() -> None:
    """Equal hashes would make `idempotent` unreadable; no rule leaves a hunk untraceable."""
    with pytest.raises(ValidationError, match="bytes did not change"):
        edit(after_sha256="a" * 64)
    with pytest.raises(ValidationError, match="rewritten by nothing"):
        edit(rules=())
    with pytest.raises(ValidationError, match="rules"):
        edit(rules=("b-rule", "a-rule"))


def test_the_plan_is_written_in_the_order_two_runs_can_be_compared_in() -> None:
    """`plan.json` has no timestamps, so order alone could make two runs differ."""
    document: dict[str, object] = {
        "obelize_version": "0.1.0.dev0",
        "packs": (PackRef(id="p/a-to-b", version="0.1.0", sha256="0" * 64),),
    }
    with pytest.raises(ValidationError, match="path order"):
        PlanDocument(**document, files=(edit(path="z.py"), edit(path="a.py")))
    with pytest.raises(ValidationError, match="two rows for one path"):
        PlanDocument(**document, files=(edit(), edit(after_sha256="c" * 64)))
    rows = (
        Edit(path="a.py", line=9, status="auto", rule_id="rename-import"),
        Edit(path="a.py", line=2, status="auto", rule_id="rename-import"),
    )
    with pytest.raises(ValidationError, match="document order"):
        PlanDocument(**document, edits=rows)
    assert PlanDocument(**document, edits=rows[::-1]).edits == rows[::-1]


def test_the_counts_of_a_run_that_applied_the_rules_add_up() -> None:
    """Sums five statuses, not four; `eligible` and `auto` together would grade the repo twice."""
    with pytest.raises(ValidationError, match="more files were parsed"):
        counts(files_selected=1, files_parsed=2)
    with pytest.raises(ValidationError, match="status split sums to"):
        counts(findings=2)
    with pytest.raises(ValidationError, match="and never both"):
        counts(findings=2, eligible=1, auto=1)


@pytest.mark.parametrize("code", ["tree_dirty", "tree_unknown"])
def test_the_refusals_about_the_repository_name_no_path(code: RefusalCode) -> None:
    """Tree codes refuse the whole tree; every other code refuses one named file."""
    with pytest.raises(ValidationError, match="name no path"):
        RunRefusal(code=code, path="a.py", detail="no")
    with pytest.raises(ValidationError, match="name no path"):
        RunRefusal(code="symlink", detail="no")
    assert RunRefusal(code=code, detail="3 paths").path is None


def test_the_written_files_and_the_refusals_are_written_in_a_stable_order() -> None:
    with pytest.raises(ValidationError, match="file_edits is written in path order"):
        applied(file_edits=(edit(path="z.py"), edit(path="a.py")), idempotent=False)
    with pytest.raises(ValidationError, match="two rows for one path"):
        applied(file_edits=(edit(), edit(after_sha256="c" * 64)), idempotent=False)
    rows = (
        RunRefusal(code="symlink", path="z.py", detail="no"),
        RunRefusal(code="symlink", path="a.py", detail="no"),
    )
    with pytest.raises(ValidationError, match="refusals are written sorted"):
        applied(refused=rows)
    assert applied(refused=rows[::-1]).refused == rows[::-1]


def test_a_run_reports_the_split_its_mode_is_entitled_to() -> None:
    """`eligible`: nothing withheld it. `auto`: a rule rewrote it, which a scan never does."""
    with pytest.raises(ValidationError, match="has run the rules"):
        fix(counts=counts(eligible=1, auto=0))
    with pytest.raises(ValidationError, match="no `auto` row"):
        record(
            counts=RunCounts(
                files_selected=1,
                files_parsed=1,
                findings=1,
                eligible=0,
                auto=1,
                needs_review=0,
                unsupported=0,
                not_a_usage=0,
            )
        )


def test_a_scan_records_nothing_about_a_disk_it_did_not_write_to() -> None:
    with pytest.raises(ValidationError, match="a scan writes no file"):
        record(file_edits=(edit(),))
    with pytest.raises(ValidationError, match="a scan writes no file"):
        record(refused=(RunRefusal(code="tree_dirty", detail="1 path"),))
    with pytest.raises(ValidationError, match="a scan writes no file"):
        record(idempotent=True)
    with pytest.raises(ValidationError, match="no verification phase"):
        record(verify=DRY_RUN)


def test_a_plan_or_an_apply_always_records_a_verification() -> None:
    """`docs/CLI.md` gives both no-verdict cases a status and a reason, never a missing field."""
    with pytest.raises(ValidationError, match="always records a verification"):
        fix(verify=None, timings=fix().timings)


def test_a_plan_writes_nothing_and_has_nothing_to_verify() -> None:
    """A plan's verdict is always `not_run` with reason `dry_run`."""
    with pytest.raises(ValidationError, match="a plan writes nothing"):
        fix(file_edits=(edit(),))
    with pytest.raises(ValidationError, match="a plan writes nothing"):
        fix(refused=(RunRefusal(code="tree_dirty", detail="1 path"),))
    with pytest.raises(ValidationError, match="a plan writes nothing"):
        fix(idempotent=True)
    with pytest.raises(ValidationError, match="nothing to verify"):
        fix(verify=NOTHING_TO_VERIFY)


def test_an_apply_says_whether_it_changed_anything_and_cannot_be_wrong_about_it() -> None:
    """`idempotent` means exactly "`file_edits` is empty"; it says nothing beyond the bytes."""
    with pytest.raises(ValidationError, match="says whether it changed anything"):
        applied(idempotent=None)
    with pytest.raises(ValidationError, match="records what happened to the bytes"):
        applied(idempotent=True)
    quiet = applied(file_edits=(), idempotent=True, counts=counts(findings=0, auto=0))
    assert quiet.idempotent is True


def test_a_phase_that_did_not_run_has_no_duration() -> None:
    clock: dict[str, object] = {
        "started_at": "2026-09-18T09:14:07Z",
        "finished_at": "2026-09-18T09:14:08Z",
        "total_ms": 1000,
        "scan_ms": 900,
    }
    with pytest.raises(ValidationError, match="plan_ms"):
        fix(timings=RunTimings(**clock))
    with pytest.raises(ValidationError, match="apply_ms"):
        fix(timings=RunTimings(**clock, plan_ms=1, apply_ms=1))
    with pytest.raises(ValidationError, match="verify_ms"):
        fix(timings=RunTimings(**clock, plan_ms=1, verify_ms=1))
    ran = applied(
        verify=PASSED,
        timings=RunTimings(**clock, plan_ms=1, apply_ms=1, verify_ms=1),
    )
    assert ran.timings.verify_ms == 1
    # Nothing was written to verify, but the tests before the refused write ran.
    refused = VerifyRecord(
        status="not_run",
        reason="no_changes_to_verify",
        baseline=VerifyPhaseRecord(status="pass", commands=PASSED.commands),
    )
    with pytest.raises(ValidationError, match="verify_ms"):
        applied(verify=refused, timings=RunTimings(**clock, plan_ms=1, apply_ms=1))
    kept = applied(verify=refused, timings=ran.timings)
    assert kept.timings.verify_ms == 1


# undo.json: the one run-folder document a later command writes; its rules are ADR-011 D4.

UNDONE: dict[str, object] = {
    "run_id": "20260918T091407Z-3f9a1c72",
    "obelize_version": "0.1.0",
    "undone_at": "2026-09-18T09:14:07Z",
}


def undone(path: str = "app.py", **overrides: object) -> UndoFile:
    row: dict[str, object] = {
        "path": path,
        "outcome": "reverted",
        "recorded_sha256": "a" * 64,
        "current_sha256": "a" * 64,
        "snapshot": "snapshots/before/" + "b" * 64,
    }
    return UndoFile(**{**row, **overrides})


def test_a_skip_says_why_and_a_revert_has_nothing_to_say() -> None:
    with pytest.raises(ValidationError, match="a revert has nothing to say"):
        undone(reason="hash_mismatch")
    with pytest.raises(ValidationError, match="a skip says"):
        undone(outcome="skipped")
    assert undone(outcome="skipped", reason="missing", current_sha256=None).reason == "missing"


def test_hash_mismatch_is_exactly_the_case_where_the_two_hashes_differ() -> None:
    """The code names a comparison, so a row carrying it has to have made one."""
    for current in (None, "a" * 64):
        with pytest.raises(ValidationError, match="exactly the case where the two differ"):
            undone(outcome="skipped", reason="hash_mismatch", current_sha256=current)
    row = undone(outcome="skipped", reason="hash_mismatch", current_sha256="c" * 64)
    assert row.current_sha256 == "c" * 64


def test_bytes_that_are_neither_the_run_s_nor_unreadable_have_only_one_word() -> None:
    with pytest.raises(ValidationError, match="the only word for that is"):
        undone(outcome="skipped", reason="symlink", current_sha256="c" * 64)
    with pytest.raises(ValidationError, match="what it held first is not recorded"):
        undone(current_sha256=None)
    assert undone(outcome="skipped", reason="symlink", current_sha256=None).current_sha256 is None


def test_the_files_are_written_in_the_order_the_run_wrote_them() -> None:
    with pytest.raises(ValidationError, match="path order"):
        UndoRecord(**UNDONE, exit_code=0, files=(undone("z.py"), undone("a.py")))
    with pytest.raises(ValidationError, match="two rows for one path"):
        UndoRecord(**UNDONE, exit_code=0, files=(undone(), undone()))


def test_the_exit_code_is_derived_from_the_rows_and_not_reported_beside_them() -> None:
    """`0` only if every file was reverted; `4` otherwise, including a run that wrote none."""
    both = (undone("a.py"), undone("z.py"))
    assert UndoRecord(**UNDONE, exit_code=0, files=both).exit_code == 0
    with pytest.raises(ValidationError, match="is every file reverted and `4` is anything else"):
        UndoRecord(**UNDONE, exit_code=4, files=both)
    partial = (
        undone("a.py"),
        undone("z.py", outcome="skipped", reason="hash_mismatch", current_sha256="c" * 64),
    )
    with pytest.raises(ValidationError, match="is every file reverted and `4` is anything else"):
        UndoRecord(**UNDONE, exit_code=0, files=partial)
    assert UndoRecord(**UNDONE, exit_code=4, files=partial).exit_code == 4
    with pytest.raises(ValidationError, match="is every file reverted and `4` is anything else"):
        UndoRecord(**UNDONE, exit_code=0)
    assert UndoRecord(**UNDONE, exit_code=4).files == ()


# The run's `model` summary and the two `model/` documents (ADR-039): their rules, not fields.

A_MODEL: dict[str, object] = {
    "provider": "openai_compat",
    "host": "localhost",
    "model": "qwen2.5-coder",
    "proposals": 1,
    "accepted": 0,
    "tokens_in": 10,
    "tokens_out": 2,
}

CONSULTED = RunTimings(
    started_at="2026-09-18T09:14:07Z",
    finished_at="2026-09-18T09:14:08Z",
    total_ms=1000,
    scan_ms=900,
    plan_ms=50,
    model_ms=400,
)


def proposed(**changes: object) -> ProposalRecord:
    """One consultation that produced nothing."""
    arguments: dict[str, object] = {
        "index": 1,
        "path": "a.py",
        "line": 5,
        "bail": "client_source_unresolved",
        "context_start_line": 1,
        "context_end_line": 9,
        "prompt_sha256": "a" * 64,
        "provider": "openai_compat",
        "model": "qwen2.5-coder",
        "outcome": "nothing_proposed",
    }
    arguments.update(changes)
    return ProposalRecord(**arguments)


A_PROPOSAL = EditProposal(
    path="a.py", start_line=5, end_line=5, symbol="x.Y", replacement="pass", rationale="because"
)


def test_a_scan_records_no_model_because_it_consults_nobody() -> None:
    """A scan plans no edit to propose; only a `plan` or an `apply` may carry `model`."""
    with pytest.raises(ValidationError, match="nothing to consult one about"):
        record(model=A_MODEL, timings=CONSULTED)
    assert fix(model=A_MODEL, timings=CONSULTED).model is not None


def test_a_proposal_is_accepted_by_being_written() -> None:
    """A dry run writes nothing, so it cannot have accepted one."""
    with pytest.raises(ValidationError, match="accepted proposal"):
        fix(model={**A_MODEL, "accepted": 1}, timings=CONSULTED)


def test_the_model_clock_is_present_exactly_when_a_model_is() -> None:
    with pytest.raises(ValidationError, match="model_ms"):
        fix(model=A_MODEL)
    with pytest.raises(ValidationError, match="model_ms"):
        fix(timings=CONSULTED)


def test_a_file_edit_names_a_rule_or_a_proposal_and_never_both() -> None:
    """Neither leaves a hunk untraceable; both would mean two writers rewrote one file."""
    assert edit(rules=(), proposals=(2,)).proposals == (2,)
    with pytest.raises(ValidationError, match="trace to anything"):
        edit(rules=())
    with pytest.raises(ValidationError, match="both a pack rule and a model proposal"):
        edit(proposals=(2,))
    with pytest.raises(ValidationError, match="numbered from 1"):
        edit(rules=(), proposals=(0,))
    with pytest.raises(ValidationError, match="sorted and de-duplicated"):
        edit(rules=(), proposals=(2, 1))


def test_the_written_files_and_the_model_count_the_same_writes() -> None:
    written = edit(rules=(), proposals=(1,))
    assert (
        applied(
            file_edits=(written,),
            model={**A_MODEL, "accepted": 1},
            timings=RunTimings(**{**dict(CONSULTED), "apply_ms": 20}),
        ).model
        is not None
    )
    with pytest.raises(ValidationError, match="count the same writes"):
        applied(
            file_edits=(written,),
            model=A_MODEL,
            timings=RunTimings(**{**dict(CONSULTED), "apply_ms": 20}),
        )


def test_a_run_model_never_says_none_and_never_writes_more_than_it_was_told() -> None:
    with pytest.raises(ValidationError, match="records no model object at all"):
        RunModel(**{**A_MODEL, "provider": "none"})
    with pytest.raises(ValidationError, match="more edits than answers"):
        RunModel(**{**A_MODEL, "accepted": 2})


def test_a_proposal_record_carries_the_word_its_outcome_implies() -> None:
    assert proposed().failure is None
    with pytest.raises(ValidationError, match="exactly the outcome that carries"):
        proposed(failure="endpoint_refused")
    with pytest.raises(ValidationError, match="exactly the outcome that carries"):
        proposed(outcome="unanswered")
    with pytest.raises(ValidationError, match="not refused for a reason"):
        proposed(refusal="path_outside_root")
    with pytest.raises(ValidationError, match="needs a proposal"):
        proposed(outcome="written")
    with pytest.raises(ValidationError, match="should not"):
        proposed(proposal=A_PROPOSAL)
    assert proposed(outcome="written", proposal=A_PROPOSAL).proposal is not None
    with pytest.raises(ValidationError, match="no range at all"):
        proposed(context_start_line=9, context_end_line=1)


def test_the_model_index_counts_what_it_points_at() -> None:
    summary = RunModel(**A_MODEL)
    assert ModelDocument(obelize_version="0", summary=summary, consulted=1).skipped == ()
    with pytest.raises(ValidationError, match="answered at most once"):
        ModelDocument(obelize_version="0", summary=summary, consulted=0)
    rows = (
        ConsultationSkip(path="z.py", line=1, reason="atomicity_only"),
        ConsultationSkip(path="a.py", line=1, reason="pack_refused"),
    )
    with pytest.raises(ValidationError, match="document order"):
        ModelDocument(obelize_version="0", summary=summary, consulted=1, skipped=rows)


def test_the_proposal_outcomes_split_into_the_two_groups_the_order_has() -> None:
    """Three outcomes describe the answer and five the run."""
    assert len(PROPOSAL_OUTCOMES) == 8
    assert PROPOSAL_HELD < PROPOSAL_OUTCOMES
    answered = {"guard_refused", "nothing_proposed", "unanswered"}
    assert answered == PROPOSAL_OUTCOMES - PROPOSAL_HELD


def test_a_module_a_distribution_provides_is_a_dotted_name() -> None:
    with pytest.raises(ValidationError, match="dotted name"):
        ProvidedModule(module="acme wire", distribution="acme-wire")


# Python identifiers are Unicode: an ASCII-only check on a name from source crashes the scan.


@pytest.mark.parametrize(
    ("kind", "name", "scope"),
    [
        ("module_const", "modèle", "module"),
        ("name", "model", "function:üret"),
        ("self_attr", "self.modèl", "class:Übersetzer"),
    ],
    ids=["a module constant", "a function", "an attribute and a class"],
)
def test_a_binding_may_be_named_as_python_names_it(kind: str, name: str, scope: str) -> None:
    binding = Binding(
        kind=kind, name=name, scope=scope, ctor_line=1, use_lines=(2,), scan_status="eligible"
    )
    assert binding.name == name


def test_a_symbol_read_through_the_legacy_alias_may_be_named_as_python_names_it() -> None:
    finding = Finding(
        path="app.py",
        line=1,
        column=0,
        kind="attribute",
        confidence_reason="alias_resolved",
        symbol="google.generativeai.módel",
        scan_status="eligible",
    )
    assert finding.symbol == "google.generativeai.módel"


@pytest.mark.parametrize(
    ("kind", "name", "scope"),
    [
        ("module_const", "mo dèle", "module"),
        ("name", "model", "function:ü ret"),
        ("self_attr", "modèl", "class:A"),
        ("name", "1model", "function:f"),
        ("name", "model", "function:outer.inner"),
    ],
    ids=[
        "a space",
        "a space in the scope",
        "an attribute with no receiver",
        "a digit first",
        "a dotted scope",
    ],
)
def test_what_python_would_not_name_is_still_refused(kind: str, name: str, scope: str) -> None:
    with pytest.raises(ValidationError):
        Binding(
            kind=kind, name=name, scope=scope, ctor_line=1, use_lines=(2,), scan_status="eligible"
        )
