"""What a scan finds and a plan decides: findings, bindings, edits, the pack's scan spec and
the findings document."""

from __future__ import annotations

import re
from typing import Annotated

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, StrictInt, field_validator, model_validator

from obelize.models.fields import (
    _DISTRIBUTION_NAME,
    QUALIFIED_NAME,
    PlainName,
    PrefilterToken,
    RelativePath,
    Sha256,
    _check_caused_by,
    _Frozen,
    sorted_unique,
)
from obelize.models.vocabulary import (
    ATOMICITY_BAIL,
    CALL_MATCHES,
    IMPORT_BAILS,
    IMPORT_KINDS,
    REPO_ATOMICITY_BAIL,
    SCAN_STATUSES,
    WITHHELD,
    BailCode,
    BindingKind,
    ConfidenceReason,
    EditStatus,
    FindingKind,
    FlagOnlyPattern,
    ScanStatus,
    WarningCode,
)

# Always lone in a `str`: JSON's `\ud800` escape makes one and UTF-8 cannot write it.
_SURROGATE = re.compile("[\ud800-\udfff]")


def _identifier(value: str, segments: int | None = None) -> bool:
    """Whether `value` is a dotted name Python accepts, in `segments` parts if given.

    Unicode on purpose (PEP 3131): source may say `modèle`. Pack names use `QUALIFIED_NAME`.
    """
    parts = value.split(".")
    counted = segments is None or len(parts) == segments
    return counted and all(part.isidentifier() for part in parts)


def _check_withheld(status: str, reason: str | None, field: str) -> None:
    """Withheld iff a reason is named, both ways; `model_proposed` may keep one anyway."""
    if status in WITHHELD:
        if reason is None:
            raise ValueError(f"status={status!r} withholds the edit, so it must name a bail code")
    elif reason is not None and status != "model_proposed":
        raise ValueError(
            f"status={status!r} is not withheld, so it must not carry {field}={reason!r}"
        )


class Finding(_Frozen):
    """One legacy usage the scanner resolved, or one file it could not read."""

    path: RelativePath
    line: int = Field(ge=1)
    column: int = Field(ge=0)
    kind: FindingKind
    confidence_reason: ConfidenceReason
    symbol: str | None = None
    # What a pack flags a call for (`CallMatch`), else null: source excerpts are kept out of it.
    evidence: str | None = None
    # Scan-time only, no verdict or warning yet: `eligible` is necessary for `auto`, not enough.
    scan_status: ScanStatus
    bail: BailCode | None = None
    caused_by: tuple[BailCode, ...] | None = None

    @property
    def sort_key(self) -> tuple[str, int, int, str, str]:
        """Document order, defined once; libcst's reference sets vary per process, so sort by it."""
        return (self.path, self.line, self.column, self.kind, self.symbol or "")

    @model_validator(mode="after")
    def _check(self) -> Finding:
        _check_withheld(self.scan_status, self.bail, "bail")
        _check_caused_by(self.bail, self.caused_by, "bail")

        if self.kind in IMPORT_KINDS and self.bail is not None and self.bail not in IMPORT_BAILS:
            raise ValueError(
                f"{self.path}:{self.line} is an import finding carrying bail {self.bail!r}, which "
                f"an import may not carry. If the import itself resolved, the code is "
                f"{ATOMICITY_BAIL!r} with caused_by=[{self.bail!r}]"
            )

        # An unparsable file yields exactly one finding, so kind and reason coincide.
        if (self.kind == "parse_error") != (self.confidence_reason == "parse_error"):
            raise ValueError("kind and confidence_reason `parse_error` are one fact; use both")
        if self.kind == "star_import" and self.confidence_reason != "star_import":
            raise ValueError("a star import statement resolves as `star_import`")
        if (self.kind == "manifest") != (self.confidence_reason == "manifest_dependency"):
            raise ValueError(
                "`manifest_dependency` is the reason of a `manifest` finding, and only"
            )
        mention = self.confidence_reason in {"string_or_comment_mention", "mock_patch_target"}
        if (self.kind == "text_mention") != mention:
            raise ValueError("a `text_mention` is resolved from a string, and a string only")
        if self.scan_status == "not_a_usage" and self.kind not in {"text_mention", "manifest"}:
            raise ValueError(
                f"`not_a_usage` is for something that is not an edit (a prose mention, or a "
                f"manifest line that disagrees with the code), not for kind {self.kind!r}"
            )
        self._check_evidence()
        self._check_symbol()
        return self

    def _check_evidence(self) -> None:
        if self.evidence is None:
            return
        word, _, detail = self.evidence.partition(" ")
        fits = {"spread": detail == "", "position": detail.isdecimal()}
        if word not in CALL_MATCHES or not fits.get(word, detail.isidentifier()):
            raise ValueError(
                f"evidence is one of {sorted(CALL_MATCHES)} and the name or index it takes, "
                f"never a source excerpt; got {self.evidence!r}"
            )

    def _check_symbol(self) -> None:
        if self.kind == "parse_error":
            # No source excerpt in evidence: only the fixture ground truth names a line.
            if self.symbol is not None:
                raise ValueError(
                    "a parse_error finding names no symbol; it is not a resolved usage"
                )
            return
        if self.symbol is None:
            raise ValueError(f"a {self.kind!r} finding must name the symbol it resolved")
        named = (
            _DISTRIBUTION_NAME.fullmatch(self.symbol) is not None
            if self.kind == "manifest"
            else _identifier(self.symbol)
        )
        if not named:
            raise ValueError(
                f"symbol {self.symbol!r} is not a "
                f"{'distribution name' if self.kind == 'manifest' else 'qualified name'}. A quoted "
                f"mock target is recorded unquoted, and a source excerpt is never a symbol"
            )


