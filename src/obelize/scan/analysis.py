"""Resolve which legacy surfaces one parsed file uses, and how confident each answer is.

libcst does no dataflow, so the resolution rules are the design. Every libcst set is sorted
before it is read: it hashes by object identity, so its order differs between processes.
Whether a file may be rewritten is `impact/`'s decision.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

import libcst as cst
from libcst._metadata_dependent import LazyValue
from libcst.metadata import (
    Assignment,
    BaseAssignment,
    ClassScope,
    FunctionScope,
    GlobalScope,
    ImportAssignment,
    MetadataWrapper,
    ParentNodeProvider,
    PositionProvider,
    QualifiedName,
    QualifiedNameProvider,
    QualifiedNameSource,
    Scope,
    ScopeProvider,
)

from obelize.models import (
    BailCode,
    BindingKind,
    ConfidenceReason,
    Finding,
    FindingKind,
    ScanSpec,
    ScanStatus,
)
from obelize.scan.parse import Read

# Closed here, where raised; `tests/oracle/` asserts the split with `impact/`.
BAILS: frozenset[BailCode] = frozenset(
    {
        "attribute_removed",
        "conditional_binding",
        "flag_only_surface",
        "local_import",
        "module_alias_rebound",
        "receiver_unresolved",
        "roundtrip_mismatch",
        "star_import",
    }
)

# Smaller wins: 1 pack refusal, 2 file gate, 3 whole-file defect, 5 binding; 4, 6 are `impact/`'s.
RUNG: Final[dict[BailCode, int]] = {
    "attribute_removed": 1,
    "flag_only_surface": 1,
    "roundtrip_mismatch": 2,
    "star_import": 3,
    "conditional_binding": 3,
    "module_alias_rebound": 3,
    "local_import": 3,
    "receiver_unresolved": 5,
}

# Worst first: under a star import nothing resolves, a conditional one resolves two SDKs, a
# rebound alias loses one name's uses. Decides only which code a file carrying two reports.
_FILE_WIDE: Final[tuple[BailCode, ...]] = (
    "roundtrip_mismatch",
    "star_import",
    "conditional_binding",
    "module_alias_rebound",
)

# Hard-coded, not read from the pack: a pack carries no behaviour.
_BY_NAME: Final[frozenset[str]] = frozenset(
    {
        "importlib.import_module",
        "builtins.__import__",
        "pkgutil.resolve_name",
        "sys.modules.get",
        "sys.modules.pop",
        "sys.modules.setdefault",
    }
)
_GETATTR: Final = "builtins.getattr"
_SYS_MODULES: Final = "sys.modules"

# Identifier segments only: `Finding` rejects a symbol like `google.generativeai.2`.
_TAIL: Final = r"(?:\.[A-Za-z_][A-Za-z0-9_]*)*"

# What reaches a module's names without writing them: it is not one of its symbols.
_REFLECTED: Final = frozenset({"__dict__", "__getattribute__"})

# The pack refuses a `flag_only` shape whatever symbol the finding carries.
_FLAGGED: Final[BailCode] = "flag_only_surface"


@dataclass(frozen=True, slots=True)
class Receiver:
    """A name bound to a legacy object and every place it is read; `impact/dataflow.py` decides.

    `escape_lines` is deliberately not the complement of the method-call uses: a `None` comparison
    is no escape yet survives the rewrite, so deleting the constructor must also check `use_lines`.
    """

    kind: BindingKind
    name: str
    scope: str
    # A constructor symbol, or what a method returned.
    receiver: str
    ctor_line: int
    # `len(scope[name])`; above one is `multiple_assignments`.
    assignments: int
    use_lines: tuple[int, ...]
    escape_lines: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Held:
    """A class attribute holding a legacy object; `prefix` is the first parameter's, not `self.`."""

    kind: BindingKind
    receiver: str
    ctor_line: int
    assignments: int
    prefix: str


@dataclass(frozen=True, slots=True)
class Analysis:
    """What one file contains, as the scan alone can see it."""

    path: str
    findings: tuple[Finding, ...]
    receivers: tuple[Receiver, ...]


def analyse(read: Read, spec: ScanSpec) -> Analysis:
    """Resolve the legacy usages in one read file."""
    if read.module is None:
        return Analysis(path=read.path, findings=read.findings, receivers=())
    return _Pass(read.path, read.module, spec, read.bail).run()


