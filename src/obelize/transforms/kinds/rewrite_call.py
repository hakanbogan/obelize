"""`rewrite_call`: a legacy free function becomes a call on the client, one rule per pack change.

Only `positional_to_kw` (the new call's own arguments, in legacy order) and `config_kwargs` (the
configuration object) carry; any other keyword is refused, never passed to a method that lacks it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import libcst as cst
from libcst.metadata import ScopeProvider

from obelize.models import BailCode, Edit
from obelize.transforms import layout
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.imports import dotted
from obelize.transforms.tree import Position, Tree, literal_string

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RewriteCallChange, RewriteCallParams

# A configuration field by its new name, and the author's node, moved rather than rebuilt.
Field = tuple[str, cst.BaseExpression]

# Codes this rule raises itself, graded as a set by the corpus. The client codes it passes on
# (`configure_to_client`'s, `client_source_unresolved`) are deliberately not here.
BAILS: frozenset[BailCode] = frozenset(
    {
        "alias_collision",
        "attribute_removed",
        "error_class_changed",
        "positional_arg_ambiguous",
        "response_shape_changed",
        "types_import_typing_only",
        "unsupported_kwarg",
    }
)


@dataclass(frozen=True, slots=True)
class _Read:
    """One legacy call's arguments, sorted into where each of them goes."""

    # The new call's arguments, already renamed and keyword.
    args: tuple[cst.Arg, ...]
    # Configuration fields, in written order.
    config: tuple[Field, ...]
    # Every argument by its legacy parameter name, which `dispatch_prefixes` is keyed on.
    given: dict[str, cst.BaseExpression]


