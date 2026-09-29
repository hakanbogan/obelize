"""`generative_model_calls`: `GenerativeModel(...)` and its calls, moved onto the client.

The new SDK has no model object, so its name and configuration go into every call. The unit is a
binding group (the constructor, its calls, and calls on what they produce, such as a chat),
written whole or refused whole.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import libcst as cst
import libcst.matchers as m
from libcst.metadata import Assignment, QualifiedNameProvider, ScopeProvider

from obelize.models import BailCode, Edit
from obelize.transforms import layout
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.imports import dotted
from obelize.transforms.tree import Position, Tree, literal_string

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Sequence

    from obelize.models import Binding, Finding, WarningCode
    from obelize.packs.schema import (
        ChangeKind,
        ChatHistory,
        GenerativeModelCallsChange,
        GenerativeModelCallsParams,
        MethodRewrite,
        SafetySettings,
    )

# A config field: its name and the author's own expression node.
Field = tuple[str, cst.BaseExpression]

# (category, threshold) as new-enum member names, not source nodes: `"hate"` may come out as
# `HARM_CATEGORY_HATE_SPEECH`.
Row = tuple[str, str]

# Bails this rule raises itself, graded as a set. Deliberately absent: the client's bail (from
# `configure_to_client`) and `client_source_unresolved` (unreachable after a scan).
BAILS: frozenset[BailCode] = frozenset(
    {
        "afc_semantics_differ",
        "alias_collision",
        "async_stream_await_missing",
        "count_tokens_config_carries_semantics",
        "ctor_argument_not_portable",
        "default_model_name_required",
        "dynamic_stream_flag",
        "error_class_changed",
        "generation_config_not_static",
        "history_parts_shape_incompatible",
        "model_object_escapes",
        "positional_arg_ambiguous",
        "receiver_method_unmapped",
        "receiver_unresolved",
        "response_shape_changed",
        "safety_settings_not_static",
        "types_import_typing_only",
        "unknown_ctor_kwarg",
        "unsupported_kwarg",
    }
)


@dataclass(frozen=True, slots=True)
class _Config:
    """One object's configuration; per binding, since a chat is created with its own."""

    fields: tuple[Field, ...]
    # In the author's order, keyed by category.
    safety: tuple[Row, ...]
    # The node the fields were written in, whose layout the output copies; `None` if named singly.
    source: cst.CSTNode | None
    safety_source: cst.CSTNode | None
    # The legacy keywords it came from, checked by a call that cannot carry a config.
    names: frozenset[str]


_EMPTY = _Config(fields=(), safety=(), source=None, safety_source=None, names=frozenset())


@dataclass(frozen=True, slots=True)
class _Ctor:
    """What one `GenerativeModel(...)` says, read once for the whole group."""

    model: cst.BaseExpression
    config: _Config
    statement: cst.BaseSmallStatement
    warnings: tuple[WarningCode, ...]


