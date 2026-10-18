"""Whether an untrusted model proposal may become an edit, and the refusal word if not.

Writes nothing. Checks run in a fixed order and the first failure is recorded (an escape before an
unplanned file). An acceptance carries the exact bytes checked, so no caller re-splices them. It
proves an edit safe to apply, not correct: an accepted proposal is still a review item.
"""

from __future__ import annotations

import difflib
import io
import itertools
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

import libcst as cst
from libcst.metadata import ExpressionContext, ExpressionContextProvider, PositionProvider

from obelize import fsutil
from obelize.models import terminal_unsafe
from obelize.native import files
from obelize.packs.schema import under_any
from obelize.providers import base
from obelize.verify import cheap, redact

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from obelize.models import EditProposal, GuardRefusal

# Max replacement lines: the largest context a model can be shown (which bounds the removed side).
REPLACEMENT_LINE_LIMIT = base.CONTEXT_LINE_LIMIT

# In UTF-8 bytes, as the line limit does not bound one huge line; 1 KiB a line dwarfs any formatter.
REPLACEMENT_BYTE_LIMIT = 1024 * REPLACEMENT_LINE_LIMIT

# Tokens in the longest statement a replacement may hold. libcst's parser overruns the C stack and
# kills the process on a chain of about 13,000 `or` terms, which `compile()` takes, and on Python
# 3.15 on about a thousand tokens of any chain per MiB of stack, measured. A statement is never
# deeper than its tokens, a chain past a few hundred levels is refused after the parse anyway, and
# nobody reviews a call of this many tokens as a rewrite.
REPLACEMENT_STATEMENT_TOKENS = 500

# A call-shaped import of a non-literal module; under no module, so a new one is refused.
DYNAMIC_IMPORT = "<computed>"

# Import calls; the bare name covers a file that already did `from importlib import import_module`.
# Without these, `__import__("os").system(...)` would pass where `import os` is refused.
IMPORT_FUNCTIONS = frozenset({"__import__", "importlib.import_module", "import_module"})

