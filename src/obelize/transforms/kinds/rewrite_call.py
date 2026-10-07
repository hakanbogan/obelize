"""`rewrite_call`: a legacy free function becomes a call on the client, one rule per pack change.

Only `positional_to_kw` (the new call's own arguments, in legacy order), `keywords` (the same, when
written as keywords) and `config_kwargs` (the configuration object) carry; any other keyword is
refused, never passed to a method that lacks it. Rooted on the `module`, the call stays on the name
the author wrote and no client is needed.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Final

import libcst as cst
from libcst.metadata import ClassScope, ScopeProvider

from obelize.models import BailCode, Edit
from obelize.transforms import layout
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.imports import dotted
from obelize.transforms.tree import Position, Tree, literal_string

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RewriteCallChange, RewriteCallParams

# Builtins that reach a variable by its name written as a string.
_NAMED: Final = frozenset({"eval", "exec", "globals", "locals", "vars"})

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

# What only a rule rooted on the `module` raises, graded by `tests/unit/test_shared_module.py`.
MODULE_BAILS: frozenset[BailCode] = frozenset({"from_import_unmigrated_symbol"})


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
        # A module rule keeps the import it was written with and needs no client.
        self._client_side = (
            frozenset({change.params.legacy_symbol})
            if change.params.root == "client"
            else frozenset()
        )
        self._paths = frozenset(_tokens(path) for path in change.params.result_paths)
        # Every proper prefix of a path: a read may go on only along one of these.
        self._stems = frozenset(path[:end] for path in self._paths for end in range(1, len(path)))

    @property
    def consumes(self) -> frozenset[str]:
        """The one symbol this rule replaces whole, so an import of it can go."""
        return self._client_side

    @property
    def client_readers(self) -> frozenset[str]:
        """The call becomes a client call, so the client must be placed where it can see it."""
        return self._client_side

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
        callee = self._callee(context, call)
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
                callee,
                args,
                indent=tree.indent(call),
                unit=context.module.default_indent,
                width=self._width(context, tree, call),
                around=tree.around(call),
            ),
        )

    def _callee(self, context: RuleContext, call: cst.Call) -> cst.BaseExpression:
        """What the new call is made on: the file's client, or the root the author wrote.

        A call written `<root>.<legacy tail>` keeps `<root>`, whatever name the file bound the
        module to. One reached through `from M import Name` has no root to keep.
        """
        if self._params.root == "client":
            client = context.client.expression
            if client is None:
                raise BailError(context.client.bail or "client_source_unresolved")
            return dotted(f"{client}.{self._params.new_call}")
        symbol = self._params.legacy_symbol
        module = max(
            (name for name in context.spec.legacy_modules if symbol.startswith(f"{name}.")),
            key=len,
        )
        root = call.func
        for _ in range(symbol.count(".") - module.count(".")):
            if not isinstance(root, cst.Attribute):
                raise BailError("from_import_unmigrated_symbol")
            root = root.value
        for part in self._params.new_call.split("."):
            root = cst.Attribute(value=root, attr=cst.Name(part))
        return root

    @staticmethod
    def _width(context: RuleContext, tree: Tree, call: cst.Call) -> int:
        """The pack's width, except in an f-string field: before Python 3.12 that is one line."""
        return sys.maxsize if tree.in_f_string(call) else context.layout.line_length

    def _arguments(self, call: cst.Call) -> _Read:
        """Every argument of the legacy call, sorted or refused one at a time.

        Positionals are lifted to keywords first: the new methods are keyword-only, and building
        the call before the lift raises `CSTValidationError`. One beyond `positional_to_kw`, or a
        repeated parameter, is ambiguous. `arg_map` renames last, so the pack lists legacy names.
        """
        positional = self._params.positional_to_kw
        carried = {*positional, *self._params.keywords}
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
            elif name in carried:
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
            width=self._width(context, tree, call),
            # `<kwarg>=` in front and a comma behind.
            around=len(self._config_kwarg) + 2,
        )

    def _check_the_answer_is_the_one_the_new_call_gives(
        self, tree: _Tree, call: cst.Call, read: _Read
    ) -> None:
        """Refuse a call whose result is not what the new call returns.

        `response_shape_changed`: a `dispatch_prefixes` argument that is not a literal with a listed
        prefix, under `result_access_flags` any use of the result (it may be read unseen), or under
        `result_paths` any read that stops short of one of them. A read of a field the new result
        lacks is `attribute_removed`, as the scan grades it.
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
        if self._paths and not tree.confined(call, self._paths, self._stems):
            raise BailError("response_shape_changed")


def _tokens(path: str) -> tuple[str, ...]:
    """`choices[].message` as `("choices", "[]", "message")`."""
    return tuple(re.findall(r"\[\]|\w+", path))


def _integer(node: cst.BaseExpression) -> bool:
    """A subscript that is a number written out; a name or a string may select a key instead."""
    match node:
        case cst.Integer():
            return True
        case cst.UnaryOperation(operator=cst.Minus(), expression=cst.Integer()):
            return True
    return False


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
        return any(self._field(node, fields) for node in self._held(target))

    def confined(
        self, call: cst.Call, leaves: frozenset[tuple[str, ...]], stems: frozenset[tuple[str, ...]]
    ) -> bool:
        """Whether what `call` returns is read only along `leaves`, and nowhere else.

        Each use is the call or a read of the one name it is assigned to. A use climbs through
        attributes and integer subscripts, and must reach a leaf: a string subscript, a method, a
        loop, or the value handed on stops short of one. A result nothing reads is confined. One
        bound in a class body is read as an attribute of the class, and one in a file that reads
        names by their strings may be read as `locals()["r"]`: no scope links either.
        """
        match self.consumer(call):
            case cst.Expr():
                return True
            case cst.Assign(targets=[cst.AssignTarget(target=cst.Name() as target)]):
                if isinstance(self._scopes[target], ClassScope) or self._by_name:
                    return False
                uses = [*self._held(target), *self._unlinked.get(target.value, ())]
            case _:
                uses = [call]
        return all(self._reaches(use, leaves, stems) for use in uses)

    def _reaches(
        self,
        node: cst.CSTNode,
        leaves: frozenset[tuple[str, ...]],
        stems: frozenset[tuple[str, ...]],
    ) -> bool:
        path: tuple[str, ...] = ()
        while path not in leaves:
            parent = self.parent(node)
            match parent:
                case cst.Attribute(value=value, attr=cst.Name(value=name)) if value is node:
                    path += (name,)
                case cst.Subscript(
                    value=value, slice=[cst.SubscriptElement(slice=cst.Index(value=index))]
                ) if value is node and _integer(index):
                    path += ("[]",)
                case _:
                    return False
            if path not in leaves and path not in stems:
                return False
            node = parent
        return True

    def _held(self, target: cst.Name) -> list[cst.CSTNode]:
        """Every read of the name `target` binds, in its own scope."""
        scope = self._scopes[target]
        found = scope[target.value] if scope is not None else set()
        return [access.node for assignment in found for access in assignment.references]

    @cached_property
    def _unlinked(self) -> dict[str, list[cst.CSTNode]]:
        """Reads linked to no assignment, by name: one above it, in a loop's second pass."""
        found: dict[str, list[cst.CSTNode]] = {}
        for each in set(self._scopes.values()):
            for access in () if each is None else each.accesses:
                if not access.referents and isinstance(access.node, cst.Name):
                    found.setdefault(access.node.value, []).append(access.node)
        return found

    @cached_property
    def _by_name(self) -> bool:
        """Whether the file reads a name by its string (`locals()["r"]`, `eval`, `"{r}".format`)."""
        return any(
            isinstance(call.func, cst.Name) and call.func.value in _NAMED
            for call in self._calls.values()
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
