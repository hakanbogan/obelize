"""`configure_to_client`: the process-wide `configure(...)` becomes a `Client(...)` bound in scope.

A client that fits no placement row is refused, never moved: relocated code cannot be reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import libcst as cst
from libcst.metadata import ScopeProvider

from obelize.impact.planner import needs_client
from obelize.models import Edit
from obelize.transforms import layout
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.tree import Position, Tree

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, ConfigureToClientChange, ConfigureToClientParams

# The `ClassDef`/`FunctionDef` chain containing a line, outermost first.
Scope = tuple[cst.CSTNode, ...]


@dataclass(frozen=True, slots=True)
class _Placement:
    """Which row of the table fired, and which candidate names it rules out."""

    # The method's receiver for the attribute row; empty otherwise.
    receiver: str
    module_level: bool
    # Candidates taken where the client would be bound. Empty for the module row, which reserves
    # through the import manager so later rules cannot be handed the same name.
    taken: frozenset[str]

    def target(self, name: str) -> cst.BaseAssignTargetExpression:
        if not self.receiver:
            return cst.Name(name)
        return cst.Attribute(value=cst.Name(self.receiver), attr=cst.Name(name))


class ConfigureToClient:
    kind: ClassVar[ChangeKind] = "configure_to_client"

    def __init__(self, change: ConfigureToClientChange) -> None:
        self._id = change.id
        self._params: ConfigureToClientParams = change.params
        self._module, _, self._leaf = change.params.client_symbol.rpartition(".")

    @property
    def consumes(self) -> frozenset[str]:
        """`configure` is imported only for the call this rule replaces."""
        return frozenset({self._params.legacy_symbol})

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        return finding.kind == "call" and finding.symbol == self._params.legacy_symbol

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        eligible = sorted(
            (finding.line, finding.column)
            for finding in context.plan.findings
            if finding.scan_status == "eligible" and self.claims(finding)
        )
        tree = _Tree(context)
        return tuple(self._edit(context, tree, position) for position in eligible)

    def _edit(self, context: RuleContext, tree: _Tree, position: Position) -> Edit:
        try:
            eager = self._rewrite(context, tree, position)
        except BailError as bail:
            # Later rules must know there is no client, and that its reason is reported here.
            context.client.bail = bail.reason
            return Edit(
                path=context.path,
                line=position[0],
                status="needs_review",
                rule_id=self._id,
                reason=bail.reason,
            )
        return Edit(
            path=context.path,
            line=position[0],
            status="auto",
            rule_id=self._id,
            warnings=("client_constructed_eagerly",) if eager else (),
        )

    def _rewrite(self, context: RuleContext, tree: _Tree, position: Position) -> bool:
        """Record the assignment that replaces one call, or raise its bail.

        Returns whether to warn `client_constructed_eagerly`: a module-level client
        without a non-empty literal key may raise where the legacy call returned quietly.
        """
        call = tree.call(position)
        statement = tree.statement(call)
        args = self._arguments(call)
        alias = context.imports.binding(self._module)
        if alias is None:
            # The import rule could not name the module and already reported why; reuse its code.
            raise BailError("alias_collision")
        placement = self._placement(context, tree, call, position)
        target = cst.AssignTarget(target=placement.target(self._name(context, placement)))
        value = layout.call(
            call,
            cst.Attribute(value=cst.Name(alias), attr=cst.Name(self._leaf)),
            args,
            indent=tree.indent(statement),
            unit=context.module.default_indent,
            width=context.layout.line_length,
            around=len(layout.render(target)) + tree.trailing(statement),
        )
        context.rewrites.set_statement(
            statement, cst.Assign(targets=[target], value=value, semicolon=statement.semicolon)
        )
        context.client.expression = layout.render(target.target)
        return placement.module_level and not self._literal_credential(args)

    def _arguments(self, call: cst.Call) -> list[cst.Arg]:
        """Every argument of the legacy call, refused one at a time.

        Only named `allowed_kwargs` carry; a positional or splat cannot be named. The credentials
        keyword refuses a mapping, since the new `credentials` takes only a credentials object.
        """
        for argument in call.args:
            keyword = argument.keyword
            if keyword is None or argument.star:
                raise BailError("configure_kwargs_unsupported")
            if keyword.value not in self._params.allowed_kwargs:
                raise BailError("configure_kwargs_unsupported")
            object_kwarg = self._params.credentials_object_kwarg
            if keyword.value == object_kwarg and isinstance(argument.value, cst.Dict):
                raise BailError("credentials_shape_differs")
        return list(call.args)

    def _placement(
        self, context: RuleContext, tree: _Tree, call: cst.Call, position: Position
    ) -> _Placement:
        """The placement table in row order: module-level, local, instance attribute, refuse.

        Every row binds the client where `configure` was, so it must run whenever its scope does;
        under an `if`, `try`, `with` or loop a reader could meet an unbound name.
        """
        here = tree.scope(position[0])
        if not tree.unconditional(call, here):
            raise BailError("client_placement_ambiguous")
        readers = [
            (tree.scope(finding.line), finding.line)
            for finding in context.plan.findings
            if (finding.line, finding.column) != position and _reads(context, finding)
        ]
        if not here:
            # A module-level reader above the `configure` runs before the client exists.
            if any(not scope and line < position[0] for scope, line in readers):
                raise BailError("client_placement_ambiguous")
            return _Placement(receiver="", module_level=True, taken=frozenset())
        scopes = [scope for scope, _line in readers]
        if all(scope[: len(here)] == here for scope in scopes):
            return _Placement(receiver="", module_level=False, taken=self._reserved(context))
        return self._attribute(tree, here, scopes)

    def _attribute(self, tree: _Tree, here: Scope, readers: list[Scope]) -> _Placement:
        """Row three: a method of a class whose other methods read the client.

        Only an undecorated method directly in the class, and readers with the same receiver: a
        nested function may rebind it, and a class or static method's first parameter is not the
        instance. A base this rule cannot read takes both names, so the ladder bails.
        """
        owner = here[0] if len(here) == 2 else None
        method = here[1] if len(here) == 2 else None
        if not isinstance(owner, cst.ClassDef) or not isinstance(method, cst.FunctionDef):
            raise BailError("client_placement_ambiguous")
        receiver = _receiver(method)
        if receiver is None:
            raise BailError("client_placement_ambiguous")
        if not all(
            len(reader) >= 2 and reader[0] is owner and _receiver(reader[1]) == receiver
            for reader in readers
        ):
            raise BailError("client_placement_ambiguous")
        held = tree.held(owner, receiver)
        taken = self._candidates if held is None else held & self._candidates
        return _Placement(receiver=receiver, module_level=False, taken=taken)

    def _reserved(self, context: RuleContext) -> frozenset[str]:
        """Every candidate any scope in the file binds: a nested binding would shadow the client."""
        return frozenset(name for name in self._candidates if context.imports.bound(name))

    @property
    def _candidates(self) -> frozenset[str]:
        return frozenset({self._params.client_name, self._params.client_name_fallback})

    def _literal_credential(self, args: list[cst.Arg]) -> bool:
        """Whether the credential is a non-empty string literal; nothing subtler."""
        for argument in args:
            keyword = argument.keyword
            if keyword is not None and keyword.value == self._params.credential_kwarg:
                evaluated = (
                    argument.value.evaluated_value
                    if isinstance(argument.value, cst.SimpleString)
                    else None
                )
                return isinstance(evaluated, str) and bool(evaluated)
        return False

    def _name(self, context: RuleContext, placement: _Placement) -> str:
        """The ladder: the pack's name, the pack's fallback, then the bail."""
        ladder = (self._params.client_name, self._params.client_name_fallback)
        if placement.module_level:
            taken = context.imports.take(*ladder)
            if taken is None:
                raise BailError("client_name_collision")
            return taken
        free = [name for name in ladder if name not in placement.taken]
        if not free:
            raise BailError("client_name_collision")
        return free[0]


def _reads(context: RuleContext, finding: Finding) -> bool:
    """Whether this row becomes a client call, counting free functions the projection misses."""
    return needs_client(finding, context.spec) or finding.symbol in context.client_readers


def _receiver(node: cst.CSTNode) -> str | None:
    """The first parameter of an undecorated method, which is the instance."""
    if not isinstance(node, cst.FunctionDef) or node.decorators or not node.params.params:
        return None
    return node.params.params[0].name.value


class _Tree(Tree):
    """The shared index, plus the scope chain the placement table reads."""

    def __init__(self, context: RuleContext) -> None:
        super().__init__(context, [ScopeProvider])
        self._scopes = context.wrapper.resolve(ScopeProvider)
        self._blocks: list[tuple[int, int, cst.CSTNode]] = [
            (span.start.line, span.end.line, node)
            for node, span in self._pos.items()
            if isinstance(node, (cst.ClassDef, cst.FunctionDef))
        ]
        # Outermost first, so scope chains compare by prefix; metadata order is arbitrary.
        self._blocks.sort(key=lambda row: (row[0], -row[1]))

    def statement(self, call: cst.Call) -> cst.Expr:
        """The expression statement `call` is the whole of; a used result has no placement."""
        parent = self.parent(call)
        if not isinstance(parent, cst.Expr):
            raise BailError("client_placement_ambiguous")
        return parent

    def unconditional(self, call: cst.Call, here: Scope) -> bool:
        """Whether `call`'s statement is directly in its scope's body, not under a compound one."""
        line = self.line_of(call)
        if line is None:
            return False
        block = self.parent(line)
        if not here:
            return isinstance(block, cst.Module)
        return isinstance(block, cst.IndentedBlock) and self.parent(block) is here[-1]

    def held(self, owner: cst.ClassDef, receiver: str) -> frozenset[str] | None:
        """Every name an instance of `owner` may already carry, or `None` if that is unknowable.

        Receiver attributes and class-body bindings (a `client` property cannot be assigned), also
        for bases defined above it here; a metaclass or any other base is unknowable.
        """
        # A class body always holds a statement, and every one is in the class's scope.
        body = self._scopes.get(owner.body.body[0])
        bound = {row.name for row in (body.assignments if body is not None else ())}
        names = set(self.attributes(owner, receiver)) | bound
        if owner.keywords:
            return None
        for base in owner.bases:
            if isinstance(base.value, cst.Name) and base.value.value == "object":
                continue
            parent = self._defined_above(owner, base.value)
            inherited = None if parent is None else self.held(parent, receiver)
            if inherited is None:
                return None
            names |= inherited
        return frozenset(names)

    def _defined_above(self, owner: cst.ClassDef, base: cst.BaseExpression) -> cst.ClassDef | None:
        """The last class of that name defined above `owner`, if the base is a plain name."""
        if not isinstance(base, cst.Name):
            return None
        above = [
            node
            for start, _end, node in self._blocks
            if isinstance(node, cst.ClassDef)
            and node.name.value == base.value
            and start < self.start(owner)[0]
        ]
        return above[-1] if above else None

    def scope(self, line: int) -> Scope:
        return tuple(node for start, end, node in self._blocks if start <= line <= end)

    def attributes(self, owner: cst.ClassDef, receiver: str) -> frozenset[str]:
        """Every `<receiver>.<name>` the class already uses, read or written."""
        found = _Attributes(receiver)
        owner.visit(found)
        return frozenset(found.names)


class _Attributes(cst.CSTVisitor):
    def __init__(self, receiver: str) -> None:
        super().__init__()
        self._receiver = receiver
        self.names: set[str] = set()

    def visit_Attribute(self, node: cst.Attribute) -> None:  # noqa: N802 - libcst dispatch
        if isinstance(node.value, cst.Name) and node.value.value == self._receiver:
            self.names.add(node.attr.value)
