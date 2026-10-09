"""The pack model. A pack is untrusted data, so every model is closed (`extra="forbid"`).

No I/O: the loader hands in a mapping, and `source.url` is never fetched. Suggestions never run,
so they are not validated as commands. Terminal-bound prose is `DisplayText`. Coherence across
fields is checked, naming the wrong key's path: an incoherent pack would scan as clean.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal, Union, get_args
from urllib.parse import urlsplit

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from obelize.models import (
    QUALIFIED_NAME,
    DisplayText,
    DistributionName,
    FlagOnlyPattern,
    PlainName,
    PrefilterToken,
    QualifiedName,
    RelativePath,
    Sha256,
    bounds,
)

# Adding a kind is a code change; the registry table must list the same set.
ChangeKind = Literal[
    "rename_import",
    "configure_to_client",
    "generative_model_calls",
    "rewrite_call",
    "rename_setting",
    "flag_only",
    "manifest_dependency",
]
CHANGE_KINDS: frozenset[ChangeKind] = frozenset(get_args(ChangeKind))

# Closed: pack review admits only the vendor's own migration guide or API reference.
SourceType = Literal["official_guide", "sdk_reference"]
SOURCE_TYPES: frozenset[SourceType] = frozenset(get_args(SourceType))

# SDK facts that drive refusals live in code: a pack may carry nothing that drives behaviour.
# PACK_SPEC must name each value (tested).

# Not a legacy `GenerationConfig` field (the server rejected it); carrying it changes behaviour.
FORBIDDEN_CONFIG_KEYS: frozenset[str] = frozenset({"seed"})

# Keys the legacy safety lookup raised `KeyError` for.
FORBIDDEN_SAFETY_CATEGORY_KEYS: frozenset[str] = frozenset({"dangerous_content"})
FORBIDDEN_SAFETY_THRESHOLD_KEYS: frozenset[str] = frozenset({"off", "none"})

# In neither SDK; the new enum fabricates unknown members with only a warning.
FORBIDDEN_SAFETY_VALUES: frozenset[str] = frozenset({"HARM_CATEGORY_HATE"})

# No dot in either segment, so a bundled id joined onto the packs directory cannot hold `..`.
_PACK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# No `+build`: comparisons ignore it, so two different packs could compare as one version.
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_ENUM_MEMBER = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SYMBOL_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
# One visible ASCII character, no quote, backslash or digit, so it ends a string literal as written
# (a digit after an octal escape would join it).
_TRAILING = re.compile(r"^[!#-&(-/:-\[\]-~]$")


def _pack_id(value: str) -> str:
    if not _PACK_ID.fullmatch(value):
        raise ValueError(
            f"expected a pack id of the form <provider>/<slug>, lower case and "
            f"hyphen separated, got {value!r}"
        )
    return value


def _slug(value: str) -> str:
    if not _SLUG.fullmatch(value):
        raise ValueError(f"expected a lower-case, hyphen-separated name, got {value!r}")
    return value


def _semver(value: str) -> str:
    if not _SEMVER.fullmatch(value):
        raise ValueError(f"expected a semver version such as 0.1.0, got {value!r}")
    return value


def _symbol_key(value: str) -> str:
    if not _SYMBOL_KEY.fullmatch(value):
        raise ValueError(f"expected `Name` or `<submodule>.Name`, got {value!r}")
    return value


def _trailing_character(value: str) -> str:
    if not _TRAILING.fullmatch(value):
        raise ValueError(
            f"expected one visible ASCII character that is not a quote, a backslash or a "
            f"digit, got {value!r}"
        )
    return value


def _enum_member(value: str) -> str:
    if not _ENUM_MEMBER.fullmatch(value):
        raise ValueError(f"expected an UPPER_SNAKE_CASE enum member name, got {value!r}")
    return value


def _lower_key(value: str) -> str:
    """Lower-case only: lookups lower the input, as the legacy SDK did."""
    if not value:
        raise ValueError("a safety-table key must not be empty")
    if value != value.lower():
        raise ValueError(
            f"safety-table keys are matched case-insensitively, so the table holds the "
            f"lower-case spelling: {value!r} should be {value.lower()!r}"
        )
    return value


def _source_url(value: str) -> str:
    """Provenance, never requested. No credential: the host is copied into the run report."""
    parts = urlsplit(value)
    if parts.scheme != "https":
        raise ValueError(f"a source url must be https, got {value!r}")
    if not parts.hostname:
        raise ValueError(f"a source url must name a host, got {value!r}")
    if parts.username or parts.password:
        raise ValueError("a source url must not carry a credential; it is copied into evidence")
    return value


def _pep440_specifier(value: str) -> str:
    if not value.strip():
        raise ValueError("expected a PEP 440 version specifier such as '>=1'")
    try:
        SpecifierSet(value)
    except InvalidSpecifier as error:
        raise ValueError(f"expected a PEP 440 version specifier, got {value!r}: {error}") from error
    return value


def _fixture_path(value: str) -> str:
    """Shape only: only bundled packs' tests check existence, so a local pack still loads."""
    if not value.startswith("fixtures/"):
        raise ValueError(f"a fixture path must be under fixtures/, got {value!r}")
    if value.endswith("/"):
        raise ValueError(f"a fixture path must name a file or a directory, got {value!r}")
    return value


def _dotted_call(value: str) -> str:
    """`service.method` relative to the client or the module, such as `models.embed_content`."""
    if not QUALIFIED_NAME.fullmatch(value):
        raise ValueError(f"expected a dotted path under the client, got {value!r}")
    if "." not in value:
        raise ValueError(
            f"a call under the client or the module names a service and a method on it, such "
            f"as models.generate_content; got {value!r}"
        )
    return value


def _call_path(value: str) -> str:
    """`_dotted_call` without the dot rule, which `MethodRewrite` applies per `root`."""
    if not QUALIFIED_NAME.fullmatch(value):
        raise ValueError(f"expected a dotted path under the client, got {value!r}")
    return value


PackId = Annotated[str, AfterValidator(_pack_id)]
Slug = Annotated[str, AfterValidator(_slug)]
SemVer = Annotated[str, AfterValidator(_semver)]
EnumMemberName = Annotated[str, AfterValidator(_enum_member)]
SymbolKey = Annotated[str, AfterValidator(_symbol_key)]
TrailingCharacter = Annotated[str, AfterValidator(_trailing_character)]
SafetyKey = Annotated[str, AfterValidator(_lower_key)]
SourceUrl = Annotated[str, AfterValidator(_source_url)]
Pep440Specifier = Annotated[str, AfterValidator(_pep440_specifier)]
FixturePath = Annotated[RelativePath, AfterValidator(_fixture_path)]
DottedCall = Annotated[str, AfterValidator(_dotted_call)]
CallPath = Annotated[str, AfterValidator(_call_path)]