class Binding(_Frozen):
    """A name bound to a legacy object, and every place it is used.

    Kinds are a closed table. A group is atomic: if one reference escapes, all are
    withheld, because a half-rewritten group breaks working code.
    """

    kind: BindingKind
    name: str
    scope: str
    path: RelativePath | None = None
    ctor_line: int = Field(ge=1)
    use_lines: tuple[int, ...] = ()
    scan_status: ScanStatus
    bail: BailCode | None = None

    @model_validator(mode="after")
    def _check(self) -> Binding:
        _check_withheld(self.scan_status, self.bail, "bail")
        if self.bail == ATOMICITY_BAIL:
            # Atomicity belongs to a file, and not every fixture gives a binding row a path.
            raise ValueError(f"a binding never carries {ATOMICITY_BAIL!r}")
        kind, _, owner = self.scope.partition(":")
        if self.scope != "module" and not (kind in {"function", "class"} and _identifier(owner, 1)):
            raise ValueError(
                f"scope is `module`, `function:<name>` or `class:<name>`: {self.scope!r}"
            )
        expected = {
            "name": "function:",
            "module_const": "module",
            "self_attr": "class:",
            "class_attr": "class:",
        }[self.kind]
        if not self.scope.startswith(expected):
            raise ValueError(
                f"a {self.kind!r} binding lives in {expected!r}, not in {self.scope!r}"
            )
        segments = 2 if self.kind == "self_attr" else 1
        if not _identifier(self.name, segments):
            raise ValueError(
                f"a {self.kind!r} binding is named by {segments} identifier(s), got {self.name!r}"
            )
        if list(self.use_lines) != sorted(set(self.use_lines)):
            raise ValueError(
                f"use_lines must be sorted and de-duplicated, got {list(self.use_lines)}"
            )
        if any(line < 1 for line in self.use_lines):
            raise ValueError(f"use_lines are 1-based, got {list(self.use_lines)}")
        return self