class _Nodes(cst.CSTVisitor):
    """One walk, collecting the node kinds the passes need."""

    def __init__(self) -> None:
        self.imports: list[cst.Import | cst.ImportFrom] = []
        self.calls: list[cst.Call] = []
        self.subscripts: list[cst.Subscript] = []
        self.classes: list[cst.ClassDef] = []
        self.assigns: list[cst.Assign] = []
        self.ann_assigns: list[cst.AnnAssign] = []
        self.comments: list[cst.Comment] = []
        self.strings: list[cst.SimpleString | cst.FormattedString] = []
        self.attributes: list[cst.Attribute] = []

    def visit_Import(self, node: cst.Import) -> None:
        self.imports.append(node)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        self.imports.append(node)

    def visit_Call(self, node: cst.Call) -> None:
        self.calls.append(node)

    def visit_Subscript(self, node: cst.Subscript) -> None:
        self.subscripts.append(node)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.classes.append(node)

    def visit_Assign(self, node: cst.Assign) -> None:
        self.assigns.append(node)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self.ann_assigns.append(node)

    def visit_Comment(self, node: cst.Comment) -> None:
        self.comments.append(node)

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        self.strings.append(node)

    def visit_FormattedString(self, node: cst.FormattedString) -> None:
        self.strings.append(node)

    def visit_Attribute(self, node: cst.Attribute) -> None:
        self.attributes.append(node)