class RewriteCall:
    kind: ClassVar[ChangeKind] = "rewrite_call"

    def __init__(self, change: RewriteCallChange) -> None:
        self._id = change.id
        self._params: RewriteCallParams = change.params
        module, _, leaf = (change.params.config_class or "").rpartition(".")
        self._config_module, self._config_leaf = module, leaf
        # Empty only with no configuration class, which the schema ties to no `config_kwargs`.
        self._config_kwarg = change.params.config_kwarg or ""

    @property
    def consumes(self) -> frozenset[str]:
        """The one symbol this rule replaces whole, so an import of it can go."""
        return frozenset({self._params.legacy_symbol})

    @property
    def client_readers(self) -> frozenset[str]:
        """The call becomes a client call, so the client must be placed where it can see it."""
        return frozenset({self._params.legacy_symbol})

    def claims(self, finding: Finding) -> bool:
        return finding.kind == "call" and finding.symbol == self._params.legacy_symbol

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        """Every call of this rule's symbol, each decided alone: a free function holds no state.

        Other calls are still rewritten around a refusal; atomicity keeps that file off disk.
        """
        eligible = sorted(
            (finding.line, finding.column)
            for finding in context.plan.findings
            if finding.scan_status == "eligible" and self.claims(finding)
        )
        if not eligible:
            # Most rules of this kind have no work in a given file; skip building the index.
            return ()
        tree = _Tree(context)
        return tuple(self._edit(context, tree, position) for position in eligible)

    def _edit(self, context: RuleContext, tree: _Tree, position: Position) -> Edit:
        try:
            self._rewrite(context, tree, position)
        except BailError as bail:
            return Edit(
                path=context.path,
                line=position[0],
                status="needs_review",
                rule_id=self._id,
                reason=bail.reason,
            )
        return Edit(path=context.path, line=position[0], status="auto", rule_id=self._id)

    def _rewrite(self, context: RuleContext, tree: _Tree, position: Position) -> None:
        """Record what replaces one call, or raise the one code that refuses it.

        Asked in precedence order, as `generative_model_calls` does: the client (the planner's code,
        raised here as the projection misses free functions), arguments, result, then surroundings.
        """
        call = tree.call(position)
        client = context.client.expression
        if client is None:
            raise BailError(context.client.bail or "client_source_unresolved")
        read = self._arguments(call)
        self._check_the_answer_is_the_one_the_new_call_gives(tree, call, read)
        if tree.caught(call, frozenset(self._params.legacy_error_modules)):
            raise BailError("error_class_changed")
        args = list(read.args)
        if read.config:
            alias = context.imports.require(self._config_module)
            if alias is None:
                # No usable name for the configuration module; reuse the import manager's reason.
                raise BailError(context.imports.refusal(self._config_module))
            args.append(
                layout.keyword(
                    self._config_kwarg,
                    self._configuration(context, tree, call, alias, read.config),
                )
            )
        context.rewrites.set(
            call,
            layout.call(
                call,
                dotted(f"{client}.{self._params.new_call}"),
                args,
                indent=tree.indent(call),
                unit=context.module.default_indent,
                width=context.layout.line_length,
                around=tree.around(call),
            ),
        )

    def _arguments(self, call: cst.Call) -> _Read:
        """Every argument of the legacy call, sorted or refused one at a time.

        Positionals are lifted to keywords first: the new methods are keyword-only, and building
        the call before the lift raises `CSTValidationError`. One beyond `positional_to_kw`, or a
        repeated parameter, is ambiguous. `arg_map` renames last, so the pack lists legacy names.
        """
        positional = self._params.positional_to_kw
        args: list[cst.Arg] = []
        config: list[Field] = []
        given: dict[str, cst.BaseExpression] = {}
        index = 0
        for argument in call.args:
            if argument.star:
                # A splat's parameters are unknown, so none can be shown to carry.
                raise BailError("unsupported_kwarg")
            if argument.keyword is None:
                if index >= len(positional):
                    raise BailError("positional_arg_ambiguous")
                name = positional[index]
                index += 1
            else:
                name = argument.keyword.value
            if name in given:
                raise BailError("positional_arg_ambiguous")
            landed = self._params.arg_map.get(name, name)
            if name in self._params.config_kwargs:
                config.append((landed, argument.value))
            elif name in positional:
                args.append(layout.keyword(landed, argument.value))
            else:
                raise BailError("unsupported_kwarg")
            given[name] = argument.value
        return _Read(args=tuple(args), config=tuple(config), given=given)

    def _configuration(
        self,
        context: RuleContext,
        tree: Tree,
        call: cst.Call,
        alias: str,
        fields: tuple[Field, ...],
    ) -> cst.Call:
        """The configuration object one call carries, laid out inside it.

        `source` is `None`: nothing earlier laid these fields out. Its indent assumes the outer call
        wraps, which it does whenever this object does.
        """
        unit = context.module.default_indent
        return layout.call(
            None,
            cst.Attribute(value=cst.Name(alias), attr=cst.Name(self._config_leaf)),
            [layout.keyword(name, value) for name, value in fields],
            indent=tree.indent(call) + unit,
            unit=unit,
            width=context.layout.line_length,
            # `<kwarg>=` in front and a comma behind.
            around=len(self._config_kwarg) + 2,
        )

    def _check_the_answer_is_the_one_the_new_call_gives(
        self, tree: _Tree, call: cst.Call, read: _Read
    ) -> None:
        """Refuse a call whose result is not what the new call returns.

        `response_shape_changed`: a `dispatch_prefixes` argument that is not a literal with a listed
        prefix, or, under `result_access_flags`, any use of the result (it may be read unseen). A
        read of a field the new result lacks is `attribute_removed`, as the scan grades it.
        """
        for parameter, prefixes in sorted(self._params.dispatch_prefixes.items()):
            value = read.given.get(parameter)
            written = literal_string(value) if value is not None else None
            if written is None or not written.startswith(prefixes):
                raise BailError("response_shape_changed")
        if self._params.result_access_flags and not isinstance(tree.consumer(call), cst.Expr):
            raise BailError("response_shape_changed")
        if tree.reads(call, frozenset(self._params.result_attribute_flags)):
            raise BailError("attribute_removed")


class _Tree(Tree):
    """The shared index, and the scopes a result's name is followed through."""

    def __init__(self, context: RuleContext) -> None:
        super().__init__(context, [ScopeProvider])
        self._scopes = context.wrapper.resolve(ScopeProvider)

    def reads(self, call: cst.Call, fields: frozenset[str]) -> bool:
        """Whether what `call` returns is read for one of `fields`.

        Off the call, or the `for`/comprehension target it feeds, or the one name it is assigned to,
        each in its own scope. `getattr` counts, since it hides the miss behind a default. A result
        returned or passed on is not seen.
        """
        if self._field(call, fields):
            return True
        match self.consumer(call):
            case cst.For(target=cst.Name() as target) | cst.CompFor(target=cst.Name() as target):
                pass
            case cst.Assign(targets=[cst.AssignTarget(target=cst.Name() as target)]):
                pass
            case _:
                return False
        scope = self._scopes[target]
        found = scope[target.value] if scope is not None else set()
        return any(
            self._field(access.node, fields)
            for assignment in found
            for access in assignment.references
        )

    def _field(self, node: cst.CSTNode, fields: frozenset[str]) -> bool:
        """Whether one of `fields` is read off `node`, the call or a name for it."""
        match self.parent(node):
            case cst.Attribute(attr=cst.Name(value=field)):
                return field in fields
            case cst.Arg() as argument:
                match self.parent(argument):
                    case cst.Call(func=cst.Name(value="getattr"), args=[first, second, *_]):
                        return first is argument and literal_string(second.value) in fields
        return False
