"""`rewrite_call`: a legacy free function becomes a call on the client, one rule per pack change.

Only `positional_to_kw` (the new call's own arguments, in legacy order), `keywords` (the same, when
written as keywords) and `config_kwargs` (the configuration object) carry; any other keyword is
refused, never passed to a method that lacks it. Rooted on the `module`, the call stays on the name
the author wrote and no client is needed. A read of the result by a string key along a listed
`result_paths` becomes the attribute read of the same name.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Final

import libcst as cst
import libcst.matchers as m
from libcst.metadata import (
    Assignment,
    BaseAssignment,
    ClassScope,
    ExpressionContext,
    ExpressionContextProvider,
    QualifiedNameSource,
    Scope,
    ScopeProvider,
)

from obelize.models import BailCode, Edit
from obelize.transforms import layout
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.imports import dotted
from obelize.transforms.tree import Position, Tree, literal_string

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RewriteCallChange, RewriteCallParams

# What reaches a variable by its name written as a string: the builtins, a frame's variables, a
# module's dictionary. Any mention counts, since `f = locals` and `ev = eval` call them unseen.
_NAMED: Final = frozenset({"eval", "exec", "globals", "locals", "vars"}) | frozenset(
    {"f_locals", "f_globals", "currentframe", "_getframe", "__dict__"}
)

# Handlers for these miss the `AttributeError` an attribute read raises in place of the key error.
_MISSING_KEY: Final = frozenset({"builtins.KeyError", "builtins.LookupError"})

# A string-keyed read and the name it becomes.
Keyed = tuple[cst.Subscript, str]

# A node to climb from, the path of the result it holds, and whether a name on the way is shared.
_Use = tuple[cst.CSTNode, tuple[str, ...], bool]

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
        keyed = self._check_the_answer_is_the_one_the_new_call_gives(tree, call, read)
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
        for subscript, name in keyed:
            context.rewrites.set(
                subscript,
                cst.Attribute(
                    value=subscript.value,
                    attr=cst.Name(name),
                    lpar=subscript.lpar,
                    rpar=subscript.rpar,
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
    ) -> tuple[Keyed, ...]:
        """Refuse a call whose result is not what the new call returns; else the reads to rewrite.

        `response_shape_changed`: a `dispatch_prefixes` argument that is not a literal with a listed
        prefix, under `result_access_flags` any use of the result (it may be read unseen), or under
        `result_paths` any read that stops short of one of them and is not followed on into a name
        (`confined`). A read of a field the new result lacks is `attribute_removed`, as the scan
        grades it. A string-keyed read along a path is returned, to become the attribute read the
        new result takes.
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
        if not self._paths:
            return ()
        keyed = tree.confined(call, self._paths, self._stems)
        if keyed is None:
            raise BailError("response_shape_changed")
        return keyed


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
        super().__init__(context, [ScopeProvider, ExpressionContextProvider])
        self._scopes = context.wrapper.resolve(ScopeProvider)
        self._contexts = context.wrapper.resolve(ExpressionContextProvider)
        self._reads: dict[tuple[Scope | None, str], list[cst.CSTNode]] = {}
        self._confined: dict[
            tuple[Scope | None, str, frozenset[tuple[str, ...]]], dict[cst.Subscript, str] | None
        ] = {}

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
    ) -> tuple[Keyed, ...] | None:
        """The string-keyed reads of the result if it is read only along `leaves`, else None.

        Each use is the call or a read of the one name it is assigned to. A use climbs through
        attributes, integer subscripts and string keys, and must reach a leaf: a key off the path,
        a method, or the value handed on stops short of one. One that stops at a stem is followed
        into the name that takes it, or the loop variable that walks it (`_handed`), each name once.
        A result nothing reads is confined. A key is rewritten only where every name on the way
        holds the result's part alone (`_shared`), in the call's own frame, and linked (`_loose`):
        a name something else may hold would lose its dictionary.
        """
        match self.consumer(call):
            case cst.Expr():
                return ()
            case cst.Assign(targets=[cst.AssignTarget(target=cst.Name() as target)]):
                # Every call bound to the name is read by the same uses: walk them once.
                key = (self._scopes[target], target.value, leaves)
                if key not in self._confined:
                    self._confined[key] = self._walk(target, leaves, stems)
                keyed = self._confined[key]
            case _:
                keyed = self._walk(call, leaves, stems)
        if keyed is None or (keyed and not self._same_frame(call, keyed)):
            return None
        return tuple(keyed.items())

    def _walk(
        self,
        start: cst.Call | cst.Name,
        leaves: frozenset[tuple[str, ...]],
        stems: frozenset[tuple[str, ...]],
    ) -> dict[cst.Subscript, str] | None:
        """The keyed reads of everything `start` reaches, or None if one read stops short."""
        todo: list[_Use] = []
        seen: set[tuple[Scope | None, str, tuple[str, ...], bool]] = set()
        keyed: dict[cst.Subscript, str] = {}

        def hold(target: cst.Name, path: tuple[str, ...], shared: bool) -> bool:
            """Queue the reads of a name that holds what `path` reaches; False if none can be."""
            scope = self._scopes[target]
            if isinstance(scope, ClassScope) or self._by_name or self._augmented(target):
                return False
            shared = shared or self._shared(target)
            if (key := (scope, target.value, path, shared)) not in seen:
                seen.add(key)
                todo.extend((use, path, shared) for use in self._held(target))
                todo.extend((use, path, True) for use in self._loose(target))
            return True

        if isinstance(start, cst.Name):
            if not hold(start, (), False):
                return None
        else:
            todo.append((start, (), False))
        while todo:
            node, path, shared = todo.pop()
            climbed = self._climb(node, leaves, stems, path)
            if climbed is None:
                return None
            reads, onward, path = climbed
            if (reads and shared) or (onward is not None and not hold(onward, path, shared)):
                return None
            keyed.update(reads)
        return keyed

    def _same_frame(self, call: cst.Call, keyed: dict[cst.Subscript, str]) -> bool:
        """Whether every read runs where the call does: a closure runs when something calls it.

        A generator expression runs when something iterates it, so one that holds a key read is no
        place for the call either: it may be iterated outside the handler around it.
        """
        frame = self._frame(call)
        return not isinstance(frame, cst.GeneratorExp) and all(
            self._frame(read) is frame for read in keyed
        )

    def _frame(self, node: cst.CSTNode) -> cst.CSTNode:
        """The function, lambda, class, generator or module that runs `node`, maybe later.

        A list, set or dict comprehension runs in place.
        """
        while not isinstance(
            node, cst.Module | cst.FunctionDef | cst.Lambda | cst.ClassDef | cst.GeneratorExp
        ):
            node = self.parent(node)
        return node

    def _climb(
        self,
        node: cst.CSTNode,
        leaves: frozenset[tuple[str, ...]],
        stems: frozenset[tuple[str, ...]],
        path: tuple[str, ...],
    ) -> tuple[list[Keyed], cst.Name | None, tuple[str, ...]] | None:
        """The keyed reads on the way from `node` to a leaf, and the name a stem goes on in.

        None if the read stops short of a leaf, or sits where its keys cannot be rewritten.
        """
        keyed: list[Keyed] = []
        while path not in leaves:
            parent = self.parent(node)
            match parent:
                case cst.Attribute(value=value, attr=cst.Name(value=name)) if value is node:
                    path += (name,)
                case cst.Subscript(
                    value=value,
                    slice=[
                        cst.SubscriptElement(
                            slice=cst.Index(value=index, star=None), comma=cst.MaybeSentinel.DEFAULT
                        )
                    ],
                ) if value is node:
                    if _integer(index):
                        path += ("[]",)
                    else:
                        key = literal_string(index)
                        if (
                            key is None
                            or not key.isidentifier()
                            or self._contexts.get(parent) is not ExpressionContext.LOAD
                        ):
                            return None
                        path += (key,)
                        keyed.append((parent, key))
                case _:
                    onward = self._handed(parent, leaves, stems, path)
                    if onward is None or not self._placed(keyed):
                        return None
                    return keyed, *onward
            if path not in leaves and path not in stems:
                return None
            node = parent
        return (keyed, None, path) if self._placed(keyed) else None

    def _handed(
        self,
        parent: cst.CSTNode,
        leaves: frozenset[tuple[str, ...]],
        stems: frozenset[tuple[str, ...]],
        path: tuple[str, ...],
    ) -> tuple[cst.Name, tuple[str, ...]] | None:
        """The name a read that stopped at `path` goes on in, and the path it holds there.

        A stem goes on in the one name it is assigned to, or the one name a loop binds to each of
        its items (`[]` is the next step of a listed path). Whatever else takes it, a call, a
        return or a tuple, may read a field off the path, so the call is refused.
        """
        match parent:
            case cst.Assign(targets=[cst.AssignTarget(target=cst.Name() as target)]) if path:
                return target, path
            case (
                cst.For(target=cst.Name() as target) | cst.CompFor(target=cst.Name() as target)
            ) if (*path, "[]") in leaves | stems:
                return target, (*path, "[]")
        return None

    def _placed(self, keyed: list[Keyed]) -> bool:
        """Whether where a chain of keyed reads sits lets them be rewritten.

        One chain sits in one place: what surrounds its first read surrounds them all.
        """
        if not keyed:
            return True
        first, last = keyed[0][0], keyed[-1][0]
        return not (self._echoed(first) or self._swallowed(first) or self._glued(last))

    def _glued(self, node: cst.CSTNode) -> bool:
        """Whether a word follows `node` with no space: `]or` was a token end, `.id or` is not."""
        line, column = self.end(node)
        return self.lines[line - 1][column : column + 1].isidentifier()

    def _echoed(self, node: cst.CSTNode) -> bool:
        """Whether `node` is in an f-string field written with `=`, which prints its own source."""
        while not isinstance(node, cst.BaseSmallStatement | cst.BaseCompoundStatement):
            node = self.parent(node)
            if isinstance(node, cst.FormattedStringExpression) and node.equal is not None:
                return True
        return False

    def _swallowed(self, node: cst.CSTNode) -> bool:
        """Whether a handler or `suppress` around `node` may have taken the missing key's error.

        Up to the enclosing function, as a `try` guards its body only. A handler names a missing
        key, or a name this file defines or leaves unresolved, which may be a tuple holding one.
        """
        while not isinstance(node, cst.Module | cst.FunctionDef | cst.Lambda | cst.ClassDef):
            parent = self.parent(node)
            match parent:
                case cst.Try(handlers=handlers) | cst.TryStar(handlers=handlers) if (
                    node is parent.body
                ):
                    if any(self._may_miss(handler) for handler in handlers):
                        return True
                case cst.With(items=items) if node is parent.body:
                    if any(self._suppresses(item) for item in items):
                        return True
            node = parent
        return False

    def _may_miss(self, handler: cst.ExceptHandler | cst.ExceptStarHandler) -> bool:
        """Whether `handler` may name a missing key; a bare one also takes the `AttributeError`."""
        if handler.type is None:
            return False
        for name in m.findall(handler.type, m.Name() | m.Attribute()):
            above = self.parent(name)
            if isinstance(above, cst.Attribute) and above.attr is name:
                continue
            found = self.names(name)
            if not found or any(
                each.source is QualifiedNameSource.LOCAL or each.name in _MISSING_KEY
                for each in found
            ):
                return True
        return False

    def _suppresses(self, item: cst.WithItem) -> bool:
        return (
            isinstance(item.item, cst.Call)
            and self.qualified(item.item.func) == "contextlib.suppress"
        )

    def _assigned(self, target: cst.Name) -> set[BaseAssignment]:
        """Every binding of the name `target` binds, in its own scope."""
        scope = self._scopes[target]
        return scope[target.value] if scope is not None else set()

    def _held(self, target: cst.Name) -> list[cst.CSTNode]:
        """Every read of the name `target` binds, in its own scope, once each.

        A read links to every binding before it, so a name bound again lists it again: gathered
        once for the name, since each call bound to it asks.
        """
        key = (self._scopes[target], target.value)
        if key not in self._reads:
            self._reads[key] = list(
                dict.fromkeys(
                    access.node for found in self._assigned(target) for access in found.references
                )
            )
        return self._reads[key]

    def _shared(self, target: cst.Name) -> bool:
        """Whether the name may hold something else where it is read.

        A second binding, or a walrus anywhere in the file: one in a comprehension binds the
        function's name, which libcst lists in the comprehension's own scope.
        """
        return len(self._assigned(target)) != 1 or target.value in self._walrused

    def _loose(self, target: cst.Name) -> list[cst.CSTNode]:
        """Reads of the name that no binding in its scope links.

        Linked to none (`_unlinked`), or to a name outside the scope: a read above the binding in
        a loop is its second pass's, and libcst links it to the one outside.
        """
        scope = self._scopes[target]
        strays = [
            access.node
            for access in (() if scope is None else scope.accesses[target.value])
            if not any(each.scope is scope for each in access.referents)
        ]
        return [*strays, *self._unlinked.get(target.value, ())]

    def _augmented(self, target: cst.Name) -> bool:
        """Whether a binding of the name is `name |= x`: it reads the part, and no read lists it."""
        return any(
            isinstance(each, Assignment) and isinstance(self.parent(each.node), cst.AugAssign)
            for each in self._assigned(target)
        )

    @cached_property
    def _walrused(self) -> frozenset[str]:
        """Names a walrus binds anywhere in the file."""
        return frozenset(
            node.target.value
            for node in m.findall(self.module, m.NamedExpr(target=m.Name()))
            if isinstance(node, cst.NamedExpr) and isinstance(node.target, cst.Name)
        )

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
        """Whether the file may read a name by its string (`locals()["r"]`, `eval`, `f_locals`)."""
        return any(isinstance(node, cst.Name) and node.value in _NAMED for node in self._parent)

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