class _Pass:
    """One file's analysis; single use."""

    def __init__(self, path: str, module: cst.Module, spec: ScanSpec, bail: BailCode | None):
        self._path = path
        self._module = module
        self._spec = spec
        self._gate = bail

        # `unsafe_skip_copy` is load-bearing: a copied module's metadata would not hold these nodes.
        wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
        # `resolve_many` erases the value type, so the typed views are read back from its cache.
        wrapper.resolve_many([QualifiedNameProvider, PositionProvider, ParentNodeProvider])
        self._qnp = wrapper.resolve(QualifiedNameProvider)
        self._pos = wrapper.resolve(PositionProvider)
        self._parents = wrapper.resolve(ParentNodeProvider)
        self._scopes = wrapper.resolve(ScopeProvider)

        self._nodes = _Nodes()
        module.visit(self._nodes)

        self._findings: list[Finding] = []
        self._claimed: set[int] = set()
        self._aliased: set[str] = set()
        self._from_bound: set[str] = set()
        self._star = False
        self._rebound = False
        self._conditional = False
        self._declared = (
            set(spec.symbols)
            | set(spec.constructor_symbols)
            | set(spec.flag_only_symbols)
            | ({spec.client_symbol} if spec.client_symbol else set())
        )
        # The hyphenated distribution name never matches: it is not an importable path.
        modules = "|".join(re.escape(module) for module in spec.legacy_modules)
        self._mention = re.compile(f"(?<![A-Za-z0-9_.])(?:{modules}){_TAIL}")
        self._produced: dict[int, str] = {}
        self._receivers: list[Receiver] = []

    def run(self) -> Analysis:
        self._imports()
        self._dynamic()
        self._resolved()
        self._mock_targets()
        self._star_candidates()
        self._bindings()
        self._unresolved_receivers()
        self._mentions()
        return Analysis(
            path=self._path,
            findings=tuple(sorted(self._stamped(), key=lambda f: f.sort_key)),
            receivers=tuple(sorted(self._receivers, key=lambda r: (r.ctor_line, r.scope, r.name))),
        )

    def _names(self, node: cst.CSTNode) -> set[QualifiedName]:
        """`node`'s qualified names; read outside a visitor, the mapping holds a `LazyValue`."""
        value = self._qnp.get(node, ())
        return set(value()) if isinstance(value, LazyValue) else set(value)

    def _legacy(self, node: cst.CSTNode) -> tuple[str, ...]:
        """The legacy names `node` resolves to; a shared module itself counts, since it escapes."""
        names = self._names(node)
        return tuple(
            sorted(
                name.name
                for name in names
                if name.source is QualifiedNameSource.IMPORT
                and (self._under_legacy(name.name) or self._bare(name.name))
            )
        )

    def _reaches(self, node: cst.CSTNode) -> bool:
        """Whether `node` resolves into a legacy module, which a legacy name or not."""
        return any(
            name.source is QualifiedNameSource.IMPORT and self._in_module(name.name)
            for name in self._names(node)
        )

    @staticmethod
    def _under(name: str, roots: Iterable[str]) -> bool:
        return any(name == root or name.startswith(root + ".") for root in roots)

    def _in_module(self, name: str) -> bool:
        return self._under(name, self._spec.legacy_modules)

    def _bare(self, name: str) -> bool:
        return self._spec.shared and name in self._spec.legacy_modules

    def _fetches(self, name: str) -> bool:
        """Whether fetching `name` by its string gets a legacy name or, if shared, the module whose
        attributes no import then names."""
        return self._under_legacy(name) or self._bare(name)

    def _under_legacy(self, name: str) -> bool:
        """A shared module is legacy only under `symbols`: the rest is what the new SDK keeps."""
        return self._under(
            name, self._spec.symbols if self._spec.shared else self._spec.legacy_modules
        )

    def _line(self, node: cst.CSTNode) -> tuple[int, int]:
        start = self._pos[node].start
        return start.line, start.column

    def _parent(self, node: cst.CSTNode) -> cst.CSTNode | None:
        try:
            return self._parents[node]
        except KeyError:  # pragma: no cover - the Module is the only parentless node
            return None

    def _add(
        self,
        node: cst.CSTNode,
        kind: FindingKind,
        reason: ConfidenceReason,
        symbol: str,
        *,
        bail: BailCode | None = None,
    ) -> None:
        at_line, at_column = self._line(node)
        status, graded = self._grade(kind, symbol)
        if bail is not None and graded is None:
            # Rung 1 outranks a shape or placement code.
            status, graded = "needs_review", bail
        self._findings.append(
            Finding(
                path=self._path,
                line=at_line,
                column=at_column,
                kind=kind,
                confidence_reason=reason,
                symbol=symbol,
                evidence=None,
                scan_status=status,
                bail=graded,
            )
        )

    def _grade(self, kind: FindingKind, symbol: str) -> tuple[ScanStatus, BailCode | None]:
        """Rung 1: a surface the pack refuses outright."""
        if kind != "import" and symbol in self._spec.removed_attributes:
            return "unsupported", "attribute_removed"
        if any(
            symbol == flagged or symbol.startswith(flagged + ".")
            for flagged in self._spec.flag_only_symbols
        ):
            return "needs_review", "flag_only_surface"
        return "eligible", None

    def _stamped(self) -> list[Finding]:
        """Apply the file-wide code where nothing as specific fired; never on `not_a_usage`."""
        stamp = self._file_wide()
        if stamp is None:
            return self._findings
        rung = RUNG[stamp]
        out = []
        for finding in self._findings:
            if finding.scan_status == "not_a_usage" or (
                finding.bail is not None and RUNG[finding.bail] <= rung
            ):
                out.append(finding)
                continue
            out.append(
                Finding(**{**finding.model_dump(), "scan_status": "needs_review", "bail": stamp})
            )
        return out

    def _file_wide(self) -> BailCode | None:
        raised = {
            "roundtrip_mismatch": self._gate == "roundtrip_mismatch",
            "star_import": self._star,
            "conditional_binding": self._conditional,
            "module_alias_rebound": self._rebound,
        }
        for code in _FILE_WIDE:
            if raised[code]:
                return code
        return None

    def _imports(self) -> None:
        """Record each import and how each bound name was spelled, which sets every later reason."""
        for statement in self._nodes.imports:
            if isinstance(statement, cst.Import):
                self._plain_import(statement)
            else:
                self._from_import(statement)

    def _plain_import(self, statement: cst.Import) -> None:
        for alias in statement.names:
            module = alias.evaluated_name
            if not self._under_legacy(module):
                continue
            bound = alias.evaluated_alias
            if bound is None:
                reason: ConfidenceReason = "direct_import_resolved"
            else:
                self._aliased.add(bound)
                reason = "alias_resolved"
            self._add(
                statement,
                "import",
                self._maybe_conditional(statement, reason),
                module,
                bail=self._placement(statement),
            )

    def _from_import(self, statement: cst.ImportFrom) -> None:
        if statement.module is None or statement.relative:
            # Never legacy: `from . import x` has no module, and `.acme` only looks top-level.
            return
        module = _dotted(statement.module)
        if isinstance(statement.names, cst.ImportStar):
            if self._under_legacy(module) or self._bare(module):
                self._star = True
                self._add(statement, "star_import", "star_import", module)
            # No placement code: `from x import *` inside a function is a SyntaxError.
            return
        legacy_module = self._under_legacy(module)
        symbols: list[str] = []
        for alias in statement.names:
            # `from google import generativeai` names the module in the imported symbol.
            full = f"{module}.{alias.evaluated_name}"
            if not legacy_module and not self._under_legacy(full):
                continue
            self._from_bound.add(alias.evaluated_alias or alias.evaluated_name)
            symbols.append(module if legacy_module else full)
        # One finding per statement; every bound name is still recorded, as later reasons key on it.
        for symbol in dict.fromkeys(symbols):
            self._add(
                statement,
                "import",
                self._maybe_conditional(statement, "from_import_resolved"),
                symbol,
                bail=self._placement(statement),
            )

    def _maybe_conditional(
        self, statement: cst.Import | cst.ImportFrom, reason: ConfidenceReason
    ) -> ConfidenceReason:
        """`conditional_binding` when a bound name has two `ImportAssignment`s (try/except).

        A second binding by ordinary assignment keeps `reason`; the file-wide code covers it.
        """
        scope = self._scopes.get(statement)
        if scope is None:  # pragma: no cover - every statement is in some scope
            return reason
        for name in _bound_names(statement):
            imports = [
                assignment for assignment in scope[name] if isinstance(assignment, ImportAssignment)
            ]
            if len(imports) > 1:
                self._conditional = True
                return "conditional_binding"
        return reason

    def _placement(self, statement: cst.Import | cst.ImportFrom) -> BailCode | None:
        """`local_import` for an import outside the module scope, a class body included.

        An `if TYPE_CHECKING:` import is still in the module scope, so it is not caught.
        """
        scope = self._scopes.get(statement)
        if isinstance(scope, GlobalScope):
            return None
        return "local_import"

    def _dynamic(self) -> None:
        """`importlib.import_module`, `__import__`, `sys.modules`: fetch by name (`dynamic_access`).

        `getattr` reads the resolvable alias instead: a bare-module escape (`module_alias_rebound`).
        """
        if "dynamic_access" not in self._spec.flag_only_patterns:
            return
        for call in self._nodes.calls:
            names = {name.name for name in self._names(call.func)}
            if not call.args:
                continue
            first = call.args[0].value
            if names & _BY_NAME:
                text = _string(first)
                if text is not None and text.startswith(".") and len(call.args) > 1:
                    # `import_module(".error", "openai")` is relative to its package.
                    package = _string(call.args[1].value)
                    text = None if package is None else package + text
                if text is not None and self._fetches(text):
                    self._claimed.add(id(first))
                    self._add(call, "dynamic", "dynamic_access", text, bail=_FLAGGED)
            elif _GETATTR in names and len(call.args) > 1:
                module = self._legacy(first)
                attribute = _string(call.args[1].value)
                if (
                    module
                    and attribute is not None
                    and module[0] in self._spec.legacy_modules
                    and self._under_legacy(f"{module[0]}.{attribute}")
                ):
                    self._claimed.add(id(first))
                    self._rebound = True
                    self._add(
                        call,
                        "dynamic",
                        "module_alias_rebound",
                        f"{module[0]}.{attribute}",
                        bail="module_alias_rebound",
                    )
        for subscript in self._nodes.subscripts:
            if _SYS_MODULES not in {name.name for name in self._names(subscript.value)}:
                continue
            for element in subscript.slice:
                index = element.slice
                if not isinstance(index, cst.Index):  # pragma: no cover - a slice, not a key
                    continue
                text = _string(index.value)
                if text is not None and self._fetches(text):
                    self._claimed.add(id(index.value))
                    self._add(subscript, "dynamic", "dynamic_access", text, bail=_FLAGGED)

    def _resolved(self) -> None:
        """Every node resolving to a legacy name, once per site.

        A dotted chain resolves at every link, so a site is neither a legacy `Attribute`'s link nor
        a callee. The name set is read whole: `genai = None` after the import adds a LOCAL name.
        """
        # libcst resolves a name in a `case {"k": name}` pattern on a node it gives no position.
        for node in sorted((node for node in self._qnp if node in self._pos), key=self._line):
            if id(node) in self._claimed:
                continue
            legacy = self._legacy(node)
            if isinstance(node, cst.SimpleString) and self._spec.shared:
                # A string annotation names the module on the way to what it names.
                legacy = tuple(name for name in legacy if not self._bare(name))
            if not legacy or self._is_link(node) or self._shared_after_call(node):
                continue
            names = self._names(node)
            imports = {n.name for n in names if n.source is QualifiedNameSource.IMPORT}
            symbol = legacy[0]
            if len(imports) > 1:
                self._conditional = True
                reason: ConfidenceReason = "conditional_binding"
            elif any(n.source is QualifiedNameSource.LOCAL for n in names):
                self._rebound = True
                reason = "module_alias_rebound"
            elif symbol in self._spec.legacy_modules:
                # The module used as a value (`g = genai`): `g.*` escapes the prefix rule.
                self._rebound = True
                reason = "module_alias_rebound"
            else:
                reason = self._spelling(node)
            self._add(node, "call" if isinstance(node, cst.Call) else "attribute", reason, symbol)

    def _is_link(self, node: cst.CSTNode) -> bool:
        """Whether this resolving node is part of a site reported elsewhere.

        A subscript always is: libcst gives `X[...]` exactly `X`'s names, and `X` is reported.
        """
        if isinstance(node, cst.Subscript):
            return True
        parent = self._parent(node)
        if isinstance(parent, cst.Attribute) and parent.value is node and self._reaches(parent):
            # In a shared module the call's own row answers for what is read off its result, and
            # the module's namespace is no way round the symbols.
            return not (
                self._spec.shared
                and (isinstance(node, cst.Call) or parent.attr.value in _REFLECTED)
            )
        return isinstance(parent, cst.Call) and parent.func is node

    def _shared_after_call(self, node: cst.CSTNode) -> bool:
        """Whether `node` reads off what a call returned, which the call's own row answers for.

        Only where the module is shared: elsewhere the read is a row of its own, and the one guard
        against a read nobody vetted.
        """
        if not self._spec.shared:
            return False
        if isinstance(node, cst.Call):
            node = node.func
        while isinstance(node, cst.Attribute | cst.Subscript):
            node = node.value
            if isinstance(node, cst.Call):
                return True
        return False

    def _spelling(self, node: cst.CSTNode) -> ConfidenceReason:
        """Which import form bound `node`'s spelling; any other root is the full dotted path."""
        root = _root(self._module, node)
        if root in self._aliased:
            return "alias_resolved"
        if root in self._from_bound:
            return "from_import_resolved"
        return "direct_import_resolved"

    def _mock_targets(self) -> None:
        """A legacy dotted path in a call argument; unlike a string annotation, it never resolves.

        Keyed on argument position: a list of patch callees would be behaviour a pack must carry.
        """
        if "mock_patch_target" not in self._spec.flag_only_patterns:
            return
        for call in self._nodes.calls:
            for argument in call.args:
                node = argument.value
                if id(node) in self._claimed or self._legacy(node):
                    continue
                text = _string(node)
                if text is None or not self._under_legacy(text):
                    continue
                if not self._mention.fullmatch(text):
                    continue
                self._claimed.add(id(node))
                self._add(node, "text_mention", "mock_patch_target", text, bail=_FLAGGED)

    def _star_candidates(self) -> None:
        """A bare name a legacy star import may have bound: an access with no assignment record.

        Nothing resolves it, so the pack's declared surface bounds the candidates.
        """
        if not self._star:
            return
        module = self._spec.legacy_modules[0]
        for scope in _distinct(self._scopes.values()):
            for access in sorted(scope.accesses, key=lambda a: self._line(a.node)):
                node = access.node
                if not isinstance(node, cst.Name) or scope[node.value]:
                    continue
                symbol = f"{module}.{node.value}"
                if symbol not in self._declared:
                    continue
                parent = self._parent(node)
                if isinstance(parent, cst.Call) and parent.func is node:
                    self._produced.setdefault(id(parent), symbol)
                    self._add(parent, "call", "star_import_candidate", symbol)
                else:
                    self._add(node, "attribute", "star_import_candidate", symbol)

    def _bindings(self) -> None:
        """Which names hold a legacy object, and what is done with each.

        `self.<attr>` has no scope record, so it matches on (class, first parameter, attribute), not
        the qualified name. Loops to a fixpoint: `start_chat` needs its receiver known first.
        """
        for call in self._nodes.calls:
            legacy = self._legacy(call)
            if legacy and legacy[0] in self._spec.constructor_symbols:
                self._produced[id(call)] = legacy[0]
        value_of = _assigned_values(self._nodes)
        while True:
            self._receivers = []
            self._method_findings: list[tuple[cst.CSTNode, ConfidenceReason, str]] = []
            self._scope_bindings(value_of)
            self._class_bindings(value_of)
            grown = self._propagate()
            if not grown:
                break
        seen: set[int] = set()
        for node, reason, symbol in self._method_findings:
            # One finding per node: a name assigned twice has two `Assignment`s sharing each access.
            if id(node) in seen:
                continue
            seen.add(id(node))
            self._add(
                node, "method_call" if isinstance(node, cst.Call) else "attribute", reason, symbol
            )

    def _propagate(self) -> bool:
        """Record what a supported method returns, and say whether that is new."""
        grown = False
        for node, _reason, symbol in self._method_findings:
            if not isinstance(node, cst.Call):
                continue
            for entry in self._spec.method_returns:
                if entry.method == symbol and id(node) not in self._produced:
                    self._produced[id(node)] = entry.receiver
                    grown = True
        return grown

    def _scope_bindings(self, value_of: dict[int, cst.BaseExpression]) -> None:
        for scope in _distinct(self._scopes.values()):
            shape = _scope_shape(scope)
            if shape is None:
                continue
            kind, label = shape
            for assignment in sorted(scope.assignments, key=_assignment_key):
                # Skips `ImportAssignment` (its node is the import) and `BuiltinAssignment` (none).
                target = assignment.node if isinstance(assignment, Assignment) else None
                if not isinstance(target, cst.Name):
                    continue
                accesses_of = assignment.references if isinstance(assignment, Assignment) else ()
                held = self._held(value_of.get(id(target)))
                if held is None:
                    continue
                value, receiver = held
                accesses = sorted(accesses_of, key=lambda a: self._line(a.node))
                self._record(
                    kind=kind,
                    name=assignment.name,
                    label=label,
                    receiver=receiver,
                    ctor_line=self._line(value)[0],
                    assignments=len(scope[assignment.name]),
                    accesses=[(access.node, self._scopes.get(access.node)) for access in accesses],
                    scope=scope,
                    escaped=self._exported(assignment.name) if kind == "module_const" else (),
                )

    def _class_bindings(self, value_of: dict[int, cst.BaseExpression]) -> None:
        for class_def in self._nodes.classes:
            held: dict[str, _Held] = {}
            for statement in class_def.body.body:
                if not isinstance(statement, cst.SimpleStatementLine):
                    continue
                for small in statement.body:
                    if not isinstance(small, cst.Assign):
                        continue
                    in_body = self._held(small.value)
                    if in_body is None:
                        continue
                    node, receiver_symbol = in_body
                    for target in small.targets:
                        if isinstance(target.target, cst.Name):
                            _hold(
                                held,
                                target.target.value,
                                _Held(
                                    kind="class_attr",
                                    receiver=receiver_symbol,
                                    ctor_line=self._line(node)[0],
                                    assignments=1,
                                    prefix="",
                                ),
                            )
            methods = [
                (member, _first_param(member))
                for member in class_def.body.body
                if isinstance(member, cst.FunctionDef)
            ]
            for member, first in methods:
                if first is None:
                    continue
                for attribute in _attribute_reads(member, first):
                    held_here = self._held(value_of.get(id(attribute)))
                    if held_here is None:
                        continue
                    value, receiver_symbol = held_here
                    _hold(
                        held,
                        attribute.attr.value,
                        _Held(
                            kind="self_attr",
                            receiver=receiver_symbol,
                            ctor_line=self._line(value)[0],
                            assignments=1,
                            prefix=f"{first}.",
                        ),
                    )
            for name, entry in sorted(held.items()):
                uses: list[tuple[cst.CSTNode, Scope | None]] = []
                # Every write counts, not only constructors: `self.model = None` is one.
                written = 0
                for member, first in methods:
                    if first is None:
                        continue
                    for attribute in _attribute_reads(member, first):
                        if attribute.attr.value != name:
                            continue
                        if id(attribute) in value_of:
                            written += 1
                        else:
                            uses.append((attribute, None))
                self._record(
                    kind=entry.kind,
                    name=f"{entry.prefix}{name}",
                    label=f"class:{class_def.name.value}",
                    receiver=entry.receiver,
                    ctor_line=entry.ctor_line,
                    assignments=written if entry.kind == "self_attr" else entry.assignments,
                    accesses=sorted(uses, key=lambda pair: self._line(pair[0])),
                    scope=None,
                    escaped=self._elsewhere(class_def, name),
                )

    def _elsewhere(self, class_def: cst.ClassDef, name: str) -> tuple[int, ...]:
        """Every line another receiver reaches this class's attribute on: an escape, read or write.

        Only this class's methods and unrelated classes' own first parameters are excluded.
        """
        family = _family(class_def, self._nodes.classes)
        own: set[int] = set()
        for other in self._nodes.classes:
            if other.name.value in family:
                continue
            for member in other.body.body:
                if not isinstance(member, cst.FunctionDef):
                    continue
                first = _first_param(member)
                if first is not None:
                    own.update(id(attribute) for attribute in _attribute_reads(member, first))
        return tuple(
            sorted(
                {
                    self._line(attribute)[0]
                    for attribute in self._nodes.attributes
                    if attribute.attr.value == name and id(attribute) not in own
                }
            )
        )

    def _exported(self, name: str) -> tuple[int, ...]:
        """The `__all__` lines listing `name`: an escape, since another module may import it."""
        return tuple(
            sorted(
                {
                    self._line(string)[0]
                    for string in self._nodes.strings
                    if isinstance(string, cst.SimpleString)
                    and string.evaluated_value == name
                    and self._listed_in_all(string)
                }
            )
        )

    def _listed_in_all(self, string: cst.SimpleString) -> bool:
        element = self._parent(string)
        sequence = self._parent(element) if isinstance(element, cst.Element) else None
        statement = self._parent(sequence) if isinstance(sequence, cst.List | cst.Tuple) else None
        if isinstance(statement, cst.Assign):
            targets = [target.target for target in statement.targets]
        elif isinstance(statement, cst.AugAssign):
            targets = [statement.target]
        else:
            return False
        return any(isinstance(target, cst.Name) and target.value == "__all__" for target in targets)

    def _held(self, value: cst.BaseExpression | None) -> tuple[cst.BaseExpression, str] | None:
        """The legacy object an assigned expression holds, and the node that built it."""
        if value is None:
            return None
        for candidate in _candidates(value):
            receiver = self._produced.get(id(candidate))
            if receiver is not None:
                return candidate, receiver
        return None

    def _record(
        self,
        *,
        kind: BindingKind,
        name: str,
        label: str,
        receiver: str,
        ctor_line: int,
        assignments: int,
        accesses: list[tuple[cst.CSTNode, Scope | None]],
        scope: Scope | None,
        escaped: tuple[int, ...],
    ) -> None:
        use_lines: list[int] = []
        escapes: list[int] = list(escaped)
        for node, access_scope in accesses:
            line = self._line(node)[0]
            use_lines.append(line)
            parent = self._parent(node)
            reason = self._access_reason(kind, scope, access_scope)
            if isinstance(parent, cst.Attribute) and parent.value is node:
                method = parent.attr.value
                grandparent = self._parent(parent)
                if (
                    isinstance(grandparent, cst.Call)
                    and grandparent.func is parent
                    and method in self._spec.methods_for(receiver)
                ):
                    self._method_findings.append((grandparent, reason, f"{receiver}.{method}"))
                    continue
                self._method_findings.append((parent, reason, f"{receiver}.{method}"))
                escapes.append(line)
                continue
            if not _is_comparison(parent):
                escapes.append(line)
        self._receivers.append(
            Receiver(
                kind=kind,
                name=name,
                scope=label,
                receiver=receiver,
                ctor_line=ctor_line,
                assignments=assignments,
                use_lines=tuple(sorted(set(use_lines))),
                escape_lines=tuple(sorted(set(escapes))),
            )
        )

    def _access_reason(
        self, kind: BindingKind, scope: Scope | None, access_scope: Scope | None
    ) -> ConfidenceReason:
        """How the receiver was reached: the access form, not the binding kind."""
        if kind in {"self_attr", "class_attr"}:
            return "receiver_bound_self_attr"
        if scope is not None and access_scope is not scope and isinstance(scope, GlobalScope):
            return "receiver_bound_module_const"
        return "receiver_bound_same_scope"

    def _unresolved_receivers(self) -> None:
        """A supported method on an unresolved receiver, only where a constructor call resolves.

        Otherwise a Vertex `model`, or one built through a rebound alias, gets an invented symbol.
        """
        if not self._produced:
            return
        claimed = {id(node) for node, _reason, _symbol in self._method_findings}
        owners = _method_owners(self._spec)
        for call in self._nodes.calls:
            if id(call) in claimed or not isinstance(call.func, cst.Attribute):
                continue
            owner = owners.get(call.func.attr.value)
            if owner is None or self._legacy(call.func):
                continue
            self._add(
                call,
                "method_call",
                "receiver_unresolved",
                f"{owner}.{call.func.attr.value}",
            )
            self._findings[-1] = Finding(
                **{
                    **self._findings[-1].model_dump(),
                    "scan_status": "needs_review",
                    "bail": "receiver_unresolved",
                }
            )

    def _mentions(self) -> None:
        """The module path in a comment or string on a line with no finding, anchored where it sits.

        No tokenizer: `tokenize` cannot read latin-1 or bare-CR files; libcst already decoded it.
        """
        taken = {finding.line for finding in self._findings}
        found: dict[tuple[int, int], str] = {}
        for node in [*self._nodes.comments, *self._nodes.strings]:
            line, column = self._line(node)
            text = self._module.code_for_node(node)
            for offset, raw in enumerate(text.splitlines()):
                for match in self._mention.finditer(raw):
                    at = line + offset
                    if at in taken or not self._under_legacy(match.group(0)):
                        continue
                    found.setdefault(
                        (at, match.start() + column if offset == 0 else match.start()),
                        match.group(0),
                    )
        for (line, column), symbol in sorted(found.items()):
            self._findings.append(
                Finding(
                    path=self._path,
                    line=line,
                    column=column,
                    kind="text_mention",
                    confidence_reason="string_or_comment_mention",
                    symbol=symbol,
                    evidence=None,
                    scan_status="not_a_usage",
                    bail=None,
                )
            )