# `receiver`: one legacy receiver survives as an object in the new SDK; the model does not.
CallRoot = Literal["client", "receiver"]

# `module`: the call stays on the root the author wrote, as the new SDK still has a module client.
RewriteRoot = Literal["client", "module"]

_RESULT_PATH = re.compile(r"^[A-Za-z_]\w*(?:\[\])?(?:\.[A-Za-z_]\w*(?:\[\])?)*$", re.ASCII)


def _result_path(value: str) -> str:
    """`choices[].message.content`: attributes, and `[]` for an integer-literal subscript."""
    if not _RESULT_PATH.fullmatch(value) or value.endswith("[]"):
        raise ValueError(
            f"a result path is dotted attribute names, `[]` after one that is indexed, and ends "
            f"in an attribute, such as choices[].message.content; got {value!r}"
        )
    return value


ResultPath = Annotated[str, AfterValidator(_result_path)]


def _literal_prefix(value: str) -> str:
    """A literal compared with `str.startswith`, never a pattern, as the legacy `get_model` did."""
    if not value:
        raise ValueError("a dispatch prefix must not be empty: every string starts with ''")
    if value != value.strip() or not value.isprintable():
        raise ValueError(f"a dispatch prefix is the literal start of an argument, got {value!r}")
    return value


LiteralPrefix = Annotated[str, AfterValidator(_literal_prefix)]


def _sorted_set(values: tuple[str, ...], field: str) -> None:
    """An unordered field has exactly one spelling."""
    if list(values) != sorted(set(values)):
        raise ValueError(f"{field} must be sorted and de-duplicated, got {list(values)}")


def _ordered_unique(values: tuple[str, ...], field: str) -> None:
    """For fields whose order is data (signatures, printed lists): refuse repeats, never sort."""
    duplicates = sorted({value for value in values if list(values).count(value) > 1})
    if duplicates:
        raise ValueError(f"{field} must not repeat an entry, got {duplicates}")


class _Closed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PackSource(_Closed):
    """Where and when the migration facts were read; the optional `sha256` hashes that page."""

    type: SourceType
    url: SourceUrl
    retrieved_at: dt.date
    sha256: Sha256 | None = None


class VersionRange(_Closed):
    """One side of the migration: a distribution and a PEP 440 range of it."""

    package: DistributionName
    version: Pep440Specifier


class Target(VersionRange):
    """The new side, which also says which Pythons it installs on."""

    requires_python: Pep440Specifier


class Match(_Closed):
    """What the scanner looks for before any rule runs."""

    imports: tuple[QualifiedName, ...]
    symbols: tuple[QualifiedName, ...] = ()
    prefilter_tokens: tuple[PrefilterToken, ...]
    # Module the legacy distribution installed and the new one does not -> its distribution. While a
    # file imports one that no manifest declares, the legacy pin stays.
    transitive: dict[QualifiedName, DistributionName] = Field(default_factory=dict)
    # The module is the new SDK's too, so `import M` is no finding and only `symbols` are legacy.
    shared: bool = False

    @model_validator(mode="after")
    def _check(self) -> Match:
        if not self.imports:
            raise ValueError("imports must name at least one module")
        if self.shared and not self.symbols:
            raise ValueError("a shared module has no legacy surface until symbols names it")
        if not self.prefilter_tokens:
            raise ValueError("without a prefilter token every file in the repository is parsed")
        _sorted_set(self.imports, "imports")
        _sorted_set(self.symbols, "symbols")
        _sorted_set(self.prefilter_tokens, "prefilter_tokens")
        for symbol in self.symbols:
            if not under_any(symbol, self.imports):
                raise ValueError(
                    f"{symbol!r} is not under any module in imports {list(self.imports)}, so no "
                    f"resolution can ever produce it"
                )
        for module in self.imports:
            if not any(token in module for token in self.prefilter_tokens):
                raise ValueError(
                    f"no prefilter token occurs in {module!r}, so every file that imports it is "
                    f"eliminated before it is parsed"
                )
        return self


def under_any(symbol: str, modules: tuple[str, ...]) -> bool:
    """Is `symbol` the module or inside it? By dotted segment: `google.generativeaix` is not."""
    return any(symbol == module or symbol.startswith(f"{module}.") for module in modules)


class RenameImportParams(_Closed):
    from_module: QualifiedName
    to_module: QualifiedName
    default_alias: PlainName
    submodule_map: dict[PlainName, QualifiedName] = Field(default_factory=dict)
    # `Name` is a symbol of the module, `<submodule>.Name` one of a submodule in `submodule_map`.
    symbol_map: dict[SymbolKey, PlainName] = Field(default_factory=dict)
    # A submodule's alias when the file already binds the submodule's own name.
    alias_fallbacks: dict[PlainName, PlainName] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> RenameImportParams:
        if self.from_module == self.to_module:
            raise ValueError("from_module and to_module are the same; there is nothing to rename")
        for name, fallback in self.alias_fallbacks.items():
            if name not in self.submodule_map:
                raise ValueError(f"alias_fallbacks[{name!r}] names no submodule in submodule_map")
            if fallback == self.default_alias:
                raise ValueError(
                    f"alias_fallbacks[{name!r}] exists for the case where the file already binds "
                    f"the submodule's own name, so it must differ from default_alias"
                )
        for name, target in self.submodule_map.items():
            if not target.startswith(f"{self.to_module}."):
                raise ValueError(
                    f"submodule_map[{name!r}] must be under to_module {self.to_module!r}, "
                    f"got {target!r}"
                )
        for key in self.symbol_map:
            head, dot, _ = key.partition(".")
            if dot and head not in self.submodule_map:
                raise ValueError(
                    f"symbol_map[{key!r}] names a symbol inside the {head!r} submodule, so "
                    f"submodule_map has to say where that submodule moved to"
                )
            if not dot and head in self.submodule_map:
                raise ValueError(
                    f"symbol_map[{key!r}] names a submodule, which submodule_map moves"
                )
        return self