@dataclass(frozen=True, slots=True)
class _Use:
    """One call on a bound receiver, and the rewrite the pack declares for it."""

    position: Position
    call: cst.Call
    rewrite: MethodRewrite
    # Indices into the group's bindings: the one called, and those holding the result.
    owner: int
    produces: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Read:
    """One call's arguments, taken apart and not yet rebuilt."""

    args: tuple[cst.Arg, ...]
    stream: bool | None
    config: cst.BaseExpression | None
    safety: cst.BaseExpression | None
    warnings: tuple[WarningCode, ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    """One use, checked and not yet written."""

    use: _Use
    # Every argument as a keyword.
    args: tuple[cst.Arg, ...]
    # The new method, under the client or the author's receiver.
    target: str
    config: _Config
    warnings: tuple[WarningCode, ...]


@dataclass(frozen=True, slots=True)
class _Group:
    """One constructor, and every call made on what it or its calls produced."""

    position: Position
    call: cst.Call
    # The closure's bindings, the constructor's first.
    bindings: tuple[Binding, ...]
    uses: tuple[_Use, ...]
    refusal: BailCode | None
    # Every claimed finding it decides, config-class calls inside it included.
    governed: tuple[Position, ...]


class GenerativeModelCalls:
    kind: ClassVar[ChangeKind] = "generative_model_calls"

    def __init__(self, change: GenerativeModelCallsChange) -> None:
        self._id = change.id
        self._params: GenerativeModelCallsParams = change.params
        self._safety_of: SafetySettings = change.params.safety
        self._config_module, _, self._config_leaf = change.params.config_class.rpartition(".")
        self._configs = frozenset(
            {change.params.legacy_config_symbol, *change.params.legacy_config_aliases}
        )

    @property
    def consumes(self) -> frozenset[str]:
        """The legacy names replaced whole, so their imports can go."""
        return frozenset({self._params.ctor_symbol, self._params.legacy_config_symbol})

    @property
    def client_readers(self) -> frozenset[str]:
        """Empty: every client call written here is a model's, counted by `needs_client`."""
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        if finding.kind == "call":
            return finding.symbol in {
                self._params.ctor_symbol,
                self._params.legacy_config_symbol,
            }
        if finding.kind == "method_call":
            return finding.symbol in self._params.rewrites
        return False

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        eligible = {
            (finding.line, finding.column): finding
            for finding in context.plan.findings
            if finding.scan_status == "eligible" and self.claims(finding)
        }
        tree = _Tree(context)
        verdicts: dict[Position, BailCode | None] = {}
        warnings: dict[Position, tuple[WarningCode, ...]] = {}
        for group in self._groups(context, tree, eligible):
            try:
                warnings.update(self._rewrite(context, tree, group))
            except BailError as bail:
                verdicts.update(dict.fromkeys(group.governed, bail.reason))
            else:
                verdicts.update(dict.fromkeys(group.governed, None))
        for position, finding in eligible.items():
            if position not in verdicts:
                verdicts[position] = self._orphan(finding)
        return tuple(
            Edit(
                path=context.path,
                line=position[0],
                status="auto" if verdicts[position] is None else "needs_review",
                rule_id=self._id,
                reason=verdicts[position],
                warnings=warnings.get(position, ()),
            )
            for position, finding in sorted(eligible.items())
        )

    def _orphan(self, finding: Finding) -> BailCode:
        """Why a claimed finding is in no group: a loose config object or an unbound constructor."""
        if finding.symbol == self._params.legacy_config_symbol:
            return "generation_config_not_static"
        return "receiver_unresolved"

    def _groups(
        self, context: RuleContext, tree: _Tree, eligible: dict[Position, Finding]
    ) -> list[_Group]:
        """One group per binding with an eligible constructor finding; a chat joins via `_closure`.

        Deliberately no binding-eligibility check: a withheld binding has no eligible constructor.
        """
        groups = []
        for binding in context.plan.bindings:
            position = next(
                (
                    where
                    for where, finding in sorted(eligible.items())
                    if finding.line == binding.ctor_line
                    and finding.symbol == self._params.ctor_symbol
                ),
                None,
            )
            if position is None:
                continue
            call = tree.call(position)
            bindings, uses = self._closure(context, tree, eligible, binding)
            written_in = (call, *(use.call for use in uses))
            groups.append(
                _Group(
                    position=position,
                    call=call,
                    bindings=bindings,
                    uses=uses,
                    refusal=self._refusal(context, tree, bindings, uses),
                    governed=(
                        position,
                        *(use.position for use in uses),
                        *(
                            where
                            for where, finding in sorted(eligible.items())
                            if finding.symbol == self._params.legacy_config_symbol
                            and any(tree.inside(node, where) for node in written_in)
                        ),
                    ),
                )
            )
        return groups

    def _closure(
        self,
        context: RuleContext,
        tree: _Tree,
        eligible: dict[Position, Finding],
        root: Binding,
    ) -> tuple[tuple[Binding, ...], tuple[_Use, ...]]:
        """Every binding `root` reaches, and every call on them.

        Breadth first, so a chat inherits the configuration its creating call emitted.
        """
        bindings: list[Binding] = [root]
        uses: list[_Use] = []
        index = 0
        while index < len(bindings):
            held = bindings[index]
            for finding in sorted(context.plan.findings, key=lambda row: row.sort_key):
                if finding.kind != "method_call" or finding.line not in held.use_lines:
                    continue
                where = (finding.line, finding.column)
                call = tree.call(where)
                if tree.receiver(call) != held.name:
                    continue
                symbol = finding.symbol or ""
                # Followed even without a rewrite, so calls on its product are refused for the
                # real reason, not as unresolved.
                start = len(bindings)
                if symbol in self._params.method_returns:
                    bindings.extend(self._produced(context, tree, call, finding.line))
                rewrite = self._params.rewrites.get(symbol)
                if rewrite is None:
                    continue
                uses.append(
                    _Use(
                        position=where,
                        call=call,
                        rewrite=rewrite,
                        owner=index,
                        produces=tuple(range(start, len(bindings))),
                    )
                )
            index += 1
        return tuple(bindings), tuple(uses)

    def _produced(
        self, context: RuleContext, tree: _Tree, call: cst.Call, line: int
    ) -> list[Binding]:
        """Bindings holding one call's result, read off its assignment as calls may share a line.

        An unassigned result yields none, safely: reaching it needs an unresolved receiver, and the
        scan withholds that file.
        """
        statement = tree.parent(call)
        if not isinstance(statement, cst.Assign):
            return []
        names = {
            layout.render(target.target)
            for target in statement.targets
            if isinstance(target.target, (cst.Name, cst.Attribute))
        }
        return [
            binding
            for binding in context.plan.bindings
            if binding.ctor_line == line and binding.name in names
        ]

    def _refusal(
        self,
        context: RuleContext,
        tree: _Tree,
        bindings: Sequence[Binding],
        uses: Sequence[_Use],
    ) -> BailCode | None:
        """Why the group cannot be written, in ladder order, or `None`.

        A binding's scan code first (reachable under the `dual` import policy only); unmapped
        before escape, as a method with no rewrite has no `_Use` and would read as an escape.
        """
        withheld = next((held.bail for held in bindings if held.bail is not None), None)
        if withheld is not None:
            return withheld
        if any(self._unmapped(context, tree, held) for held in bindings):
            return "receiver_method_unmapped"
        if self._left_behind(tree, bindings[0], uses):
            return "model_object_escapes"
        return None

    def _left_behind(self, tree: _Tree, root: Binding, uses: Sequence[_Use]) -> bool:
        """Whether a reference to the constructor's binding survives its deletion.

        The scan allows comparisons, which would read an unbound name, so each use
        line needs one rewritten use per reference: `MODEL.x(p) if MODEL is not None` fails.
        """
        rewritten = Counter(use.position[0] for use in uses if use.owner == 0)
        return any(
            not rewritten[line] or tree.references(root.name, line) != rewritten[line]
            for line in root.use_lines
        )

    def _unmapped(self, context: RuleContext, tree: _Tree, binding: Binding) -> bool:
        """Whether the receiver calls a method the scan knows and `rewrites` lacks."""
        return any(
            finding.scan_status == "eligible"
            and finding.kind == "method_call"
            and finding.line in binding.use_lines
            and finding.symbol not in self._params.rewrites
            and tree.receiver(tree.call((finding.line, finding.column))) == binding.name
            for finding in context.plan.findings
        )

    def _rewrite(
        self, context: RuleContext, tree: _Tree, group: _Group
    ) -> dict[Position, tuple[WarningCode, ...]]:
        """Check everything, take the config import, then write: a refusal records nothing.

        Refusals keep this order, as the report gives one code: client (a rung above the group),
        group shape (it moots the arguments), constructor, each call in closure order, response
        reads, copied expressions.
        """
        client = context.client.expression
        if client is None:
            raise BailError(context.client.bail or "client_source_unresolved")
        if group.refusal is not None:
            raise BailError(group.refusal)
        ctor = self._constructor(tree, group)
        held: dict[int, _Config] = {0: ctor.config}
        plans: list[_Plan] = []
        for use in group.uses:
            plan = self._plan(tree, held.get(use.owner, _EMPTY), use)
            plans.append(plan)
            for produced in use.produces:
                held[produced] = plan.config
        self._check_the_response_is_still_read_the_old_way(tree, group)
        self._check_what_the_constructor_wrote_travels(tree, group, ctor, plans)
        alias = None
        if any(plan.config.fields or plan.config.safety for plan in plans):
            alias = context.imports.require(self._config_module)
            if alias is None:
                raise BailError(context.imports.refusal(self._config_module))
        for plan in plans:
            emitted = self._emit(context, tree, client, ctor, plan, alias)
            context.rewrites.set(plan.use.call, emitted)
        self._drop(context, tree, ctor.statement)
        return {
            group.position: ctor.warnings,
            **{plan.use.position: plan.warnings for plan in plans},
        }

    def _check_what_the_constructor_wrote_travels(
        self, tree: _Tree, group: _Group, ctor: _Ctor, plans: Sequence[_Plan]
    ) -> None:
        """Refuse unless each copied constructor expression means the same at every call.

        Nothing in it may run, and each name must bind the same at both places (an `__init__`
        parameter or a local rebound later does not). Safety rows are rebuilt, so unchecked.
        """
        copied = [ctor.model, *(value for _name, value in ctor.config.fields)]
        for plan in plans:
            if not all(tree.travels(value, group.call, plan.use.call) for value in copied):
                raise BailError("ctor_argument_not_portable")

    def _constructor(self, tree: _Tree, group: _Group) -> _Ctor:
        """Read `GenerativeModel(...)` once for the group, or refuse it."""
        named, warnings = self._ctor_arguments(group.call)
        refused = sorted(set(named) & set(self._params.ctor_afc_kwargs))
        if refused:
            raise BailError("afc_semantics_differ")
        placed = {
            self._params.ctor_model_kwarg,
            self._params.legacy_config_kwarg,
            self._safety_of.legacy_kwarg,
            *self._params.ctor_config_fields,
        }
        if set(named) - placed:
            raise BailError("unknown_ctor_kwarg")
        model = named.get(self._params.ctor_model_kwarg)
        if model is None:
            raise BailError("default_model_name_required")
        if self._prefixed(model):
            warnings = (*warnings, "model_name_looks_prefixed")
        statement = tree.parent(group.call)
        if not isinstance(  # pragma: no cover - the binding pass records assignments only
            statement, (cst.Assign, cst.AnnAssign)
        ):
            raise BailError("receiver_unresolved")
        return _Ctor(
            model=model,
            config=self._config(tree, named),
            statement=statement,
            warnings=tuple(sorted(warnings)),
        )

    def _ctor_arguments(
        self, call: cst.Call
    ) -> tuple[dict[str, cst.BaseExpression], tuple[WarningCode, ...]]:
        """The constructor's arguments by legacy parameter name.

        Positionals map through `ctor_order` (`safety_settings` precedes `generation_config`) and
        warn past index zero. A literal `None` is absent, as every legacy default is, so
        `GenerativeModel("m", None, config)` rewrites.
        """
        order = self._params.ctor_order
        named: dict[str, cst.BaseExpression] = {}
        index = 0
        warnings: tuple[WarningCode, ...] = ()
        for argument in call.args:
            if argument.star:
                raise BailError("unknown_ctor_kwarg")
            if argument.keyword is None:
                if index >= len(order):
                    raise BailError("positional_arg_ambiguous")
                name = order[index]
                if index > 0:
                    warnings = ("positional_args_mapped_by_index",)
                index += 1
            else:
                name = argument.keyword.value
            if name in named:
                raise BailError("positional_arg_ambiguous")
            if not _is_none(argument.value):
                named[name] = argument.value
        return named, warnings

    def _prefixed(self, model: cst.BaseExpression) -> bool:
        """Whether the model literal carries the resource-name prefix."""
        if not isinstance(model, cst.SimpleString):
            return False
        value = model.evaluated_value
        return isinstance(value, str) and value.startswith(self._params.model_name_prefix)

    def _config(self, tree: _Tree, named: dict[str, cst.BaseExpression]) -> _Config:
        """Config parameters in legacy order, then the config object's keys as written, then safety.

        Safety is rebuilt rather than carried, so it goes below the author's own spellings.
        """
        fields: list[Field] = [
            (name, named[name])
            for name in self._params.ctor_order
            if name in self._params.ctor_config_fields and name in named
        ]
        names = {name for name, _ in fields}
        source = named.get(self._params.legacy_config_kwarg)
        if source is not None:
            fields.extend(self._keys(tree, source))
            names.add(self._params.legacy_config_kwarg)
        safety_source = named.get(self._safety_of.legacy_kwarg)
        safety: tuple[Row, ...] = ()
        if safety_source is not None:
            safety = tuple(_merged((), self._safety(tree, safety_source)))
            names.add(self._safety_of.legacy_kwarg)
        return _Config(
            fields=tuple(fields),
            safety=safety,
            source=source,
            safety_source=safety_source,
            names=frozenset(names),
        )

    def _keys(self, tree: _Tree, node: cst.BaseExpression) -> list[Field]:
        """Config keys from the legacy config class or a dict literal; any other shape is refused.

        A dict was never validated, so an illegal key is refused, not carried into a class that
        accepts it.
        """
        if isinstance(node, cst.Call) and tree.qualified(node.func) in self._configs:
            return [self._field(argument.keyword, argument) for argument in node.args]
        if isinstance(node, cst.Dict):
            return [self._entry(element) for element in node.elements]
        raise BailError("generation_config_not_static")

    def _field(self, name: cst.Name | None, argument: cst.Arg) -> Field:
        if name is None or argument.star:
            raise BailError("generation_config_not_static")
        return (self._legal(name.value), argument.value)

    def _entry(self, element: cst.BaseDictElement) -> Field:
        if not isinstance(element, cst.DictElement):
            raise BailError("generation_config_not_static")
        key = element.key
        value = key.evaluated_value if isinstance(key, cst.SimpleString) else None
        if not isinstance(value, str):
            raise BailError("generation_config_not_static")
        return (self._legal(value), element.value)

    def _legal(self, name: str) -> str:
        if name not in self._params.generation_config_keys:
            raise BailError("generation_config_not_static")
        return name

    def _safety(self, tree: _Tree, node: cst.BaseExpression) -> list[Row]:
        """Safety rows from a category-to-threshold dict or a list of row dicts, else refused.

        Checked against the pack's tables: the new enums accept an unknown member with a warning.
        """
        if isinstance(node, cst.Dict):
            return [self._pair(tree, element) for element in node.elements]
        if isinstance(node, (cst.List, cst.Tuple)):
            return [self._row(tree, element) for element in node.elements]
        raise BailError("safety_settings_not_static")

    def _pair(self, tree: _Tree, element: cst.BaseDictElement) -> Row:
        if not isinstance(element, cst.DictElement):
            raise BailError("safety_settings_not_static")
        return (self._category(tree, element.key), self._threshold(tree, element.value))

    def _row(self, tree: _Tree, element: cst.BaseElement) -> Row:
        """One `{"category": ..., "threshold": ...}` of the list form."""
        if not isinstance(element, cst.Element) or not isinstance(element.value, cst.Dict):
            raise BailError("safety_settings_not_static")
        # A non-literal key becomes `None` and fails the key-set check below; a repeated key keeps
        # the later value, as Python does.
        written: dict[str | None, cst.BaseExpression] = {}
        for entry in element.value.elements:
            if not isinstance(entry, cst.DictElement):
                raise BailError("safety_settings_not_static")
            written[literal_string(entry.key)] = entry.value
        wanted = {self._safety_of.legacy_category_key, self._safety_of.legacy_threshold_key}
        if set(written) != wanted:
            raise BailError("safety_settings_not_static")
        return (
            self._category(tree, written[self._safety_of.legacy_category_key]),
            self._threshold(tree, written[self._safety_of.legacy_threshold_key]),
        )

    def _category(self, tree: _Tree, node: cst.BaseExpression) -> str:
        return self._member(
            tree,
            node,
            self._safety_of.category_map,
            self._safety_of.category_members,
            self._safety_of.legacy_category_class,
        )

    def _threshold(self, tree: _Tree, node: cst.BaseExpression) -> str:
        return self._member(
            tree,
            node,
            self._safety_of.threshold_map,
            self._safety_of.threshold_members,
            self._safety_of.legacy_threshold_class,
        )

    def _member(
        self,
        tree: _Tree,
        node: cst.BaseExpression,
        table: dict[str, str],
        members: Sequence[str],
        legacy_class: str,
    ) -> str:
        """The new enum member one half of a safety row names.

        Strings are looked up lower-cased, as the legacy SDK did, and enum members kept by name: so
        `HarmBlockThreshold.OFF` is rewritable but `"off"`, which already raised `KeyError`, is not.
        """
        written = literal_string(node)
        if written is not None:
            found = table.get(written.lower())
            if found is None:
                raise BailError("safety_settings_not_static")
            return found
        if (
            isinstance(node, cst.Attribute)
            and tree.qualified(node.value) == legacy_class
            and node.attr.value in members
        ):
            return node.attr.value
        raise BailError("safety_settings_not_static")

    def _table(
        self, rows: Sequence[Row], alias: str, indent: str, unit: str, width: int
    ) -> list[cst.BaseExpression]:
        """Each safety row as the new SDK's object, at the indent the list would wrap to."""
        return [
            layout.call(
                None,
                self._named(alias, self._safety_of.setting_class),
                [
                    layout.keyword(
                        self._safety_of.category_kwarg,
                        cst.Attribute(
                            value=self._named(alias, self._safety_of.category_class),
                            attr=cst.Name(category),
                        ),
                    ),
                    layout.keyword(
                        self._safety_of.threshold_kwarg,
                        cst.Attribute(
                            value=self._named(alias, self._safety_of.threshold_class),
                            attr=cst.Name(threshold),
                        ),
                    ),
                ],
                indent=indent,
                unit=unit,
                width=width,
                # Only the trailing comma sits beside a list row.
                around=1,
            )
            for category, threshold in rows
        ]

    @staticmethod
    def _named(alias: str, symbol: str) -> cst.BaseExpression:
        """`symbol`'s leaf, under the alias the import manager bound."""
        return cst.Attribute(value=cst.Name(alias), attr=cst.Name(symbol.rpartition(".")[2]))

    def _history(self, node: cst.BaseExpression) -> tuple[cst.BaseExpression, bool]:
        """A list of `{"role": ..., "parts": [...]}` dicts reshaped, and whether anything changed.

        The new SDK rejects bare string parts at the first message, not at import, so any shape
        this cannot reshape is refused.
        """
        shape = self._params.history
        if shape is None or not isinstance(node, cst.List):
            raise BailError("history_parts_shape_incompatible")
        rewrote = False
        elements: list[cst.BaseElement] = []
        for element in node.elements:
            if not isinstance(element, cst.Element) or not isinstance(element.value, cst.Dict):
                raise BailError("history_parts_shape_incompatible")
            turn, changed = self._turn(element.value, shape)
            rewrote = rewrote or changed
            elements.append(element.with_changes(value=turn))
        return node.with_changes(elements=elements), rewrote

    def _contents(
        self, tree: _Tree, rewrite: MethodRewrite, node: cst.BaseExpression
    ) -> tuple[cst.BaseExpression, bool]:
        """What the model is asked; an inline list of turns is reshaped like a history.

        Refused: a single turn, a name filled with a mapping elsewhere, and turns sent to a chat,
        whose message is parts, never turns.
        """
        if isinstance(node, cst.Dict) or tree.filled(node):
            raise BailError("history_parts_shape_incompatible")
        if isinstance(node, cst.List) and any(
            isinstance(element.value, cst.Dict) for element in node.elements
        ):
            if rewrite.root == "receiver":
                raise BailError("history_parts_shape_incompatible")
            return self._history(node)
        return node, False

    def _turn(self, node: cst.Dict, shape: ChatHistory) -> tuple[cst.Dict, bool]:
        """One entry of the history: a role both SDKs take, and its parts."""
        # As in `_row`: a non-literal key becomes `None` and fails the key-set check below.
        written: dict[str | None, cst.DictElement] = {}
        for entry in node.elements:
            if not isinstance(entry, cst.DictElement):
                raise BailError("history_parts_shape_incompatible")
            written[literal_string(entry.key)] = entry
        if set(written) != {shape.role_key, shape.parts_key}:
            raise BailError("history_parts_shape_incompatible")
        if literal_string(written[shape.role_key].value) not in shape.roles:
            raise BailError("history_parts_shape_incompatible")
        holder = written[shape.parts_key]
        parts, rewrote = self._parts(holder.value, holder.key, shape)
        return (
            node.with_changes(
                elements=[
                    entry.with_changes(value=parts) if entry is holder else entry
                    for entry in node.elements
                ]
            ),
            rewrote,
        )

    def _parts(
        self, node: cst.BaseExpression, key: cst.BaseExpression, shape: ChatHistory
    ) -> tuple[cst.BaseExpression, bool]:
        """One turn's parts with string literals wrapped; a name may hold a `Part`, so refused."""
        if not isinstance(node, cst.List):
            raise BailError("history_parts_shape_incompatible")
        rewrote = False
        elements: list[cst.BaseElement] = []
        for element in node.elements:
            if not isinstance(element, cst.Element):
                raise BailError("history_parts_shape_incompatible")
            part = element.value
            if isinstance(part, (cst.SimpleString, cst.FormattedString)):
                elements.append(element.with_changes(value=_wrapped(part, key, shape.text_key)))
                rewrote = True
            elif isinstance(part, cst.Dict) and self._already_text(part, shape):
                elements.append(element)
            else:
                raise BailError("history_parts_shape_incompatible")
        return node.with_changes(elements=elements), rewrote

    @staticmethod
    def _already_text(part: cst.Dict, shape: ChatHistory) -> bool:
        """Whether a mapping part is the one-key shape the new SDK wants."""
        if len(part.elements) != 1:
            return False
        only = part.elements[0]
        return isinstance(only, cst.DictElement) and literal_string(only.key) == shape.text_key

    def _plan(self, tree: _Tree, base: _Config, use: _Use) -> _Plan:
        if tree.caught(use.call, frozenset(self._params.legacy_error_modules)):
            raise BailError("error_class_changed")
        read = self._call_arguments(tree, use)
        target, streaming = use.rewrite.new_call, False
        if read.stream is True:
            if use.rewrite.stream_call is None:
                raise BailError("unsupported_kwarg")
            target, streaming = use.rewrite.stream_call, True
            if not tree.iterated(use.call):
                raise BailError("response_shape_changed")
        own_fields = self._keys(tree, read.config) if read.config is not None else []
        own_safety = self._safety(tree, read.safety) if read.safety is not None else []
        config = self._carried(base, read, own_fields, own_safety, use)
        warnings = read.warnings
        if use.rewrite.config_kwarg is None:
            if base.names & set(use.rewrite.semantic_kwargs):
                raise BailError("count_tokens_config_carries_semantics")
            if config.fields or config.safety:
                warnings = (*warnings, "count_tokens_config_dropped")
            config = _EMPTY
        if use.rewrite.coroutine and streaming:
            warnings = (*warnings, *self._await(tree, use))
        return _Plan(
            use=use,
            args=read.args,
            target=target,
            config=config,
            warnings=warnings,
        )

    def _carried(
        self,
        base: _Config,
        read: _Read,
        own_fields: list[Field],
        own_safety: list[Row],
        use: _Use,
    ) -> _Config:
        """This call's `config=`: the legacy key-by-key merge, call winning.

        On a receiver the new SDK replaces the object's config instead of merging: pass nothing,
        or restate every key.
        """
        if use.rewrite.root == "receiver" and not (own_fields or own_safety):
            return _EMPTY
        return _Config(
            fields=tuple(_merged(base.fields, own_fields)),
            safety=tuple(_merged(base.safety, own_safety)),
            source=read.config if read.config is not None else base.source,
            safety_source=read.safety if read.safety is not None else base.safety_source,
            names=base.names | self._stated(read),
        )

    def _stated(self, read: _Read) -> frozenset[str]:
        """The legacy keywords this call's own configuration came from."""
        return frozenset(
            {self._params.legacy_config_kwarg} if read.config is not None else set()
        ) | frozenset({self._safety_of.legacy_kwarg} if read.safety is not None else set())

    def _call_arguments(self, tree: _Tree, use: _Use) -> _Read:
        """One call's arguments as keywords, renamed by `arg_map` for the keyword-only new method.

        Positionals become keywords before `model=` is prepended, or `CSTValidationError` loses
        the whole file.
        """
        rewrite = use.rewrite
        positional = rewrite.positional_to_kw
        args: list[cst.Arg] = []
        given: set[str] = set()
        index = 0
        stream: bool | None = None
        config: cst.BaseExpression | None = None
        safety: cst.BaseExpression | None = None
        warnings: tuple[WarningCode, ...] = ()
        for argument in use.call.args:
            if argument.star:
                raise BailError("unsupported_kwarg")
            if argument.keyword is None:
                if index >= len(positional):
                    raise BailError("positional_arg_ambiguous")
                name = positional[index]
                index += 1
            else:
                name = argument.keyword.value
            if name == self._params.stream_kwarg:
                stream = _literal_flag(argument.value)
                continue
            if name == self._params.legacy_config_kwarg:
                config = argument.value
                continue
            if name == self._safety_of.legacy_kwarg:
                safety = argument.value
                continue
            if name in rewrite.afc_kwargs:
                raise BailError("afc_semantics_differ")
            if name == rewrite.history_kwarg:
                value, rewrote = self._history(argument.value)
                if rewrote:
                    warnings = ("history_parts_rewritten",)
                args.append(layout.keyword(name, value))
                continue
            if name not in positional:
                raise BailError("unsupported_kwarg")
            if name in given:
                raise BailError("positional_arg_ambiguous")
            given.add(name)
            value = argument.value
            if name == rewrite.contents_kwarg:
                value, rewrote = self._contents(tree, rewrite, value)
                if rewrote:
                    warnings = ("history_parts_rewritten",)
            args.append(layout.keyword(rewrite.arg_map.get(name, name), value))
        return _Read(
            args=tuple(args), stream=stream, config=config, safety=safety, warnings=warnings
        )

    def _await(self, tree: _Tree, use: _Use) -> tuple[WarningCode, ...]:
        """Keep an async stream call's `await`; refuse a `for`, async or not, over it without one.

        A coroutine is not iterable, so that `for` was already broken, and dropping the `await`
        raises `TypeError`. Coroutine methods only: a sync stream in a `for` is correct.
        """
        parent = tree.parent(use.call)
        if isinstance(parent, cst.Await):
            return ("async_stream_await_preserved",)
        if isinstance(parent, cst.For):
            raise BailError("async_stream_await_missing")
        return ()

    def _emit(
        self,
        context: RuleContext,
        tree: _Tree,
        client: str,
        ctor: _Ctor,
        plan: _Plan,
        alias: str | None,
    ) -> cst.Call:
        """The call that replaces one use, laid out at the line it sits on."""
        unit = context.module.default_indent
        width = context.layout.line_length
        indent = tree.indent(plan.use.call)
        args = list(plan.args)
        if plan.use.rewrite.root == "client":
            args.insert(0, layout.keyword(self._params.model_kwarg, ctor.model))
        keyword = plan.use.rewrite.config_kwarg
        if alias is not None and keyword is not None and (plan.config.fields or plan.config.safety):
            args.append(
                layout.keyword(
                    keyword,
                    self._configuration(plan, alias, indent + unit, unit, width, len(keyword) + 2),
                )
            )
        return layout.call(
            plan.use.call,
            self._rooted(client, plan),
            args,
            indent=indent,
            unit=unit,
            width=width,
            around=tree.around(plan.use.call),
        )

    def _rooted(self, client: str, plan: _Plan) -> cst.BaseExpression:
        """The client, or the author's receiver node, where the schema keeps `new_call` one name."""
        if plan.use.rewrite.root == "client":
            return dotted(f"{client}.{plan.target}")
        func = plan.use.call.func
        receiver = (  # pragma: no branch - a method call has a receiver
            func.value if isinstance(func, cst.Attribute) else func
        )
        return cst.Attribute(value=receiver, attr=cst.Name(plan.target))

    def _configuration(
        self, plan: _Plan, alias: str, indent: str, unit: str, width: int, around: int
    ) -> cst.Call:
        """One call's config object, rebuilt per call: hoisting needs a name no scope anchors."""
        args = [layout.keyword(name, value) for name, value in plan.config.fields]
        if plan.config.safety:
            args.append(
                layout.keyword(
                    self._safety_of.config_field,
                    layout.sequence(
                        plan.config.safety_source,
                        self._table(plan.config.safety, alias, indent + unit + unit, unit, width),
                        indent=indent + unit,
                        unit=unit,
                        width=width,
                        # `<field>=` in front, a comma behind.
                        around=len(self._safety_of.config_field) + 2,
                    ),
                )
            )
        return layout.call(
            plan.config.source,
            cst.Attribute(value=cst.Name(alias), attr=cst.Name(self._config_leaf)),
            args,
            indent=indent,
            unit=unit,
            width=width,
            around=around,
        )

    def _drop(self, context: RuleContext, tree: _Tree, statement: cst.BaseSmallStatement) -> None:
        """Delete the constructor, handing its leading comment to what follows.

        The next statement keeps its own blank lines and gains only the comment; at a block's end
        the constructor's blank lines come too.
        """
        context.rewrites.drop(statement)
        line = tree.line_of(statement)
        if line is None or len(line.body) > 1:
            return
        first = next(
            (index for index, empty in enumerate(line.leading_lines) if empty.comment is not None),
            None,
        )
        if first is None:
            return
        target = tree.after(line)
        keeps_the_blanks = isinstance(target, (cst.Module, cst.IndentedBlock))
        context.rewrites.lead(target, tuple(line.leading_lines[0 if keeps_the_blanks else first :]))

    def _check_the_response_is_still_read_the_old_way(self, tree: _Tree, group: _Group) -> None:
        """Refuse a read, now `None` where it raised, guarded by a handler naming the old error.

        E.g. `response.text` raised `ValueError`, so the handler would silently never run.
        """
        if not self._params.response_attrs_now_none:
            return
        reads = _handled_reads(
            tree.module,
            self._params.response_legacy_error or "",
            frozenset(self._params.response_attrs_now_none),
        )
        held = {id(use.call) for use in group.uses}
        names = _bound_by(tree, group)
        for value in reads:
            if id(value) in held:
                raise BailError("response_shape_changed")
            if isinstance(value, cst.Name) and value.value in names:
                raise BailError("response_shape_changed")


class _Tree(Tree):
    """The shared index, plus qualified names and scopes."""

    def __init__(self, context: RuleContext) -> None:
        super().__init__(context, [QualifiedNameProvider, ScopeProvider])
        self._scopes = context.wrapper.resolve(ScopeProvider)
        self._named: dict[int, list[cst.Name | cst.Attribute]] = {}
        for node in self._pos:
            if isinstance(node, cst.Name | cst.Attribute):
                self._named.setdefault(self.start(node)[0], []).append(node)

    def references(self, name: str, line: int) -> int:
        """How many expressions starting on `line` are the binding `name` (not `config.MODEL`).

        Assignment targets and keyword names count, which can only refuse: the scan withholds a
        name assigned twice.
        """
        return sum(
            1
            for node in self._named.get(line, ())
            if layout.render(node) == name
            and not (isinstance(parent := self.parent(node), cst.Attribute) and parent.attr is node)
        )

    def travels(self, value: cst.BaseExpression, source: cst.Call, target: cst.Call) -> bool:
        """Whether `value` runs nothing and each name in it has one assignment, the same at both."""
        reads = _Pasted()
        value.visit(reads)
        if reads.runs:
            return False
        here, there = self._scopes[source], self._scopes[target]
        for name in reads.names:
            found = here[name] if here is not None else set()
            if len(found) != 1 or there is None or there[name] != found:
                return False
        return True

    def filled(self, node: cst.BaseExpression) -> bool:
        """Whether name `node` gets a dict from its binding or a method call (`x.append({...})`)."""
        if not isinstance(node, cst.Name):
            return False
        scope = self._scopes[node]
        found = scope[node.value] if scope is not None else set()
        places: list[cst.CSTNode] = []
        for assignment in found:
            if not isinstance(assignment, Assignment):
                continue
            line = self.line_of(assignment.node)
            if line is not None:
                places.append(line)
            for access in assignment.references:
                parent = self.parent(access.node)
                if isinstance(parent, cst.Attribute):
                    places.append(self.parent(parent))
        return any(m.findall(place, m.Dict()) for place in places)

    def iterated(self, call: cst.Call) -> bool:
        """Whether the rewritten result, a chunk generator, is only ever a `for` loop's iterable."""
        match self.consumer(call):
            case cst.For():
                return True
            case cst.Assign(targets=[cst.AssignTarget(target=cst.Name() as target)]):
                scope = self._scopes[target]
                found = scope[target.value] if scope is not None else set()
                return len(found) == 1 and all(
                    isinstance(self.parent(access.node), cst.For)
                    for assignment in found
                    for access in assignment.references
                )
        return False

    def receiver(self, call: cst.Call) -> str:
        """How the receiver of a method call is spelled in the source."""
        func = call.func
        if not isinstance(func, cst.Attribute):  # pragma: no cover - a method call has a receiver
            return ""
        return layout.render(func.value)

    def after(self, line: cst.SimpleStatementLine) -> cst.CSTNode:
        """The statement written after `line`, or the block it is the last of."""
        block = self.parent(line)
        if not isinstance(block, (cst.Module, cst.IndentedBlock)):  # pragma: no cover - two shapes
            return block
        body = list(block.body)
        index = next(row for row, node in enumerate(body) if node is line)
        return body[index + 1] if index + 1 < len(body) else block


# Nodes that make reading an expression run something; not a lambda, since making one runs nothing.
_RUNS = (
    cst.Call,
    cst.Await,
    cst.ListComp,
    cst.SetComp,
    cst.DictComp,
    cst.GeneratorExp,
    cst.NamedExpr,
    cst.Yield,
)


class _Pasted(cst.CSTVisitor):
    """The names an expression reads, and whether reading it runs anything."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []
        self.runs = False

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, _RUNS):
            self.runs = True
            return False
        return super().on_visit(node)

    def visit_Name(self, node: cst.Name) -> None:  # noqa: N802 - libcst dispatches by name
        self.names.append(node.value)

    def visit_Attribute(self, node: cst.Attribute) -> bool:  # noqa: N802 - libcst dispatches by name
        # The attribute's own name reads no binding.
        node.value.visit(self)
        return False


def _merged[Value](
    base: Sequence[tuple[str, Value]], overrides: Sequence[tuple[str, Value]]
) -> list[tuple[str, Value]]:
    """The legacy SDK's merge: an override replaces a shared key in place, a new key appends."""
    fields = list(base)
    for name, value in overrides:
        index = next((row for row, (held, _) in enumerate(fields) if held == name), None)
        if index is None:
            fields.append((name, value))
        else:
            fields[index] = (name, value)
    return fields


def _wrapped(part: cst.BaseExpression, key: cst.BaseExpression, text: str) -> cst.Dict:
    """One bare string part as the new SDK's mapping, its key quoted like the author's `key`."""
    quote = key.quote if isinstance(key, cst.SimpleString) else '"'
    named = cst.SimpleString(f"{quote}{text}{quote}")
    return cst.Dict(elements=[cst.DictElement(key=named, value=part)])


def _is_none(node: cst.BaseExpression) -> bool:
    return isinstance(node, cst.Name) and node.value == "None"


def _literal_flag(node: cst.BaseExpression) -> bool:
    """A literal `True` or `False`, else refused: the two values call different methods."""
    if isinstance(node, cst.Name) and node.value in {"True", "False"}:
        return node.value == "True"
    raise BailError("dynamic_stream_flag")


def _bound_by(tree: _Tree, group: _Group) -> frozenset[str]:
    """The plain names this group's calls are assigned to."""
    names: set[str] = set()
    for use in group.uses:
        statement = tree.parent(use.call)
        if not isinstance(statement, cst.Assign):
            continue
        names.update(
            target.target.value
            for target in statement.targets
            if isinstance(target.target, cst.Name)
        )
    return frozenset(names)


def _handled_reads(
    module: cst.Module, error: str, attributes: frozenset[str]
) -> list[cst.BaseExpression]:
    """Everything read as one of `attributes` inside a `try` that names `error`."""
    found = _Handled(error, attributes)
    module.visit(found)
    return found.reads


class _Handled(cst.CSTVisitor):
    def __init__(self, error: str, attributes: frozenset[str]) -> None:
        super().__init__()
        self._error = error
        self._attributes = attributes
        self.reads: list[cst.BaseExpression] = []

    def visit_Try(self, node: cst.Try) -> bool:  # noqa: N802 - libcst dispatch
        if any(self._names(handler.type) for handler in node.handlers):
            reads = _Reads(self._attributes)
            node.body.visit(reads)
            self.reads.extend(reads.found)
        return True

    def _names(self, node: cst.BaseExpression | None) -> bool:
        if isinstance(node, cst.Name):
            return node.value == self._error
        if isinstance(node, cst.Tuple):
            return any(self._names(element.value) for element in node.elements)
        return False


class _Reads(cst.CSTVisitor):
    """Every expression one of a set of attributes is read on."""

    def __init__(self, attributes: frozenset[str]) -> None:
        super().__init__()
        self._attributes = attributes
        self.found: list[cst.BaseExpression] = []

    def visit_Attribute(self, node: cst.Attribute) -> None:  # noqa: N802 - libcst dispatch
        if node.attr.value in self._attributes:
            self.found.append(node.value)