def _dotted(node: cst.BaseExpression) -> str:
    """The dotted name of the `Attribute`/`Name` chain in a `from` clause."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        prefix = _dotted(node.value)
        return f"{prefix}.{node.attr.value}" if prefix else ""
    return ""  # pragma: no cover - an import target is always a dotted name


def _root(module: cst.Module, node: cst.CSTNode) -> str:
    """The first segment of how `node` is spelled in the source."""
    if isinstance(node, cst.Call):
        node = node.func
    if isinstance(node, cst.SimpleString):
        value = node.evaluated_value
        text = value if isinstance(value, str) else ""
    else:
        text = module.code_for_node(node)
    return text.partition(".")[0].strip()


def _string(node: cst.CSTNode) -> str | None:
    """The value of a plain string literal, or `None` if it is not one."""
    if not isinstance(node, cst.SimpleString):
        return None
    value = node.evaluated_value
    return value if isinstance(value, str) else None


def _bound_names(statement: cst.Import | cst.ImportFrom) -> list[str]:
    """The local names an import binds: `a` for `import a.b`, else exactly what is spelled."""
    if isinstance(statement.names, cst.ImportStar):  # pragma: no cover - guarded by the caller
        return []
    return [
        alias.evaluated_alias or alias.evaluated_name.partition(".")[0] for alias in statement.names
    ]


def _distinct(scopes: Iterable[Scope | None]) -> list[Scope]:
    """Each scope once, in resolution order; some nodes map to `None`."""
    return list({id(scope): scope for scope in scopes if scope is not None}.values())


def _scope_shape(scope: Scope) -> tuple[BindingKind, str] | None:
    """`Binding.kind` and `Binding.scope` for a libcst scope, or `None` to skip.

    A comprehension is skipped: `Binding.scope` cannot spell it.
    """
    if isinstance(scope, GlobalScope):
        return "module_const", "module"
    if isinstance(scope, ClassScope):
        # Left to `_class_bindings`: only it finds the uses, as `self.<attr>` has no scope record.
        return None
    if isinstance(scope, FunctionScope):
        return ("name", f"function:{scope.name}") if scope.name else None
    return None


def _assignment_key(assignment: BaseAssignment) -> tuple[str, str]:
    return assignment.name, type(assignment).__name__


def _assigned_values(nodes: _Nodes) -> dict[int, cst.BaseExpression]:
    """Target node -> assigned value; also keeps an assignment target out of `use_lines`."""
    values: dict[int, cst.BaseExpression] = {}
    for assign in nodes.assigns:
        for target in assign.targets:
            values[id(target.target)] = assign.value
    for ann_assign in nodes.ann_assigns:
        if ann_assign.value is not None:
            values[id(ann_assign.target)] = ann_assign.value
    return values


def _candidates(value: cst.BaseExpression) -> list[cst.BaseExpression]:
    """The expression, or both branches of `a if c else b` / `a or b`, either of which may bind."""
    if isinstance(value, cst.IfExp):
        return [value.body, value.orelse]
    if isinstance(value, cst.BooleanOperation):
        return [value.left, value.right]
    return [value]


def _hold(held: dict[str, _Held], name: str, entry: _Held) -> None:
    """Record a class attribute holding a legacy object and count its assignments.

    The first constructor wins, since a class body runs before `__init__`.
    """
    previous = held.get(name)
    held[name] = (
        entry
        if previous is None
        else _Held(
            kind=previous.kind,
            receiver=previous.receiver,
            ctor_line=previous.ctor_line,
            assignments=previous.assignments + 1,
            prefix=previous.prefix,
        )
    )


def _first_param(function: cst.FunctionDef) -> str | None:
    params = function.params.params
    return params[0].name.value if params else None


def _family(class_def: cst.ClassDef, classes: Sequence[cst.ClassDef]) -> set[str]:
    """Names of this file's classes deriving from `class_def` at any depth, excluding itself.

    Bare-name bases only; a base precedes its subclass, so one pass finds every depth.
    """
    family = {class_def.name.value}
    for other in classes:
        if any(
            isinstance(base.value, cst.Name) and base.value.value in family for base in other.bases
        ):
            family.add(other.name.value)
    return family - {class_def.name.value}


def _attribute_reads(function: cst.FunctionDef, first: str) -> list[cst.Attribute]:
    """Every `<first>.<attr>` node inside `function`, in source order."""
    collector = _Attributes(first)
    function.visit(collector)
    return collector.found


class _Attributes(cst.CSTVisitor):
    def __init__(self, first: str) -> None:
        self.first = first
        self.found: list[cst.Attribute] = []

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if isinstance(node.value, cst.Name) and node.value.value == self.first:
            self.found.append(node)


def _is_comparison(parent: cst.CSTNode | None) -> bool:
    return isinstance(parent, cst.Comparison | cst.ComparisonTarget)


def _method_owners(spec: ScanSpec) -> dict[str, str]:
    """Method name -> the one receiver that has it; a shared method has no symbol to report."""
    owners: dict[str, str] = {}
    shared: set[str] = set()
    for entry in spec.supported_methods:
        for method in entry.methods:
            if method in owners:
                shared.add(method)
            owners[method] = entry.receiver
    for method in shared:
        del owners[method]
    return owners


__all__ = ["BAILS", "RUNG", "Analysis", "Receiver", "analyse"]