class ConfigureToClientParams(_Closed):
    legacy_symbol: QualifiedName
    # The class the rewrite constructs.
    client_symbol: QualifiedName
    client_name: PlainName
    # The naming ladder's second rung; pack data, since a rule must not invent names in user files.
    client_name_fallback: PlainName
    allowed_kwargs: tuple[PlainName, ...]
    # The new client validates it at construction. A non-empty literal cannot fail there, so it is
    # exempt from `client_constructed_eagerly`.
    credential_kwarg: PlainName
    # The new client takes an object only; a mapping, valid in the legacy one, bails
    # `credentials_shape_differs`.
    credentials_object_kwarg: PlainName

    @model_validator(mode="after")
    def _check(self) -> ConfigureToClientParams:
        if not self.allowed_kwargs:
            raise ValueError("allowed_kwargs is empty, so every call with a keyword is refused")
        _sorted_set(self.allowed_kwargs, "allowed_kwargs")
        if self.client_name == self.client_name_fallback:
            raise ValueError(
                f"client_name and client_name_fallback are both {self.client_name!r}, so the "
                f"naming ladder has one rung written as two: a module that binds the name would "
                f"bail client_name_collision where the pack looks like it offers a second chance"
            )
        if "." not in self.client_symbol:
            raise ValueError(
                f"client_symbol names a class under the new module, such as google.genai.Client; "
                f"got {self.client_symbol!r}"
            )
        for field, value in (
            ("credential_kwarg", self.credential_kwarg),
            ("credentials_object_kwarg", self.credentials_object_kwarg),
        ):
            if value not in self.allowed_kwargs:
                raise ValueError(
                    f"{field} is {value!r}, which is not in allowed_kwargs "
                    f"{list(self.allowed_kwargs)}: a keyword with a role in the rewrite that the "
                    f"rule refuses outright is a rule that can never reach the role"
                )
        return self


class SafetySettings(_Closed):
    """The safety table: legacy safety strings and enum members, and the new members they become."""

    # The new enums' `_missing_` fabricates unknown members with only a warning, so every emitted
    # name is checked here. Legacy strings (`*_map`) and legacy members (`*_members`) are different
    # sets: `HarmBlockThreshold.OFF` is a member, but "off" was never a legacy string.

    # Same spelling on the legacy constructor and the legacy call.
    legacy_kwarg: PlainName
    # Keys of the list-of-dicts form the legacy SDK also accepted.
    legacy_category_key: PlainName
    legacy_threshold_key: PlainName
    # The PaLM-era `protos` spelling is deliberately absent: it is flagged, and the file withheld.
    legacy_category_class: QualifiedName
    legacy_threshold_class: QualifiedName
    category_map: dict[SafetyKey, EnumMemberName]
    threshold_map: dict[SafetyKey, EnumMemberName]
    # Recognised and emitted under their own names, so every map value must be one.
    category_members: tuple[EnumMemberName, ...]
    threshold_members: tuple[EnumMemberName, ...]
    # The class one table row becomes, and the two enums it names.
    setting_class: QualifiedName
    category_class: QualifiedName
    threshold_class: QualifiedName
    # What that class calls the two halves of a row.
    category_kwarg: PlainName
    threshold_kwarg: PlainName
    # The configuration field the list of rows lands in.
    config_field: PlainName

    @model_validator(mode="after")
    def _check(self) -> SafetySettings:
        for field, table, forbidden_keys in (
            ("category_map", self.category_map, FORBIDDEN_SAFETY_CATEGORY_KEYS),
            ("threshold_map", self.threshold_map, FORBIDDEN_SAFETY_THRESHOLD_KEYS),
        ):
            if not table:
                raise ValueError(f"{field} is empty; no safety setting could be mapped")
            present = forbidden_keys.intersection(table)
            if present:
                raise ValueError(
                    f"{field} must not accept {sorted(present)}: the legacy lookup raised "
                    f"KeyError for it, so code using it was already broken"
                )
        for field, members in (
            ("category_members", self.category_members),
            ("threshold_members", self.threshold_members),
        ):
            if not members:
                raise ValueError(f"{field} is empty; no enum member could be recognised")
            _sorted_set(members, field)
            emitted = FORBIDDEN_SAFETY_VALUES.intersection(members)
            if emitted:
                raise ValueError(
                    f"{field} must never carry {sorted(emitted)}: the name exists in neither SDK "
                    f"and the new enum fabricates an unknown member with only a warning"
                )
        for field, table, members in (
            ("category_map", self.category_map, self.category_members),
            ("threshold_map", self.threshold_map, self.threshold_members),
        ):
            outside = sorted(set(table.values()) - set(members))
            if outside:
                raise ValueError(
                    f"{field} emits {outside}, which {field.split('_')[0]}_members does not "
                    f"declare; the member list is the closed set this rule may write, and a map "
                    f"that reaches past it is how an enum member nobody checked gets emitted"
                )
        if self.legacy_category_class == self.legacy_threshold_class:
            raise ValueError(
                "legacy_category_class and legacy_threshold_class are the two enums a safety row "
                "is written out of; naming one class twice makes a threshold readable as a "
                "category"
            )
        return self


class ChatHistory(_Closed):
    """A chat history, whose bare-string parts are wrapped under `text_key` for the new SDK."""

    role_key: PlainName
    parts_key: PlainName
    text_key: PlainName
    # The new SDK raises `ValueError` for any other role, so such a history is refused.
    roles: tuple[PlainName, ...]

    @model_validator(mode="after")
    def _check(self) -> ChatHistory:
        if not self.roles:
            raise ValueError("roles is empty; every history entry would be refused")
        _sorted_set(self.roles, "roles")
        if self.role_key == self.parts_key:
            raise ValueError("role_key and parts_key are two keys of one entry, not one")
        return self