class Edit(_Frozen):
    """What a rule did with a finding, or why it refused to."""

    path: RelativePath
    line: int = Field(ge=1)
    # Deliberately not the fixture `verdict`: `not_a_usage` is never an edit, and
    # `model_proposed` cannot be graded by a hand-written answer key.
    status: EditStatus
    rule_id: str | None = None
    reason: BailCode | None = None
    caused_by: tuple[BailCode, ...] | None = None
    warnings: tuple[WarningCode, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Edit:
        _check_withheld(self.status, self.reason, "reason")
        _check_caused_by(self.reason, self.caused_by, "reason")
        if self.status == "auto" and self.rule_id is None:
            # Every applied hunk must trace to a pack rule via run.json's `file_edits[].rules`.
            raise ValueError("an applied edit must name the pack rule that produced it")
        if self.status == "model_proposed":
            if self.rule_id is not None:
                raise ValueError(
                    "a model proposal is not produced by a pack rule; rule_id stays unset"
                )
            if self.reason is None:
                raise ValueError(
                    "a model proposal exists only where the deterministic rules refused, and the "
                    "report has to say what they refused"
                )
        sorted_unique(self.warnings, "warnings")
        return self


class EditProposal(_Frozen):
    """A model's proposed edit, held exactly as it came back."""

    # Plain `str` fields on purpose: a hostile path must be constructible so the
    # guard can refuse it by name. Failing even these checks makes it unanswered, not refused.
    path: str
    # 1-based, inclusive; the guard checks it against the range sent as context.
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    # The legacy symbol it claims to migrate; the guard checks it is at that line.
    symbol: str
    # The range's old text as the model read it; the guard compares it with what was sent.
    replaces: str
    # The range's new text: newline-separated, no trailing newline.
    replacement: str
    # For the report; it never reaches the tree.
    rationale: str
    # Import statements the replacement needs, which obelize adds at module level: a name the new
    # release spells another way is imported where the file imports the rest, not inside a class.
    imports: tuple[str, ...] = Field(default=(), max_length=4)

    @field_validator("imports", mode="before")
    @classmethod
    def _none_is_none(cls, value: object) -> object:
        """A reply that says `null` for what it has none of means the same as one that is silent."""
        return () if value is None else value

    @model_validator(mode="after")
    def _check(self) -> EditProposal:
        if self.end_line < self.start_line:
            raise ValueError(
                f"a proposal replaces lines {self.start_line}..{self.end_line}, which is "
                f"no range at all"
            )
        for field, value in (
            ("path", self.path),
            ("symbol", self.symbol),
            ("rationale", self.rationale),
        ):
            if not value.strip():
                raise ValueError(f"{field} is empty, so the proposal names nothing")
        for field, value in (
            ("path", self.path),
            ("symbol", self.symbol),
            ("replaces", self.replaces),
            ("replacement", self.replacement),
            ("rationale", self.rationale),
            *(("imports", entry) for entry in self.imports),
        ):
            if _SURROGATE.search(value):
                raise ValueError(
                    f"{field} holds a lone surrogate, which no file or report can hold"
                )
        return self


class ReceiverMethods(_Frozen):
    """The methods a legacy receiver supports, by the symbol that constructs it."""

    receiver: str
    methods: tuple[str, ...]

    @model_validator(mode="after")
    def _check(self) -> ReceiverMethods:
        if not QUALIFIED_NAME.fullmatch(self.receiver):
            raise ValueError(f"receiver must be a qualified name, got {self.receiver!r}")
        if not self.methods:
            raise ValueError(f"{self.receiver} supports no methods; drop the entry instead")
        sorted_unique(self.methods, "methods")
        return self


class MethodReturn(_Frozen):
    """A supported method, and the legacy receiver its result is.

    Without it `chat.send_message(...)` resolves to nothing: `ChatSession` has no constructor,
    only `GenerativeModel.start_chat(...)`.
    """

    method: str
    receiver: str

    @model_validator(mode="after")
    def _check(self) -> MethodReturn:
        for field, value in (("method", self.method), ("receiver", self.receiver)):
            if not QUALIFIED_NAME.fullmatch(value):
                raise ValueError(f"{field} must be a qualified name, got {value!r}")
        if self.method.rpartition(".")[0] == self.receiver:
            raise ValueError(
                f"{self.method} would produce the receiver it is called on; a method that "
                f"returns its own receiver needs no entry"
            )
        return self


class MemberClass(_Frozen):
    """A class whose members a pack renames: they are renamed on its instances, and on those of
    every class that derives from it."""

    class_symbol: str
    members: tuple[str, ...]

    @model_validator(mode="after")
    def _check(self) -> MemberClass:
        if not QUALIFIED_NAME.fullmatch(self.class_symbol):
            raise ValueError(f"class_symbol must be a qualified name, got {self.class_symbol!r}")
        if not self.members:
            raise ValueError(f"{self.class_symbol} has no member to rename; drop the entry instead")
        sorted_unique(self.members, "members")
        bad = [name for name in self.members if not name.isidentifier()]
        if bad:
            raise ValueError(f"members takes plain names, got {bad}")
        return self


class ProvidedModule(_Frozen):
    """A module the legacy distribution installed and the new one does not.

    Importing one relies on an undeclared dependency that leaves with the legacy pin.
    """

    module: str
    distribution: str

    @model_validator(mode="after")
    def _check(self) -> ProvidedModule:
        if not QUALIFIED_NAME.fullmatch(self.module):
            raise ValueError(f"module must be a dotted name, got {self.module!r}")
        return self


# `==` bounds both sides; `!=` bounds neither.
_LOWER_BOUND_OPERATORS = (">=", ">", "==", "~=")
_UPPER_BOUND_OPERATORS = ("<=", "<", "==")


def bounds(specifiers: SpecifierSet) -> tuple[Version | None, Version | None]:
    """The floor and the ceiling a specifier set names, where it names one."""
    lowers: list[Version] = []
    uppers: list[Version] = []
    for specifier in specifiers:
        # `==1.*` has a floor and no ceiling a `Version` can name.
        wildcard = specifier.version.endswith(".*")
        try:
            version = Version(specifier.version.removesuffix(".*"))
        except InvalidVersion:  # `===foo` names no version
            continue
        if specifier.operator in _LOWER_BOUND_OPERATORS:
            lowers.append(version)
        if specifier.operator in _UPPER_BOUND_OPERATORS and not wildcard:
            uppers.append(version)
    return (max(lowers) if lowers else None, min(uppers) if uppers else None)


class CallShape(_Frozen):
    """The calls of a flagged symbol that the flag is about; any other call is the API as it was.

    A call is one if it passes a keyword of `keywords`, has more positional arguments than
    `positional_from`, leaves out a name of `omits` (given by keyword, or by position at its index;
    null for a name only a keyword can give), or has a `*` or `**` argument, which can pass
    anything.
    """

    keywords: tuple[PlainName, ...] = ()
    positional_from: StrictInt | None = Field(default=None, ge=0)
    omits: dict[PlainName, Annotated[StrictInt, Field(ge=0)] | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> CallShape:
        if not (self.keywords or self.omits or self.positional_from is not None):
            raise ValueError("a call shape names a keyword, a position or a name a call must pass")
        sorted_unique(self.keywords, "keywords")
        sorted_unique(tuple(self.omits), "omits")
        return self


class ScanSpec(_Frozen):
    """Everything the scanner needs from a pack, and nothing it must not have.

    `scan/*` and `impact/*` never import `packs.schema`; `packs/loader.py` builds this with
    `to_scan_spec()`, keeping rewrite data out of the scanner.
    """

    pack_id: str
    pack_version: str
    pack_sha256: Sha256
    legacy_modules: tuple[str, ...]
    # Empty for a side that is the Python itself (ADR-071): it has no pin to read or to edit.
    legacy_distribution: str
    new_distribution: str
    prefilter_tokens: tuple[PrefilterToken, ...]
    symbols: tuple[str, ...] = ()
    # The legacy call that configures the module; `None` for a library with no client.
    client_symbol: str | None = None
    # The class the new SDK's client is built from: a receiver only ever assigned one is not legacy.
    new_client_symbol: str | None = None
    constructor_symbols: tuple[str, ...] = ()
    supported_methods: tuple[ReceiverMethods, ...] = ()
    method_returns: tuple[MethodReturn, ...] = ()
    # Unlike `supported_methods`, a receiver here is no object the new SDK replaces: its members
    # are renamed where it is seen, whatever else is done with it.
    member_classes: tuple[MemberClass, ...] = ()
    removed_attributes: tuple[str, ...] = ()
    flag_only_symbols: tuple[str, ...] = ()
    # Of those, the symbols flagged only for the calls that match: any other call is no row.
    flag_only_calls: dict[str, CallShape] = Field(default_factory=dict)
    flag_only_patterns: tuple[FlagOnlyPattern, ...] = ()
    # The variables `environment_write` reports a write of: the new releases read other names.
    flag_only_variables: tuple[str, ...] = ()
    # The new SDK keeps the module's name, so only `symbols` (and what lies under them) is legacy.
    shared: bool = False
    # A library with no pack: every place that uses it is listed, none is rewritten.
    inventory: bool = False
    # Set only where one distribution is both sides: the versions of it that are the new API.
    new_range: str | None = None
    # Modules that came with the legacy pin, which the manifest pin check inspects before the
    # pin may go.
    transitive_modules: tuple[ProvidedModule, ...] = ()
    # Whether the pin moves by declaring those modules' distributions in a requirements file,
    # where `transitive_dependency_in_use` would keep it.
    declare_transitive: bool = False
    # Names only the new API defines, where one distribution holds both: code that uses one beside
    # a pin that admits only the legacy range is a manifest row.
    new_names: tuple[str, ...] = ()
    # What the repository must declare for a run to propose anything: the PEP 440 set of Pythons
    # the new side runs on (the new distribution installs on, or `to.python`), and the lowest legacy
    # version the pack's rules were measured on. Neither changes a finding, so `spec_digest` leaves
    # them out. Nor do the newest legacy release (what a declaration naming no version installs)
    # and the names it lacks, or the legacy range and the names only it defines (what code that
    # uses one is taken to prove).
    requires_python: str
    legacy_floor: str | None = None
    legacy_newest: str | None = None
    legacy_lacks: tuple[str, ...] = ()
    legacy_range: str = ""
    legacy_since: tuple[str, ...] = ()
    # The releases the pack writes (`to.version`): a declaration of the new distribution that admits
    # none of them stops the run. Also a gate, so `spec_digest` leaves it out.
    new_version: str | None = None

    @model_validator(mode="after")
    def _check(self) -> ScanSpec:
        if not self.legacy_modules:
            raise ValueError("legacy_modules must name at least one module")
        if not self.prefilter_tokens:
            raise ValueError("without a prefilter token every file in the repository is parsed")
        for field, values in (
            ("legacy_modules", self.legacy_modules),
            ("symbols", self.symbols),
            ("constructor_symbols", self.constructor_symbols),
            ("removed_attributes", self.removed_attributes),
            ("flag_only_symbols", self.flag_only_symbols),
            ("flag_only_variables", self.flag_only_variables),
            ("legacy_lacks", self.legacy_lacks),
            ("legacy_since", self.legacy_since),
            ("new_names", self.new_names),
        ):
            sorted_unique(values, field)
            bad = [value for value in values if not QUALIFIED_NAME.fullmatch(value)]
            if bad:
                raise ValueError(f"{field} takes qualified names, got {bad}")
        sorted_unique(self.prefilter_tokens, "prefilter_tokens")
        sorted_unique(self.flag_only_patterns, "flag_only_patterns")
        sorted_unique(tuple(self.flag_only_calls), "flag_only_calls")
        if not set(self.flag_only_calls) <= set(self.flag_only_symbols):
            raise ValueError("flag_only_calls names a symbol that flag_only_symbols does not")
        for field, value in (
            ("legacy_distribution", self.legacy_distribution),
            ("new_distribution", self.new_distribution),
        ):
            if value and not _DISTRIBUTION_NAME.fullmatch(value):
                raise ValueError(f"{field} takes a distribution name, got {value!r}")
        for field, symbol in (
            ("client_symbol", self.client_symbol),
            ("new_client_symbol", self.new_client_symbol),
        ):
            if symbol is not None and not QUALIFIED_NAME.fullmatch(symbol):
                raise ValueError(f"{field} must be a qualified name, got {symbol!r}")
        SpecifierSet(self.requires_python)
        SpecifierSet(self.legacy_range)
        for specifier in (self.new_range, self.new_version):
            if specifier is not None:
                SpecifierSet(specifier)
        if self.legacy_floor is not None:
            Version(self.legacy_floor)
        if self.legacy_newest is not None:
            Version(self.legacy_newest)
        receivers = tuple(entry.receiver for entry in self.supported_methods)
        sorted_unique(receivers, "supported_methods")
        sorted_unique(tuple(entry.method for entry in self.method_returns), "method_returns")
        sorted_unique(tuple(entry.class_symbol for entry in self.member_classes), "member_classes")
        for entry in self.method_returns:
            owner, _, method = entry.method.rpartition(".")
            if method not in self.methods_for(owner):
                raise ValueError(
                    f"method_returns names {entry.method}, which is not a supported method of "
                    f"{owner or '(nothing)'}"
                )
            if entry.receiver not in receivers:
                raise ValueError(
                    f"{entry.method} is said to produce {entry.receiver}, which supports no "
                    f"methods; a receiver the scanner can hold and do nothing with is not one"
                )
        produced = {entry.receiver for entry in self.method_returns}
        unreachable = sorted(set(receivers) - set(self.constructor_symbols) - produced)
        if unreachable:
            raise ValueError(
                f"nothing in this spec can produce {unreachable}: a receiver is held by a "
                f"constructor call or by a method that returns it, and these are neither, so "
                f"their methods would never resolve"
            )
        return self

    def members_of(self, class_symbol: str) -> tuple[str, ...]:
        """The members a pack renames on `class_symbol`, or `()`."""
        return next(
            (entry.members for entry in self.member_classes if entry.class_symbol == class_symbol),
            (),
        )

    def methods_for(self, receiver: str) -> tuple[str, ...]:
        """The supported methods of `receiver`, or `()` when it has none.

        The escape rule: a bound name used other than as their receiver withholds its group.
        """
        for entry in self.supported_methods:
            if entry.receiver == receiver:
                return entry.methods
        return ()


class ImpactPlan(_Frozen):
    """One file's findings and binding groups, after every scan-time rule.

    A file with any withheld row is left exactly as it was, so no plan that edits half a file
    can be built.
    `manifest` findings are refused: the manifest pin check grades them repo-wide in
    `ManifestPlan`.
    """

    path: RelativePath
    findings: tuple[Finding, ...] = ()
    bindings: tuple[Binding, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ImpactPlan:
        elsewhere = sorted(
            {row.path for row in self.findings if row.path != self.path}
            | {str(row.path) for row in self.bindings if row.path != self.path}
        )
        if elsewhere:
            raise ValueError(
                f"a plan for {self.path!r} carries rows about {elsewhere}; a plan is one file's"
            )
        if any(finding.kind == "manifest" for finding in self.findings):
            raise ValueError(
                "a manifest is not a parsed source file; a `manifest` finding does not belong "
                "to a file's plan"
            )
        keys = [finding.sort_key for finding in self.findings]
        if keys != sorted(keys):
            raise ValueError("findings are written in document order; sort before emitting")
        rows = [(row.ctor_line, row.scope, row.name) for row in self.bindings]
        if rows != sorted(rows):
            raise ValueError("bindings are written in constructor order; sort before emitting")

        withheld = [row.line for row in self.findings if row.scan_status in WITHHELD]
        eligible = [row.line for row in self.findings if row.scan_status == "eligible"]
        if withheld and eligible:
            raise ValueError(
                f"{self.path}: lines {eligible} are eligible while lines {withheld} are "
                f"withheld. A file with a withheld finding is left exactly as it was, so the "
                f"eligible rows carry {ATOMICITY_BAIL!r} with `caused_by` naming what withheld "
                f"the rest"
            )
        return self


class ManifestPlan(_Frozen):
    """The repository's dependency declarations, after the manifest pin check's two edits.

    Repo-wide, and unlike `ImpactPlan` an applied edit may sit beside a withheld one: both pins
    keep a partial migration installable. `blocking` and `transitive` are the in-scope files
    behind `repo_not_fully_migrated` and `transitive_dependency_in_use`, required when either
    appears; `excluded` files do not block the removal but are named, since it breaks them too.
    """

    findings: tuple[Finding, ...] = ()
    blocking: tuple[RelativePath, ...] = ()
    excluded: tuple[RelativePath, ...] = ()
    transitive: tuple[RelativePath, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ManifestPlan:
        kinds = sorted({row.kind for row in self.findings if row.kind != "manifest"})
        if kinds:
            raise ValueError(
                f"a manifest plan grades dependency declarations and nothing else, got {kinds}"
            )
        stamped = [row.line for row in self.findings if row.bail == ATOMICITY_BAIL]
        if stamped:
            raise ValueError(
                f"{ATOMICITY_BAIL!r} is a property of a parsed source file; lines {stamped} are "
                f"manifest declarations, whose atomicity is {REPO_ATOMICITY_BAIL!r}"
            )
        keys = [row.sort_key for row in self.findings]
        if keys != sorted(keys):
            raise ValueError("findings are written in document order; sort before emitting")
        sorted_unique(self.blocking, "blocking")
        sorted_unique(self.excluded, "excluded")
        sorted_unique(self.transitive, "transitive")
        for code, named, claim in (
            (REPO_ATOMICITY_BAIL, self.blocking, "still imports the legacy distribution"),
            (
                "transitive_dependency_in_use",
                self.transitive,
                "imports a module only the legacy distribution installs",
            ),
        ):
            withheld = [row.line for row in self.findings if row.bail == code]
            if withheld and not named:
                raise ValueError(
                    f"lines {withheld} are withheld with {code!r}, which claims that an "
                    f"in-scope file {claim}, and none is named"
                )
        return self


class PackRef(_Frozen):
    """The pack a document was produced with, as `run.json` records it."""

    id: str
    version: str
    sha256: Sha256


class ScanCounts(_Frozen):
    """A summary of the findings, never a substitute for them."""

    files_selected: int = Field(ge=0)
    files_parsed: int = Field(ge=0)
    findings: int = Field(ge=0)
    eligible: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    not_a_usage: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> ScanCounts:
        if self.files_parsed > self.files_selected:
            raise ValueError("more files were parsed than were selected")
        split = self.eligible + self.needs_review + self.unsupported + self.not_a_usage
        if split != self.findings:
            raise ValueError(f"the status split sums to {split}, and there are {self.findings}")
        return self


class FindingsDocument(_Frozen):
    """The `findings.json` document, which `obelize scan --json` also prints."""

    # Nothing time-derived: two runs over the same input are byte-identical.

    obelize_version: str
    packs: tuple[PackRef, ...] = ()
    counts: ScanCounts
    findings: tuple[Finding, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> FindingsDocument:
        sorted_unique(tuple(pack.id for pack in self.packs), "packs")
        keys = [finding.sort_key for finding in self.findings]
        if keys != sorted(keys):
            raise ValueError("findings are written in document order; sort before emitting")
        counted = dict.fromkeys(sorted(SCAN_STATUSES), 0)
        for finding in self.findings:
            counted[finding.scan_status] += 1
        recorded = {
            "eligible": self.counts.eligible,
            "needs_review": self.counts.needs_review,
            "not_a_usage": self.counts.not_a_usage,
            "unsupported": self.counts.unsupported,
        }
        # `counts.findings` needs no check: ScanCounts already ties the total to the split.
        if counted != recorded:
            raise ValueError(f"counts {recorded} do not describe the {len(self.findings)} findings")
        return self


__all__ = [
    "Binding",
    "CallShape",
    "Edit",
    "EditProposal",
    "Finding",
    "FindingsDocument",
    "ImpactPlan",
    "ManifestPlan",
    "MemberClass",
    "MethodReturn",
    "PackRef",
    "ProvidedModule",
    "ReceiverMethods",
    "ScanCounts",
    "ScanSpec",
    "bounds",
]