# Builtins a replacement may name unprompted. Deliberately absent: anything reaching the filesystem,
# process, interpreter or attributes by string (`open`, `exec`, `eval`, `compile`, `getattr`,
# `setattr`, `globals`, `vars`, `input`, `breakpoint`, `__import__`) and every dunder.
ADMITTED_BUILTINS = frozenset(
    {
        "Exception", "False", "KeyError", "None", "RuntimeError", "True", "TypeError",
        "ValueError", "all", "any", "bool", "bytes", "dict", "enumerate", "float",
        "classmethod", "frozenset", "int", "isinstance", "len", "list", "max", "min", "object",
        "property", "range", "repr", "set", "sorted", "staticmethod", "str", "sum", "super",
        "tuple", "zip",
    }
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Checked:
    """One proposal and its verdict; `after`, the whole file to write, is set iff `refusal` is None.

    `detail` is one line naming the values decided on, never an absolute path: evidence gets
    attached to public issues.
    """

    proposal: EditProposal
    refusal: GuardRefusal | None
    detail: str
    after: bytes | None = None
    # (line, count) for each run of lines the proposal's imports added, in the numbering of the file
    # as it was sent: a line at or below one is `count` lines further down in `after`.
    shifts: tuple[tuple[int, int], ...] = ()

    @property
    def accepted(self) -> bool:
        return self.refusal is None


def check(
    proposal: EditProposal,
    *,
    consultation: base.Consultation,
    root: Path,
    before: bytes,
) -> Checked:
    """Every check over one proposal, in order; the first refusal wins.

    `before`: the bytes the plan was built from (`codemod.Outcome.before`). Only the proposal's
    own file is read from `root`.
    """
    refused = _admissible(proposal, consultation, root, before)
    if refused is not None:
        return Checked(proposal, refused[0], refused[1])
    try:
        return _produced(proposal, consultation, before)
    except (RecursionError, MemoryError):
        # libcst's tree walks take a few frames a level, so a reply that compiles can still
        # overrun the stack a few hundred levels down.
        return Checked(
            proposal,
            "output_does_not_parse",
            f"{proposal.path}: nested more deeply than obelize reads",
        )


def _admissible(
    proposal: EditProposal,
    consultation: base.Consultation,
    root: Path,
    before: bytes,
) -> tuple[GuardRefusal, str] | None:
    escape = _escape(proposal.path)
    if escape is not None:
        return "path_outside_root", f"{proposal.path!r}: {escape}"
    if not proposal.path.endswith(".py"):
        return "path_not_python", f"{proposal.path!r} is not a Python file"
    if proposal.path != consultation.context.path:
        return (
            "path_not_the_consulted_file",
            f"the question was about {consultation.context.path!r} and the proposal edits "
            f"{proposal.path!r}",
        )
    stale = _stale(root, proposal.path, before)
    if stale is not None:
        return "file_changed_since_read", stale
    return None


def _escape(path: str) -> str | None:
    """Why this text names no file inside the repository, or `None`.

    `models._relative_posix_path`'s rules and the system's reserved names on the text, so no
    race; `_stale` and `fsutil.write` guard the disk. The absolute rule is redundant but kept for
    its sentence, which tests assert.
    """
    if "\\" in path:
        return "a repository path uses forward slashes on every platform"
    if path.startswith("/"):
        return "the path is absolute"
    parts = path.split("/")
    if ".." in parts:
        return "the path climbs out of the repository"
    if "" in parts:
        # Also the empty path: `"".split("/")` is `[""]`.
        return "the path holds an empty component"
    if files.reserved(path):
        return "this system opens the name as something else: a device, a stream or another file"
    return None


def _stale(root: Path, path: str, before: bytes) -> str | None:
    """Why the file on disk is not the one the plan read, or `None`.

    Reads with `fsutil.read` (`O_NOFOLLOW`, like the write). Changed, gone, a link or unreadable
    are one refusal: the proposal's line numbers address a document that is not there.
    """
    try:
        now = fsutil.read(root / path)
    except OSError as error:
        return f"{path} cannot be read: {error.strerror}"
    if fsutil.sha256(now) != fsutil.sha256(before):
        return f"{path} is not the file the plan read"
    return None


def _produced(
    proposal: EditProposal,
    consultation: base.Consultation,
    before: bytes,
) -> Checked:
    """Where the edit lands, and what it makes of the file."""
    source = cst.parse_module(before)
    lines = base.split_lines(before.decode(source.encoding))
    misplaced = _placed(proposal, consultation, len(lines))
    if misplaced is not None:
        return Checked(proposal, misplaced[0], misplaced[1])

    parts = base.LINE_BREAK.split(proposal.replacement)
    if len(parts) > REPLACEMENT_LINE_LIMIT:
        return Checked(
            proposal,
            "replacement_too_large",
            f"the replacement is {len(parts)} lines and the limit is {REPLACEMENT_LINE_LIMIT}",
        )
    size = len(proposal.replacement.encode("utf-8"))
    if size > REPLACEMENT_BYTE_LIMIT:
        return Checked(
            proposal,
            "replacement_too_large",
            f"the replacement is {size} bytes and the limit is {REPLACEMENT_BYTE_LIMIT}",
        )
    # What a reviewer reads must be what runs (TM-1); only tab and line breaks are allowed.
    unsafe = terminal_unsafe(proposal.replacement, allowed="\t\r\n")
    if unsafe is not None:
        return Checked(
            proposal,
            "replacement_not_displayable",
            f"the replacement carries a character a terminal acts on instead of printing: {unsafe}",
        )

    # The model was shown `[REDACTED...]` where a secret stood, so a marker it echoes would be
    # written into the file as text, unless the lines it replaces already hold one.
    marker = redact.REDACTED[:-1]
    if marker in proposal.replacement and marker not in "".join(
        lines[proposal.start_line - 1 : proposal.end_line]
    ):
        return Checked(
            proposal,
            "replacement_carries_redaction",
            f"the replacement holds {marker!r}, a placeholder for a secret the model was shown "
            f"instead of the value, and the lines it replaces hold none",
        )

    shifts: tuple[tuple[int, int], ...] = ()
    if proposal.imports:
        made = _with_imports(source, lines, proposal, consultation.to_modules)
        if not isinstance(made, _Imported):
            return Checked(proposal, *made)
        source, lines, shifts = made
    # The proposal where it lies in `lines`, which its imports may have pushed down.
    moved = sum(count for at, count in shifts if at <= proposal.start_line)
    placed = proposal.model_copy(
        update={"start_line": proposal.start_line + moved, "end_line": proposal.end_line + moved}
    )
    spliced = _spliced(parts, lines[placed.start_line - 1 : placed.end_line])
    text = "".join([*lines[: placed.start_line - 1], *spliced, *lines[placed.end_line :]])
    try:
        after = text.encode(source.encoding)
    except UnicodeEncodeError as error:
        return Checked(
            proposal,
            "replacement_not_encodable",
            f"{proposal.path} is {source.encoding} and the replacement holds "
            f"{error.object[error.start : error.end]!r}",
        )

    # `compile()` first: it answers most deeply nested expressions with an exception, where libcst's
    # parser overruns the C stack and kills the process (`scan.parse.gates` orders them so too). It
    # takes the rest, so the longest statement is bounded before libcst sees it.
    try:
        compile(after, proposal.path, "exec")
    except cheap.COMPILE_REFUSALS as error:
        return Checked(proposal, "output_does_not_compile", f"{proposal.path}: {_said(error)}")
    last = placed.start_line + len(parts) - 1
    tokens = _tokens(text, last)
    longest = _longest_statement(tokens, placed.start_line)
    if longest > REPLACEMENT_STATEMENT_TOKENS:
        return Checked(
            proposal,
            "replacement_too_large",
            f"a statement of the replacement is {longest} tokens and the limit is "
            f"{REPLACEMENT_STATEMENT_TOKENS}",
        )
    try:
        result = cst.parse_module(after)
    except (cst.ParserSyntaxError, SyntaxError) as error:
        return Checked(proposal, "output_does_not_parse", f"{proposal.path}: {_said(error)}")

    if _runs_past(tokens):
        return Checked(
            proposal,
            "replacement_runs_past_its_range",
            f"the replacement of lines {proposal.start_line}..{proposal.end_line} changes how "
            f"the lines after them are read",
        )

    added = sorted(_imports(result) - _imports(source))
    outside = [name for name in added if not under_any(name, consultation.to_modules)]
    if outside:
        return Checked(
            proposal,
            "import_outside_the_target",
            f"the result imports {outside}, and this pack targets {list(consultation.to_modules)}",
        )

    unlicensed = _unlicensed(source, result, placed, last, consultation.to_modules)
    if unlicensed:
        return Checked(
            proposal,
            "name_outside_the_question",
            f"the replacement names {unlicensed}, which neither the lines it replaces, nor "
            f"the modules this pack targets, nor the builtins a replacement may use provide",
        )
    return Checked(
        proposal,
        None,
        f"{proposal.path} lines {proposal.start_line}..{proposal.end_line}, "
        f"{proposal.end_line - proposal.start_line + 1} replaced by {len(parts)}",
        after,
        shifts,
    )


_Body = list[cst.SimpleStatementLine | cst.BaseCompoundStatement]


class _Imported(NamedTuple):
    """The file with a proposal's imports added, and where that put lines in it."""

    source: cst.Module
    lines: list[str]
    shifts: tuple[tuple[int, int], ...]


def _with_imports(
    source: cst.Module,
    lines: Sequence[str],
    proposal: EditProposal,
    targets: tuple[str, ...],
) -> _Imported | tuple[GuardRefusal, str]:
    """`source` with the proposal's imports at module level, or why one is refused.

    Each is one absolute `import` or `from ... import` of a target module. A name joins the file's
    own `from m import ...` line when there is a plain one, else a line of its own follows the
    imports at the top. Neither may touch a line the proposal replaces.
    """
    smalls: list[cst.Import | cst.ImportFrom] = []
    for entry in proposal.imports:
        small = _one_import(entry)
        if isinstance(small, str):
            return "output_does_not_parse", f"import {entry!r}: {small}"
        smalls.append(small)
    outside = sorted(
        name
        for small in smalls
        for name in _imports(cst.Module(body=[cst.SimpleStatementLine(body=[small])]))
        if not under_any(name, targets)
    )
    if outside:
        return (
            "import_outside_the_target",
            f"the proposal imports {outside}, and this pack targets {list(targets)}",
        )
    body: _Body = list(source.body)
    for small in smalls:
        body = _joined(body, small)
    joined = source.with_changes(body=body)
    new = base.split_lines(joined.code)
    shifts: list[tuple[int, int]] = []
    first, last = proposal.start_line, proposal.end_line
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, lines, new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        # Lines `i1 + 1`..`i2` were changed; an insertion changes none, and lands before `i1 + 1`.
        if (first <= i2 and i1 < last and tag != "insert") or first < i1 + 1 <= last:
            return (
                "replacement_runs_past_its_range",
                f"an import cannot be added without changing lines {first}..{last}, "
                f"which the proposal replaces",
            )
        if (grew := (j2 - j1) - (i2 - i1)) and tag != "replace":
            shifts.append((i1 + 1, grew))
        elif grew:
            shifts.append((i2 + 1, grew))
    return _Imported(joined, new, tuple(shifts))


def _one_import(entry: str) -> cst.Import | cst.ImportFrom | str:
    """The one import statement `entry` is, or why it is not one."""
    try:
        statement = cst.parse_statement(entry)
    except (cst.ParserSyntaxError, SyntaxError) as error:
        return _said(error)
    if isinstance(statement, cst.SimpleStatementLine) and len(statement.body) == 1:
        small = statement.body[0]
        if isinstance(small, cst.Import) or (
            isinstance(small, cst.ImportFrom) and not isinstance(small.names, cst.ImportStar)
        ):
            return small
    return "not one import of named things"


def _joined(body: _Body, small: cst.Import | cst.ImportFrom) -> _Body:
    """`body` with `small` imported: already, or by a name added to a plain line, or on its own."""
    start = 1 if body and _docstring(body[0]) else 0
    run = list(itertools.takewhile(lambda at: _imports_only(body[at]), range(start, len(body))))
    wanted = cst.Module(body=[]).code_for_node(small).strip()
    for index in run:
        line = body[index]
        assert isinstance(line, cst.SimpleStatementLine)  # noqa: S101 - `_imports_only` said so
        for held in line.body:
            if cst.Module(body=[]).code_for_node(held).strip() == wanted:
                return body
        held = line.body[0]
        if (
            len(line.body) == 1
            and isinstance(small, cst.ImportFrom)
            and isinstance(held, cst.ImportFrom)
            and not isinstance(small.names, cst.ImportStar)
            and not isinstance(held.names, cst.ImportStar)
            and _plain_from(held, small)
        ):
            fresh = [
                alias
                for alias in small.names
                if all(_key(alias) != _key(have) for have in held.names)
            ]
            if not fresh:
                return body
            comma = cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
            names = [*held.names[:-1], held.names[-1].with_changes(comma=comma), *fresh]
            added = line.with_changes(body=[held.with_changes(names=names)])
            return [*body[:index], added, *body[index + 1 :]]
    at = run[-1] + 1 if run else start
    return [*body[:at], cst.SimpleStatementLine(body=[small]), *body[at:]]


def _docstring(statement: cst.BaseStatement) -> bool:
    return (
        isinstance(statement, cst.SimpleStatementLine)
        and len(statement.body) == 1
        and isinstance(statement.body[0], cst.Expr)
        and isinstance(statement.body[0].value, cst.SimpleString | cst.ConcatenatedString)
    )


def _imports_only(statement: cst.BaseStatement) -> bool:
    return isinstance(statement, cst.SimpleStatementLine) and all(
        isinstance(small, cst.Import | cst.ImportFrom) for small in statement.body
    )


def _plain_from(held: cst.ImportFrom, small: cst.ImportFrom) -> bool:
    """Whether `held` is `from m import a, b` with no parenthesis, `m` being `small`'s module."""
    return (
        not isinstance(held.names, cst.ImportStar)
        and held.lpar is None
        and not held.relative
        and not small.relative
        and _dotted(held.module) == _dotted(small.module)  # type: ignore[arg-type]
        and held.names[-1].comma is cst.MaybeSentinel.DEFAULT
    )


def _key(alias: cst.ImportAlias) -> tuple[str | None, str | None]:
    return _dotted(alias.name), _alias(alias)


def _placed(
    proposal: EditProposal,
    consultation: base.Consultation,
    total: int,
) -> tuple[GuardRefusal, str] | None:
    """Whether this answers the question that was asked."""
    context = consultation.context
    if not context.holds(proposal.start_line, proposal.end_line) or proposal.end_line > total:
        return (
            "outside_the_context",
            f"the proposal replaces lines {proposal.start_line}..{proposal.end_line} and "
            f"lines {context.start_line}..{context.end_line} of {total} were sent",
        )
    if not proposal.start_line <= consultation.line <= proposal.end_line:
        return (
            "site_not_replaced",
            f"the question was about line {consultation.line} and the proposal replaces "
            f"{proposal.start_line}..{proposal.end_line}",
        )
    if proposal.symbol != consultation.symbol:
        # Also refuses a consultation with no symbol: `EditProposal.symbol` is a non-empty str.
        return (
            "symbol_mismatch",
            f"the question was about {consultation.symbol!r} and the proposal names "
            f"{proposal.symbol!r}",
        )
    differs = _misquoted(proposal, context)
    return None if differs is None else ("replaced_text_differs", differs)


def _misquoted(proposal: EditProposal, context: base.Context) -> str | None:
    """Why the text the proposal says it replaces is not what its lines were sent as, or `None`.

    Against the context as sent, redacted, so the model is held to what it read. Compared without
    trailing whitespace or line break, and without blank lines at the end of either: a quote joined
    with newlines has no tail where the range ends in a blank line. A redaction that joined lines
    leaves fewer lines than the range, so no number can be trusted, and nothing is accepted.
    """
    shown = base.split_lines(context.text)
    if len(shown) != context.end_line - context.start_line + 1:
        return (
            f"redaction joined lines of the {context.start_line}..{context.end_line} sent, so "
            f"what lines {proposal.start_line}..{proposal.end_line} held cannot be checked"
        )
    first = proposal.start_line - context.start_line
    held = shown[first : first + proposal.end_line - proposal.start_line + 1]
    if _text(held) != _text(base.split_lines(proposal.replaces)):
        return (
            "the text the proposal says it replaces is not the text of lines "
            f"{proposal.start_line}..{proposal.end_line} as they were sent"
        )
    return None


def _text(lines: Sequence[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).rstrip()


def _spliced(parts: Sequence[str], replaced: Sequence[str]) -> list[str]:
    """The replacement's lines, terminated like the lines they replace.

    The last new line takes the last replaced line's terminator (maybe none), the rest take the
    file's own, so CRLF and a missing final newline survive.
    """
    terminators = [_terminator(line) for line in replaced]
    inner = next((one for one in terminators if one), "\n")
    last = terminators[-1]
    return [part + (last if index == len(parts) - 1 else inner) for index, part in enumerate(parts)]


def _terminator(line: str) -> str:
    """The line break this line ends with, or `""` for the last line of a file."""
    match = base.LINE_BREAK.search(line)
    return match.group() if match else ""


def _said(error: BaseException) -> str:
    """The parser's message alone; the rendered form would put the file's path into evidence."""
    return str(getattr(error, "msg", None) or error)


def _imports(module: cst.Module) -> set[str]:
    """Every module this file imports, by the name the statement spells."""
    collector = _Imports()
    module.visit(collector)
    return collector.found


class _Imports(cst.CSTVisitor):
    """`import`, `from ... import`, and the two calls that are imports.

    `from X import Y` is `X.Y`, so `from google import genai` is under the target and `from os
    import system` is not. Relative imports (`.x`) are under nothing, so a new one is refused.
    """

    def __init__(self) -> None:
        super().__init__()
        self.found: set[str] = set()

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            self.found.add(_dotted(alias.name) or DYNAMIC_IMPORT)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        module = "" if node.module is None else (_dotted(node.module) or DYNAMIC_IMPORT)
        stem = "." * len(node.relative) + module
        if isinstance(node.names, cst.ImportStar):
            self.found.add(stem)
            return
        joined = stem if stem.endswith(".") else f"{stem}."
        for alias in node.names:
            self.found.add(joined + (_dotted(alias.name) or DYNAMIC_IMPORT))

    def visit_Call(self, node: cst.Call) -> None:
        if _dotted(node.func) not in IMPORT_FUNCTIONS:
            return
        first = node.args[0].value if node.args else None
        named = first.evaluated_value if isinstance(first, cst.SimpleString) else None
        self.found.add(named if isinstance(named, str) else DYNAMIC_IMPORT)


def _tokens(text: str, last: int) -> list[tokenize.TokenInfo]:
    """The file's tokens up to line `last`, where the replacement ends."""
    every = tokenize.generate_tokens(io.StringIO(text).readline)
    return list(itertools.takewhile(lambda token: token.start[0] <= last, every))


def _longest_statement(tokens: Sequence[tokenize.TokenInfo], first: int) -> int:
    """The token count of the longest statement, from line `first` on, in `tokens`."""
    longest = run = 0
    for token in tokens:
        if token.start[0] >= first and token.type not in _TRIVIA:
            run = 0 if token.type == tokenize.NEWLINE else run + 1
            longest = max(longest, run)
    return longest


def _runs_past(tokens: Sequence[tokenize.TokenInfo]) -> bool:
    """Whether the replacement reaches into the lines after its range.

    True when its last token ends no statement (a backslash, open bracket or string), which still
    parses and compiles. An opened block cannot capture the lines below: `compile()` checked that.
    """
    closing = [token for token in tokens if token.type not in _TRIVIA]
    return bool(closing) and closing[-1].type != tokenize.NEWLINE


# Tokens that end no statement and start none: a comment, and a blank line's break.
_TRIVIA = frozenset({tokenize.COMMENT, tokenize.NL})


def _unlicensed(
    source: cst.Module,
    result: cst.Module,
    proposal: EditProposal,
    last: int,
    targets: tuple[str, ...],
) -> list[str]:
    """The names the replacement reaches for that the question never licensed.

    Licensed: in the replaced lines, bound by a target import or the replacement, or admitted
    builtins; never a dunder. Catches `exec("import os")`, `open(...)`, an already-imported module.
    """
    named = _Named(proposal.start_line, proposal.end_line)
    cst.MetadataWrapper(source).visit(named)
    used = _Used(proposal.start_line, last)
    cst.MetadataWrapper(result).visit(used)
    licensed = named.found | used.bound | ADMITTED_BUILTINS | _bound_by_targets(result, targets)
    return sorted({*used.dunders, *(name for name in used.loaded if name not in licensed)})


class _Named(cst.CSTVisitor):
    """Every name spelled on lines `first`..`last`, in any role."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, first: int, last: int) -> None:
        super().__init__()
        self.first, self.last = first, last
        self.found: set[str] = set()

    def visit_Name(self, node: cst.Name) -> None:
        if self.first <= self.get_metadata(PositionProvider, node).start.line <= self.last:
            self.found.add(node.value)


class _Used(cst.CSTVisitor):
    """The names a replacement reads, the names it binds, and its dunders.

    An attribute's or keyword's own name is not read (`client.models` reads `client`). A binding is
    a libcst STORE context. Names in an import are module paths, left to `_bound_by_targets`.
    """

    METADATA_DEPENDENCIES = (PositionProvider, ExpressionContextProvider)

    def __init__(self, first: int, last: int) -> None:
        super().__init__()
        self.first, self.last = first, last
        self.loaded: set[str] = set()
        self.bound: set[str] = set()
        self.dunders: set[str] = set()
        self._roles: set[int] = set()

    def _inside(self, node: cst.CSTNode) -> bool:
        return self.first <= self.get_metadata(PositionProvider, node).start.line <= self.last

    def visit_Import(self, node: cst.Import) -> bool:
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        return False

    def visit_Attribute(self, node: cst.Attribute) -> None:
        self._roles.add(id(node.attr))
        if _dunder(node.attr.value) and self._inside(node):
            self.dunders.add(node.attr.value)

    def visit_Arg(self, node: cst.Arg) -> None:
        if node.keyword is not None:
            self._roles.add(id(node.keyword))

    def visit_Name(self, node: cst.Name) -> None:
        if id(node) in self._roles or not self._inside(node):
            return
        if _dunder(node.value):
            self.dunders.add(node.value)
        elif self.get_metadata(ExpressionContextProvider, node, None) is ExpressionContext.STORE:
            self.bound.add(node.value)
        else:
            self.loaded.add(node.value)


def _dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _bound_by_targets(module: cst.Module, targets: tuple[str, ...]) -> set[str]:
    """The names an import of one of the pack's target modules binds, anywhere."""
    collector = _TargetBindings(targets)
    module.visit(collector)
    return collector.bound


class _TargetBindings(cst.CSTVisitor):
    """`import google.genai` binds `google`, `from google import genai as g` binds `g`."""

    def __init__(self, targets: tuple[str, ...]) -> None:
        super().__init__()
        self.targets = targets
        self.bound: set[str] = set()

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            dotted = _dotted(alias.name) or DYNAMIC_IMPORT
            if under_any(dotted, self.targets):
                self.bound.add(_alias(alias) or dotted.split(".")[0])

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if isinstance(node.names, cst.ImportStar):
            return
        stem = "" if node.module is None else (_dotted(node.module) or DYNAMIC_IMPORT)
        for alias in node.names:
            name = _dotted(alias.name) or DYNAMIC_IMPORT
            if under_any(f"{stem}.{name}", self.targets):
                self.bound.add(_alias(alias) or name)


def _alias(alias: cst.ImportAlias) -> str | None:
    if alias.asname is None or not isinstance(alias.asname.name, cst.Name):
        return None
    return alias.asname.name.value


def _dotted(node: cst.BaseExpression) -> str | None:
    """A `Name` or `Attribute` chain as one dotted string; anything else is `None`.

    The `or DYNAMIC_IMPORT` fallbacks above make an alias shape libcst widens later fail closed
    rather than vanish from the set.
    """
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        prefix = _dotted(node.value)
        return None if prefix is None else f"{prefix}.{node.attr.value}"
    return None


__all__ = [
    "ADMITTED_BUILTINS",
    "DYNAMIC_IMPORT",
    "IMPORT_FUNCTIONS",
    "REPLACEMENT_BYTE_LIMIT",
    "REPLACEMENT_LINE_LIMIT",
    "REPLACEMENT_STATEMENT_TOKENS",
    "Checked",
    "check",
]