class MethodRewrite(_Closed):
    """How one legacy method of a declared receiver becomes a call in the new SDK."""

    # A method in `methods` with no entry here is recognised, never rewritten: its file stays as is.
    new_call: CallPath
    # `client` prepends the client and the model name: new model calls go through a client service.
    # `receiver` prepends neither: the new chat object already holds both.
    root: CallRoot = "client"
    # Where a `stream=True` call goes instead; absent means `stream=` is `unsupported_kwarg`.
    stream_call: CallPath | None = None
    # Legacy positional parameters in legacy order. The new methods are keyword-only, so a
    # positional argument takes the name at its index before anything is prepended.
    positional_to_kw: tuple[PlainName, ...] = ()
    # Renamed arguments, legacy -> new; the old spelling is a `TypeError` after migration.
    arg_map: dict[PlainName, PlainName] = Field(default_factory=dict)
    # This call's keywords toggling automatic function calling: refused, since the default flipped.
    afc_kwargs: tuple[PlainName, ...] = ()
    # Carries a chat history, reshaped by `GenerativeModelCallsParams.history`.
    history_kwarg: PlainName | None = None
    # The prompt: bare-string parts are checked, and a list of turns is reshaped like a history.
    contents_kwarg: PlainName | None = None
    # The legacy method and its replacement are both coroutine functions, so `await` carries over.
    # A streaming call under `async for` with no `await` already raised before migration.
    coroutine: bool = False
    # Absent: the new call takes no config, so the constructor's is dropped and the edit says so.
    config_kwarg: PlainName | None = None
    # Constructor keywords that change this call's answer, so they may not be dropped.
    semantic_kwargs: tuple[PlainName, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> MethodRewrite:
        # Legacy parameter order: not sorted.
        _ordered_unique(self.positional_to_kw, "positional_to_kw")
        _sorted_set(self.semantic_kwargs, "semantic_kwargs")
        _sorted_set(self.afc_kwargs, "afc_kwargs")
        if self.semantic_kwargs and self.config_kwarg is not None:
            raise ValueError(
                "semantic_kwargs names constructor keywords that may not be dropped, and a call "
                "that has a config_kwarg drops nothing; one of the two is wrong"
            )
        if self.stream_call == self.new_call:
            raise ValueError(
                f"stream_call is where a streaming call goes *instead* of {self.new_call!r}; "
                f"naming the same method makes the stream keyword disappear silently"
            )
        self._check_the_arguments_are_claimed_once()
        self._check_the_call_is_spelled_for_where_it_is_rooted()
        return self

    def _check_the_call_is_spelled_for_where_it_is_rooted(self) -> None:
        for field, value in (("new_call", self.new_call), ("stream_call", self.stream_call)):
            if value is None:
                continue
            if self.root == "client" and "." not in value:
                raise ValueError(
                    f"{field} is rooted on the client, so it names a service and a method on it, "
                    f"such as models.generate_content; got {value!r}"
                )
            if self.root == "receiver" and "." in value:
                raise ValueError(
                    f"{field} is rooted on the receiver the author already wrote, so it names a "
                    f"method of that object and nothing in front of it; got {value!r}"
                )

    def _check_the_arguments_are_claimed_once(self) -> None:
        for field, names in (("afc_kwargs", self.afc_kwargs), ("arg_map", tuple(self.arg_map))):
            for name in names:
                if name in self.positional_to_kw and field == "afc_kwargs":
                    raise ValueError(
                        f"afc_kwargs names {name!r}, which positional_to_kw also claims; a "
                        f"keyword is refused or it is carried, not both"
                    )
                if field == "arg_map" and name not in self.positional_to_kw:
                    raise ValueError(
                        f"arg_map renames {name!r}, which is not in positional_to_kw "
                        f"{list(self.positional_to_kw)}; no call can reach the rename"
                    )
        renamed = sorted(self.arg_map.values())
        if len(set(renamed)) != len(renamed):
            raise ValueError(f"arg_map maps two legacy keywords onto one new one: {renamed}")
        if self.history_kwarg is not None and self.history_kwarg in (
            *self.positional_to_kw,
            *self.afc_kwargs,
        ):
            raise ValueError(
                f"history_kwarg is {self.history_kwarg!r}, which another field already claims; a "
                f"keyword whose value is reshaped is not also one that is carried or refused"
            )


class GenerativeModelCallsParams(_Closed):
    ctor_symbol: QualifiedName
    methods: dict[QualifiedName, tuple[PlainName, ...]]
    method_returns: dict[QualifiedName, QualifiedName] = Field(default_factory=dict)
    generation_config_keys: tuple[PlainName, ...]
    safety: SafetySettings
    history: ChatHistory | None = None
    config_class: QualifiedName
    # The legacy class behind `config_class`. Named, not derived: it is also reached off the legacy
    # module, and its `types` spelling is the import rule's to rewrite.
    legacy_config_symbol: QualifiedName
    # Its submodule spellings: recognised as a configuration here, renamed by the import rule.
    legacy_config_aliases: tuple[QualifiedName, ...] = ()
    # Same spelling on the legacy constructor and the legacy call.
    legacy_config_kwarg: PlainName
    # The legacy constructor's parameters in declared order, which is data: all are
    # positional-or-keyword, and `safety_settings` comes before `generation_config`.
    ctor_order: tuple[PlainName, ...]
    ctor_model_kwarg: PlainName
    # Constructor parameters carried into the configuration object under the same name.
    ctor_config_fields: tuple[PlainName, ...] = ()
    # Constructor keywords toggling automatic function calling: refused, since the default flipped.
    ctor_afc_kwargs: tuple[PlainName, ...] = ()
    # Names the model on the new calls.
    model_kwarg: PlainName
    # Asked the legacy methods to stream.
    stream_kwarg: PlainName
    # Folding this prefix into `model=` works, so it warns and never rewrites the author's string.
    model_name_prefix: str
    rewrites: dict[QualifiedName, MethodRewrite] = Field(default_factory=dict)
    # Response attributes that raised `response_legacy_error` on the legacy object and return `None`
    # on the new one. A handler would silently stop running, so the shape is refused.
    response_attrs_now_none: tuple[PlainName, ...] = ()
    response_legacy_error: PlainName | None = None
    # Exceptions only the legacy SDK raises: a handler would never run, so `error_class_changed`.
    legacy_error_modules: tuple[QualifiedName, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> GenerativeModelCallsParams:
        if not self.methods:
            raise ValueError("methods is empty, so no call can be rewritten")
        if self.ctor_symbol not in self.methods:
            raise ValueError(
                f"methods has no entry for ctor_symbol {self.ctor_symbol!r}. A reference that "
                f"is not the receiver of a supported method is withheld, so a receiver with no "
                f"method list withholds every use of it"
            )
        for receiver, names in self.methods.items():
            if not names:
                raise ValueError(f"methods[{receiver!r}] is empty; drop the entry instead")
            _sorted_set(names, f"methods[{receiver!r}]")
        self._check_receivers_can_be_held()
        if not self.generation_config_keys:
            raise ValueError("generation_config_keys is empty; every config would be unknown")
        _sorted_set(self.generation_config_keys, "generation_config_keys")
        forbidden = FORBIDDEN_CONFIG_KEYS.intersection(self.generation_config_keys)
        if forbidden:
            raise ValueError(
                f"generation_config_keys must not carry {sorted(forbidden)}: the key is absent "
                f"from the legacy configuration and mapping it across would change behaviour"
            )
        if not self.model_name_prefix:
            raise ValueError(
                "model_name_prefix is the resource-name prefix a model literal may carry; an "
                "empty one is a prefix every literal has, so every edit would carry the warning"
            )
        self._check_the_constructor_is_taken_apart_once()
        self._check_every_rewritten_method_is_a_supported_one()
        self._check_the_configuration_class_has_one_claimant()
        self._check_the_response_shape_is_stated_from_both_ends()
        self._check_what_a_rewrite_needs_is_declared()
        return self

    def _check_the_constructor_is_taken_apart_once(self) -> None:
        _ordered_unique(self.ctor_order, "ctor_order")
        if not self.ctor_order:
            raise ValueError("ctor_order is the legacy signature; a constructor has parameters")
        _sorted_set(self.ctor_config_fields, "ctor_config_fields")
        _sorted_set(self.ctor_afc_kwargs, "ctor_afc_kwargs")
        placed: list[tuple[str, tuple[str, ...]]] = [
            ("ctor_model_kwarg", (self.ctor_model_kwarg,)),
            ("legacy_config_kwarg", (self.legacy_config_kwarg,)),
            ("safety.legacy_kwarg", (self.safety.legacy_kwarg,)),
            ("ctor_config_fields", self.ctor_config_fields),
            ("ctor_afc_kwargs", self.ctor_afc_kwargs),
        ]
        seen: dict[str, str] = {}
        for field, names in placed:
            for name in names:
                if name not in self.ctor_order:
                    raise ValueError(
                        f"{field} names {name!r}, which is not a parameter in ctor_order "
                        f"{list(self.ctor_order)}; the rule would wait for a call that cannot "
                        f"be written"
                    )
                if name in seen:
                    raise ValueError(
                        f"{name!r} is placed by both {seen[name]} and {field}; a constructor "
                        f"parameter has one destination or none"
                    )
                seen[name] = field

    def _check_every_rewritten_method_is_a_supported_one(self) -> None:
        """A rewrite needs a supported method; not vice versa, which keeps the file out of a run."""
        supported = {
            f"{receiver}.{name}" for receiver, names in self.methods.items() for name in names
        }
        for method in self.rewrites:
            if method not in supported:
                raise ValueError(
                    f"rewrites names {method!r}, which is not a supported method of any receiver "
                    f"in methods; no resolution can produce it"
                )

    def _check_the_configuration_class_has_one_claimant(self) -> None:
        _sorted_set(self.legacy_config_aliases, "legacy_config_aliases")
        if self.legacy_config_symbol in self.legacy_config_aliases:
            raise ValueError(
                f"legacy_config_symbol {self.legacy_config_symbol!r} is also in "
                f"legacy_config_aliases; one symbol has one rule that rewrites it"
            )

    def _check_the_response_shape_is_stated_from_both_ends(self) -> None:
        _sorted_set(self.response_attrs_now_none, "response_attrs_now_none")
        if bool(self.response_attrs_now_none) != bool(self.response_legacy_error):
            raise ValueError(
                "response_attrs_now_none and response_legacy_error are one fact: an attribute "
                "that stopped raising, and what it used to raise. A handler is only recognisable "
                "from both halves"
            )

    def _check_what_a_rewrite_needs_is_declared(self) -> None:
        carrying = sorted(
            method for method, rewrite in self.rewrites.items() if rewrite.history_kwarg
        )
        if carrying and self.history is None:
            raise ValueError(
                f"{carrying} declare a history_kwarg and this rule has no history shape; the "
                f"keyword names an argument whose value is rewritten, and nothing says into what"
            )
        module = self.config_class.rpartition(".")[0]
        for field, symbol in (
            ("safety.setting_class", self.safety.setting_class),
            ("safety.category_class", self.safety.category_class),
            ("safety.threshold_class", self.safety.threshold_class),
        ):
            if symbol.rpartition(".")[0] != module:
                raise ValueError(
                    f"{field} is {symbol!r}, which is not under {module!r}; every class this rule "
                    f"emits is reached through the one name it asks the import manager for, so "
                    f"two modules would need an import nothing requests"
                )

    def _check_receivers_can_be_held(self) -> None:
        for method, receiver in self.method_returns.items():
            owner, _, name = method.rpartition(".")
            if name not in self.methods.get(owner, ()):
                raise ValueError(
                    f"method_returns names {method!r}, which is not a supported method of {owner!r}"
                )
            if receiver not in self.methods:
                raise ValueError(
                    f"method_returns says {method!r} produces {receiver!r}, which has no method "
                    f"list; a receiver the scanner can hold and do nothing with is not one"
                )
            if owner == receiver:
                raise ValueError(
                    f"{method!r} is said to produce the receiver it is called on; a method that "
                    f"returns its own receiver needs no entry"
                )
        unreachable = sorted(
            set(self.methods) - {self.ctor_symbol} - set(self.method_returns.values())
        )
        if unreachable:
            raise ValueError(
                f"nothing in this pack produces {unreachable}: a receiver is held by "
                f"{self.ctor_symbol!r} or returned by a method that says so in method_returns, "
                f"and these are neither, so their methods would never resolve"
            )


class RewriteCallParams(_Closed):
    """One legacy free function and the client call it becomes; unlisted parameters are refused."""

    # A legacy parameter is a new-call argument (`positional_to_kw`, in legacy order), a field of
    # `config_class` (`config_kwargs`), or refused as `unsupported_kwarg`, the safe default.
    legacy_symbol: QualifiedName
    new_call: DottedCall
    # `module` spells `new_call` after the root the author wrote and asks for no client.
    root: RewriteRoot = "client"
    arg_map: dict[PlainName, PlainName] = Field(default_factory=dict)
    positional_to_kw: tuple[PlainName, ...] = ()
    # Legacy parameters carried when written as keywords, so a positional one is still refused.
    keywords: tuple[PlainName, ...] = ()
    config_class: QualifiedName | None = None
    config_kwargs: tuple[PlainName, ...] = ()
    config_kwarg: PlainName | None = None
    result_access_flags: tuple[PlainName, ...] = ()
    # Exceptions only the legacy SDK raises: a handler would never run, so `error_class_changed`.
    legacy_error_modules: tuple[QualifiedName, ...] = ()
    # Legacy-only result fields; reading one refuses the call as `attribute_removed`.
    result_attribute_flags: tuple[PlainName, ...] = ()
    # The only reads of the result that carry: anything else, or the result passed on, is refused.
    result_paths: tuple[ResultPath, ...] = ()
    dispatch_prefixes: dict[PlainName, tuple[LiteralPrefix, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> RewriteCallParams:
        # Legacy parameter order: the one sequence here that must not be sorted.
        _ordered_unique(self.positional_to_kw, "positional_to_kw")
        _sorted_set(self.keywords, "keywords")
        _sorted_set(self.config_kwargs, "config_kwargs")
        _sorted_set(self.result_access_flags, "result_access_flags")
        _sorted_set(self.result_attribute_flags, "result_attribute_flags")
        _sorted_set(self.result_paths, "result_paths")
        _sorted_set(self.legacy_error_modules, "legacy_error_modules")
        declared = {bool(self.config_class), bool(self.config_kwargs), bool(self.config_kwarg)}
        if len(declared) != 1:
            raise ValueError(
                "config_class, config_kwargs and config_kwarg go together: a keyword with no "
                "class to carry it cannot be emitted, a class with no keyword would be emitted "
                "empty, and neither can be passed without the name the new call takes it under"
            )
        self._check_the_result_is_read_one_way()
        self._check_no_parameter_has_two_destinations()
        self._check_every_renamed_parameter_is_one_the_rule_reads()
        self._check_no_two_parameters_land_on_one_keyword()
        self._check_every_dispatching_parameter_is_one_the_rule_reads()
        return self

    def _check_the_result_is_read_one_way(self) -> None:
        if self.result_paths and self.result_access_flags:
            raise ValueError(
                "result_access_flags refuses every use of the result, so result_paths, which "
                "lists the uses that carry, would never be consulted"
            )
        for path in self.result_paths:
            inside = [
                other for other in self.result_paths if other.startswith((f"{path}.", f"{path}[]"))
            ]
            if inside:
                raise ValueError(
                    f"result_paths names {path!r} and {inside[0]!r} below it; a path ends where "
                    f"the read is trusted, so one may not continue another"
                )

    def _check_no_parameter_has_two_destinations(self) -> None:
        both = sorted(set(self.positional_to_kw) & set(self.config_kwargs))
        if both:
            raise ValueError(
                f"{both} is in positional_to_kw and in config_kwargs; a parameter is an argument "
                f"of the new call or a field of its configuration, and a pack that says both "
                f"leaves the rule's own order to decide"
            )
        twice = sorted(set(self.keywords) & {*self.positional_to_kw, *self.config_kwargs})
        if twice:
            raise ValueError(
                f"{twice} is in keywords and also in positional_to_kw or config_kwargs; a "
                f"parameter has one destination"
            )

    def _check_every_renamed_parameter_is_one_the_rule_reads(self) -> None:
        known = {*self.positional_to_kw, *self.keywords, *self.config_kwargs}
        unknown = sorted(set(self.arg_map) - known)
        if unknown:
            raise ValueError(
                f"arg_map renames {unknown}, which positional_to_kw, keywords and config_kwargs "
                f"do not name; a call that passes one is refused as an unsupported keyword "
                f"before the rename is ever read"
            )

    def _check_every_dispatching_parameter_is_one_the_rule_reads(self) -> None:
        known = {*self.positional_to_kw, *self.keywords, *self.config_kwargs}
        unknown = sorted(set(self.dispatch_prefixes) - known)
        if unknown:
            raise ValueError(
                f"dispatch_prefixes names {unknown}, which positional_to_kw, keywords and "
                f"config_kwargs do not; the rule reads an argument by its legacy name, so this "
                f"prefix list is never consulted"
            )
        for parameter, prefixes in sorted(self.dispatch_prefixes.items()):
            if not prefixes:
                raise ValueError(
                    f"dispatch_prefixes[{parameter!r}] is empty, which refuses every call rather "
                    f"than saying which values carry; drop the entry instead"
                )
            _sorted_set(prefixes, f"dispatch_prefixes[{parameter!r}]")

    def _check_no_two_parameters_land_on_one_keyword(self) -> None:
        """After `arg_map`, no two parameters share a keyword: libcst emits that; Python refuses."""
        for field, names in (
            ("positional_to_kw and keywords", (*self.positional_to_kw, *self.keywords)),
            ("config_kwargs", self.config_kwargs),
        ):
            landed = [self.arg_map.get(name, name) for name in names]
            if self.config_kwarg and field != "config_kwargs":
                # The configuration object is an argument of the same call.
                landed.append(self.config_kwarg)
            clashing = sorted({name for name in landed if landed.count(name) > 1})
            if clashing:
                raise ValueError(
                    f"two entries of {field} land on {clashing} once arg_map is applied; the "
                    f"emitted call would name one keyword twice"
                )


class RenameSettingParams(_Closed):
    """Module settings the new release spells another way, assigned as the old ones were."""

    # A legacy attribute by its dotted path, and the name it takes on the same module.
    settings: dict[QualifiedName, PlainName]
    # A string literal lacking it gets it; any other value is written `str(v).rstrip(c) + c`.
    value_ends_with: TrailingCharacter | None = None

    @model_validator(mode="after")
    def _check(self) -> RenameSettingParams:
        if not self.settings:
            raise ValueError("a rename_setting rule must name a setting")
        for key, new in self.settings.items():
            module, dot, name = key.rpartition(".")
            if not dot:
                raise ValueError(
                    f"settings names an attribute of a module, so it is a dotted path: got {key!r}"
                )
            if new == name:
                raise ValueError(f"settings[{key!r}] keeps its name, so there is nothing to rename")
            if f"{module}.{new}" in self.settings:
                raise ValueError(
                    f"settings[{key!r}] is renamed onto {new!r}, which settings renames again"
                )
        return self


class FlagOnlyParams(_Closed):
    """Symbols, string patterns and removed attributes a pack refuses, and what it says instead."""

    # A symbol or pattern reports `flag_only_surface`; an attribute reports `attribute_removed`.
    message: DisplayText
    suggestion: DisplayText
    symbols: tuple[QualifiedName, ...] = ()
    patterns: tuple[FlagOnlyPattern, ...] = ()
    attributes: tuple[QualifiedName, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> FlagOnlyParams:
        if not (self.symbols or self.patterns or self.attributes):
            raise ValueError("a flag_only rule must name a symbol, a pattern or an attribute")
        _sorted_set(self.symbols, "symbols")
        _sorted_set(self.patterns, "patterns")
        _sorted_set(self.attributes, "attributes")
        for attribute in self.attributes:
            if "." not in attribute:
                raise ValueError(
                    f"attributes names an attribute of an object, so it is a dotted path: "
                    f"got {attribute!r}"
                )
        both = sorted(set(self.symbols).intersection(self.attributes))
        if both:
            raise ValueError(f"{both} is named as both a symbol and an attribute")
        return self


class ManifestDependencyParams(_Closed):
    """The pin edit; both names may be one distribution, whose major version is the migration."""

    from_name: DistributionName
    to_name: DistributionName
    to_spec: Pep440Specifier


class _ChangeBase(_Closed):
    id: Slug
    citation: DisplayText
    fixtures: tuple[FixturePath, ...]

    @model_validator(mode="after")
    def _check_base(self) -> _ChangeBase:
        if not self.fixtures:
            raise ValueError("every change must name at least one fixture")
        _sorted_set(self.fixtures, "fixtures")
        return self


class RenameImportChange(_ChangeBase):
    kind: Literal["rename_import"]
    params: RenameImportParams


class ConfigureToClientChange(_ChangeBase):
    kind: Literal["configure_to_client"]
    params: ConfigureToClientParams


class GenerativeModelCallsChange(_ChangeBase):
    kind: Literal["generative_model_calls"]
    params: GenerativeModelCallsParams


class RewriteCallChange(_ChangeBase):
    kind: Literal["rewrite_call"]
    params: RewriteCallParams


class RenameSettingChange(_ChangeBase):
    kind: Literal["rename_setting"]
    params: RenameSettingParams


class FlagOnlyChange(_ChangeBase):
    kind: Literal["flag_only"]
    params: FlagOnlyParams


class ManifestDependencyChange(_ChangeBase):
    kind: Literal["manifest_dependency"]
    params: ManifestDependencyParams


# Discriminated over the whole change, not `params`, so an error lands at
# `changes.<n>.params.<key>` rather than at the union.
Change = Annotated[
    Union[  # noqa: UP007 - pydantic reads the discriminator off a typing.Union
        RenameImportChange,
        ConfigureToClientChange,
        GenerativeModelCallsChange,
        RewriteCallChange,
        RenameSettingChange,
        FlagOnlyChange,
        ManifestDependencyChange,
    ],
    Field(discriminator="kind"),
]


class Layout(_Closed):
    """The maximum line width the pack's rules emit; match it to the user's formatter."""

    line_length: int = Field(default=100, ge=40, le=320)


class Verification(_Closed):
    """Commands a pack suggests as display text; obelize never runs them, under any flag."""

    suggestions: tuple[DisplayText, ...]

    @model_validator(mode="after")
    def _check(self) -> Verification:
        if not self.suggestions:
            raise ValueError("drop the verification block instead of declaring no suggestion")
        _ordered_unique(self.suggestions, "suggestions")
        return self


class PackDocument(_Closed):
    """One migration between two versions of one SDK, as declarative data."""

    # The format is unversioned through 0.x: a version field is refused like any unknown key.
    id: PackId
    pack_version: SemVer
    provider: Slug
    language: Literal["python"]
    source: PackSource
    from_: VersionRange = Field(alias="from")
    to: Target
    match: Match
    changes: tuple[Change, ...]
    limitations: tuple[DisplayText, ...]
    layout: Layout = Field(default_factory=Layout)
    verification: Verification | None = None

    @model_validator(mode="after")
    def _check(self) -> PackDocument:
        if self.id.split("/", 1)[0] != self.provider:
            raise ValueError(
                f"id {self.id!r} must begin with provider {self.provider!r}, so that the id and "
                f"the directory a bundled pack lives in cannot disagree"
            )
        if not self.changes:
            raise ValueError("a pack must declare at least one change")
        if not self.limitations:
            raise ValueError("limitations must list at least one thing the pack does not handle")
        _ordered_unique(self.limitations, "limitations")
        self._check_change_ids()
        self._check_client_source()
        self._check_receivers_and_symbols_are_claimed_once()
        self._check_every_legacy_symbol_is_looked_for()
        self._check_mapped_symbols_are_not_also_refused()
        self._check_a_setting_is_not_renamed_onto_a_legacy_name()
        self._check_manifest_matches_the_migration()
        self._check_version_ranges()
        return self

    def to_modules(self) -> tuple[str, ...]:
        """Every module a `rename_import` writes; empty authorises no new import."""
        return tuple(
            sorted(
                {
                    change.params.to_module
                    for change in self.changes
                    if change.kind == "rename_import"
                }
            )
        )

    def _check_change_ids(self) -> None:
        seen: set[str] = set()
        for change in self.changes:
            if change.id in seen:
                raise ValueError(
                    f"changes[].id must be unique within a pack; {change.id!r} appears twice. "
                    f"The id is written into Edit.rule_id and into the report"
                )
            seen.add(change.id)

    def _check_client_source(self) -> None:
        found = [change.id for change in self.changes if change.kind == "configure_to_client"]
        needing = [
            change.id
            for change in self.changes
            if change.kind == "generative_model_calls"
            or (isinstance(change, RewriteCallChange) and change.params.root == "client")
        ]
        if len(found) > 1 or (needing and not found):
            raise ValueError(
                f"a module has one client source: a pack declares at most one configure_to_client "
                f"change, and exactly one when a change rewrites calls onto the client "
                f"({needing}); found {len(found)}: {found}"
            )

    def _check_receivers_and_symbols_are_claimed_once(self) -> None:
        receivers: set[str] = set()
        for change in self.changes:
            if not isinstance(change, GenerativeModelCallsChange):
                continue
            for receiver in change.params.methods:
                if receiver in receivers:
                    raise ValueError(
                        f"two changes declare the supported methods of {receiver!r}; the "
                        f"projection carries one method list per receiver"
                    )
                receivers.add(receiver)
        rewritten: set[str] = set()
        for change in self.changes:
            if isinstance(change, RewriteCallChange):
                claimed: tuple[str, ...] = (change.params.legacy_symbol,)
            elif isinstance(change, RenameSettingChange):
                claimed = tuple(change.params.settings)
            else:
                continue
            for symbol in claimed:
                if symbol in rewritten:
                    raise ValueError(
                        f"two changes claim {symbol!r}; which one applies would be decided by "
                        f"the order of the list"
                    )
                rewritten.add(symbol)

        refused = {
            symbol
            for change in self.changes
            if isinstance(change, FlagOnlyChange)
            for symbol in (*change.params.symbols, *change.params.attributes)
        }
        contested = sorted(refused.intersection(self.rewritten_symbols()))
        if contested:
            raise ValueError(
                f"{contested} is both rewritten and refused; the order of the rules would decide "
                f"which wins"
            )

    def _check_mapped_symbols_are_not_also_refused(self) -> None:
        """A symbol is mapped or refused, not both; the rename would silently win.

        The lists key it differently (relative name vs qualified), so this is not visible by
        reading.
        """
        refused = {
            symbol
            for change in self.changes
            if isinstance(change, FlagOnlyChange)
            for symbol in change.params.symbols
        }
        for change in self.changes:
            if not isinstance(change, RenameImportChange):
                continue
            contested = sorted(
                key
                for key in change.params.symbol_map
                if f"{change.params.from_module}.{key}" in refused
            )
            if contested:
                raise ValueError(
                    f"changes[{change.id!r}].params.symbol_map maps {contested}, which a "
                    f"flag_only rule refuses; a symbol is mapped or refused, not both"
                )

    def _check_a_setting_is_not_renamed_onto_a_legacy_name(self) -> None:
        """The new name must be one the scan lets pass, or the rewritten file is a finding again."""
        for change in self.changes:
            if not isinstance(change, RenameSettingChange):
                continue
            for key, new in change.params.settings.items():
                landed = f"{key.rpartition('.')[0]}.{new}"
                if under_any(landed, self.match.symbols):
                    raise ValueError(
                        f"changes[{change.id!r}].params.settings[{key!r}] is renamed onto "
                        f"{landed!r}, which match.symbols lists as legacy"
                    )

    def _check_every_legacy_symbol_is_looked_for(self) -> None:
        """A shared module is legacy only where `symbols` says so, so the rules must sit there."""
        field = "match.symbols" if self.match.shared else "match.imports"
        looked = self.match.symbols if self.match.shared else self.match.imports
        for change in self.changes:
            if self.match.shared and change.kind == "rename_import":
                raise ValueError(
                    f"changes[{change.id!r}] renames a module that match.shared says the new SDK "
                    f"keeps; a shared module is rewritten at its calls"
                )
            if not self.match.shared and change.kind == "rename_setting":
                raise ValueError(
                    f"changes[{change.id!r}] renames a setting and keeps its module, which "
                    f"match.shared says; a module that moves is renamed by rename_import"
                )
            for name, symbol in self._legacy_symbols(change):
                # Read for a member, never found as a usage, so no `symbols` entry can be asked.
                if self.match.shared and name.startswith("safety."):
                    continue
                if not under_any(symbol, looked):
                    raise ValueError(
                        f"changes[{change.id!r}].params.{name} names {symbol!r}, which is under "
                        f"nothing in {field} {list(looked)}. Resolution can never produce it, so "
                        f"the rule can never fire"
                    )

    def _check_manifest_matches_the_migration(self) -> None:
        for change in self.changes:
            if not isinstance(change, ManifestDependencyChange):
                continue
            for field, declared, expected in (
                ("from_name", change.params.from_name, self.from_.package),
                ("to_name", change.params.to_name, self.to.package),
            ):
                if canonicalize_name(declared) != canonicalize_name(expected):
                    raise ValueError(
                        f"changes[{change.id!r}].params.{field} is {declared!r}, but the pack "
                        f"migrates {self.from_.package!r} to {self.to.package!r}. A manifest "
                        f"rule that pins a third distribution is not this migration"
                    )

    def _check_version_ranges(self) -> None:
        """Overlap and direction, only within one distribution (a rename may keep the version).

        Overlap is tested at the versions either side names, direction on the bounds: deliberately
        not a full specifier intersection, which `!=` and `~=` make costly.
        """
        if canonicalize_name(self.from_.package) != canonicalize_name(self.to.package):
            return
        source, target = SpecifierSet(self.from_.version), SpecifierSet(self.to.version)
        both = [
            str(version)
            for version in sorted(_named(source) | _named(target))
            if version in source.filter([version]) and version in target.filter([version])
        ]
        if both:
            raise ValueError(
                f"from.version {self.from_.version!r} and to.version {self.to.version!r} both "
                f"admit {both[0]}, so a single installed version would be on both sides of the "
                f"migration"
            )
        floor = bounds(source)[0]
        ceiling = bounds(target)[1]
        if floor is not None and ceiling is not None and ceiling <= floor:
            raise ValueError(
                f"to.version {self.to.version!r} reaches no higher than {ceiling}, which is not "
                f"above {floor} in from.version {self.from_.version!r}: the migration would move "
                f"backwards"
            )

    def rewritten_symbols(self) -> frozenset[str]:
        """Every legacy symbol some rule proposes to change rather than refuse."""
        symbols: set[str] = set()
        for change in self.changes:
            if isinstance(change, ConfigureToClientChange):
                symbols.add(change.params.legacy_symbol)
            elif isinstance(change, GenerativeModelCallsChange):
                symbols.add(change.params.ctor_symbol)
                symbols.add(change.params.legacy_config_symbol)
                symbols.update(change.params.legacy_config_aliases)
                symbols.update(change.params.methods)
            elif isinstance(change, RewriteCallChange):
                symbols.add(change.params.legacy_symbol)
            elif isinstance(change, RenameSettingChange):
                symbols.update(change.params.settings)
        return frozenset(symbols)

    @staticmethod
    def _legacy_symbols(change: Change) -> tuple[tuple[str, str], ...]:
        """The `(field, symbol)` pairs in one change that name legacy code."""
        if isinstance(change, RenameImportChange):
            return (("from_module", change.params.from_module),)
        if isinstance(change, ConfigureToClientChange):
            return (("legacy_symbol", change.params.legacy_symbol),)
        if isinstance(change, GenerativeModelCallsChange):
            return (
                ("ctor_symbol", change.params.ctor_symbol),
                ("legacy_config_symbol", change.params.legacy_config_symbol),
                *(
                    ("legacy_config_aliases", alias)
                    for alias in change.params.legacy_config_aliases
                ),
                *(("methods", receiver) for receiver in change.params.methods),
                # Deliberately not in `match.symbols`: the rule reads a member and discards the
                # node, so a finding for one would be a row no rule claims.
                ("safety.legacy_category_class", change.params.safety.legacy_category_class),
                ("safety.legacy_threshold_class", change.params.safety.legacy_threshold_class),
            )
        if isinstance(change, RewriteCallChange):
            return (("legacy_symbol", change.params.legacy_symbol),)
        if isinstance(change, RenameSettingChange):
            return tuple(("settings", key) for key in change.params.settings)
        if isinstance(change, FlagOnlyChange):
            return (
                *(("symbols", symbol) for symbol in change.params.symbols),
                *(("attributes", attribute) for attribute in change.params.attributes),
            )
        return ()


def _named(specifiers: SpecifierSet) -> set[Version]:
    """The versions a specifier set names; a range is decided at them. Wildcards are skipped."""
    found: set[Version] = set()
    for specifier in specifiers:
        try:
            found.add(Version(specifier.version))
        except InvalidVersion:  # pragma: no cover - `==1.*` and friends
            continue
    return found
