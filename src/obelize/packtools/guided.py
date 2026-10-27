"""Claims drafted from a migration guide, and the checks that decide which become part of a pack.

A model reads the guide and drafts claims (ADR-075); nothing it says is believed. A claim is kept
only when its quote is in the guide, its names are in the two releases, its pattern is one a pack
may hold and the API diff does not contradict it. What it becomes is the least: a report for a
person. It becomes a rewrite only where the diff independently shows the old name removed or
deprecated and the new one there to take its place. Every claim not kept is counted under one
closed reason, so none is dropped unsaid.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args
from urllib.parse import urlsplit

import libcst as cst
import libcst.matchers as m
from pydantic import ValidationError

from obelize import index, pattern
from obelize.apidiff.diff import accepts, takes
from obelize.models import CallShape
from obelize.models.fields import DISPLAY_TEXT_LIMIT, printable
from obelize.net import NetworkError
from obelize.packs.schema import (
    FlagOnlyParams,
    PackSource,
    RenameMemberParams,
    RenameSymbolParams,
    RewritePatternParams,
)
from obelize.packtools import guide as guides
from obelize.providers import base
from obelize.providers import claims as drafting

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from obelize.apidiff.diff import ApiChange
    from obelize.apidiff.surface import Obj, Param
    from obelize.net import Fetcher

# The shortest quote that can carry a claim, and the most claims one quote may carry.
MIN_QUOTE: Final = 30
MAX_PER_QUOTE: Final = 3
# The most claims kept in one pack: each has words of its own to read.
MAX_KEPT: Final = 60
RECORD: Final = "guide.json"
RECORD_BYTES: Final = 8 << 20
# The model is not asked for the rest of the parts after this many failures one after another, or
# once the guide has taken this long; the claims drafted so far are still held to the checks.
MAX_FAILURES: Final = 2
DEADLINE_S: Final = 1800.0
Stopped = Literal["failures", "deadline"]
STOPS: Final = get_args(Stopped)
_AFTER: Final = {"failures": f"{MAX_FAILURES} failures one after another", "deadline": "too long"}
_PLACED: Final = ("positional-only", "positional or keyword")
_KEYED: Final = ("positional or keyword", "keyword-only")

Reason = Literal[
    "malformed",
    "quote_missing",
    "quote_weak",
    "quote_reused",
    "legacy_unknown",
    "new_unknown",
    "keyword_unknown",
    "out_of_scope",
    "pattern_refused",
    "params_refused",
    "contradicts_diff",
    "in_the_diff",
    "repeated",
    "too_many",
    "pack_failed",
]
REASONS: Final = get_args(Reason)
Route = Literal["flag", "rename", "member", "pattern"]
Refused = tuple[Reason, str]
Fit = Literal["fits", "misfits", "unknown", "missing"]


@dataclass(frozen=True, slots=True)
class Names:
    """What the model is told: the library, its two releases and the module compared."""

    distribution: str
    old: str
    new: str
    module: str


@dataclass(frozen=True, slots=True)
class Cite:
    """Where a claim was read: the citation text, and for an https guide its address and hash."""

    text: str
    ref: str
    url: str | None
    sha256: str
    official: bool

    def source(self, retrieved: dt.date) -> PackSource | None:
        """The pack's record of the guide, if its address is one a pack may cite."""
        kind = "official_guide" if self.official else "guide"
        try:
            return PackSource.model_validate(
                {"type": kind, "url": self.url, "retrieved_at": retrieved, "sha256": self.sha256}
            )
        except ValidationError:
            return None


@dataclass(frozen=True, slots=True)
class Piece:
    """One guide, and what the model said to each of its chunks (`None` where it failed)."""

    guide: guides.Guide
    official: bool
    replies: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class Drafted:
    """Everything the model said, before any of it is believed."""

    pieces: tuple[Piece, ...]
    provider: str
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    # Why the model was not asked for the rest, and how many parts that left unasked.
    stopped: Stopped | None = None
    unasked: int = 0


@dataclass(frozen=True, slots=True)
class Accepted:
    """A claim the checks kept, and what it becomes. Paths are below the module."""

    claim: drafting.Claim
    cite: Cite
    route: Route
    path: str
    target: str | None = None
    # A rename: whether a call of the name is rewritten too. A member rename: the keywords the new
    # method takes. A flag: the calls it is about. A pattern: the class of its receiver and the
    # modules it reaches names through.
    calls: bool = False
    takes: tuple[str, ...] | None = None
    shape: CallShape | None = None
    where: Mapping[str, str] = field(default_factory=dict)
    imports: tuple[str, ...] = ()

    @property
    def automatic(self) -> bool:
        return self.route != "flag"

    def words(self) -> tuple[str, str]:
        """What a report of the claim says, and what it advises."""
        claim = self.claim
        if claim.kind == "rewrite_pattern":
            advice = f"Write {claim.before} as {claim.after}."
        else:
            advice = f"Use {claim.new}." if claim.new else "Follow the guide."
        said = f"The migration guide says: {guides.flat(claim.quote)}"
        return _cut(printable(said)), _cut(printable(advice))


@dataclass(frozen=True, slots=True)
class Outcome:
    """What became of the claims: kept, rejected by reason, and the answers that were no answer."""

    drafted: Drafted
    accepted: tuple[Accepted, ...]
    rejected: Mapping[str, int]
    # Answers that were not the shape asked for, and chunks the model did not answer.
    refused: int
    failed: int
    rows: tuple[tuple[str, str, str], ...] = ()

    @property
    def claims(self) -> int:
        return len(self.accepted) + sum(self.rejected.values())

    def line(self) -> str:
        """One line for the person: the counts, and under which reason the rest went."""
        automatic = sum(one.automatic for one in self.accepted)
        parts = [
            f"{self.claims} claim(s) drafted, {len(self.accepted)} kept ({automatic} as a rewrite, "
            f"{len(self.accepted) - automatic} to report)"
        ]
        if self.rejected:
            parts.append("rejected: " + ", ".join(f"{k} {v}" for k, v in self.rejected.items()))
        if self.refused or self.failed:
            parts.append(f"{self.refused} answer(s) refused, {self.failed} not given")
        if self.drafted.stopped:
            parts.append(
                f"stopped after {_AFTER[self.drafted.stopped]}, "
                f"{self.drafted.unasked} part(s) not asked"
            )
        return "; ".join(parts) + "."

    def document(self, retrieved: dt.date) -> dict[str, Any]:
        """The record kept beside the pack, from which the answers can be fed back."""
        drafted = self.drafted
        return {
            "version": 1,
            "retrieved_at": retrieved.isoformat(),
            "provider": drafted.provider,
            "model": drafted.model,
            "tokens_in": drafted.tokens_in,
            "tokens_out": drafted.tokens_out,
            "stopped": drafted.stopped,
            "parts_not_asked": drafted.unasked,
            "drafted": self.claims,
            "accepted": len(self.accepted),
            "rejected": dict(self.rejected),
            "answers_refused": self.refused,
            "answers_failed": self.failed,
            "guides": [
                {
                    "ref": one.guide.ref,
                    "url": one.guide.url,
                    "sha256": one.guide.sha256,
                    "official": one.official,
                    "replies": list(one.replies),
                }
                for one in drafted.pieces
            ],
            "claims": [
                {"legacy": legacy, "outcome": outcome, "detail": detail}
                for legacy, outcome, detail in self.rows
            ],
        }


@dataclass(frozen=True, slots=True)
class View:
    """What the API diff and the pack so far hold, for a claim to be held against."""

    module: str
    olds: Mapping[str, Obj]
    news: Mapping[str, Obj]
    changes: Sequence[ApiChange]
    # The names the pack so far looks for, and where it renames or moves one.
    held: frozenset[str]
    made: Mapping[str, str]
    # The names it flags only because the library removed or deprecated them, saying no more.
    plain: frozenset[str]
    in_scope: Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class Drafter:
    """The model a guide is put to: the adapter, which provider it is, the model's name where there
    is one, and where the text goes, in words for the person."""

    model: base.TextModel
    provider: str
    name: str | None
    where: str


@dataclass(frozen=True, slots=True)
class Record:
    """What an earlier run kept: the answers by the hash of the text each was given, the day it
    ran, and where it stopped asking."""

    replies: Mapping[str, tuple[str | None, ...]]
    retrieved: dt.date
    stopped: Stopped | None = None
    unasked: int = 0


@dataclass(frozen=True, slots=True)
class Source:
    """Guides read, and how they are put to a model: by asking one, or from a record."""

    texts: tuple[guides.Guide, ...]
    official: tuple[bool, ...]
    drafter: Drafter | None = None
    kept: Record | None = None

    @property
    def retrieved(self) -> dt.date | None:
        """The day a record says the guides were read, which a pack made from it is dated."""
        return self.kept.retrieved if self.kept else None

    @property
    def digest(self) -> str:
        """A short name for these texts, which the id of the pack made from them ends with."""
        return hashlib.sha256("\n".join(one.sha256 for one in self.texts).encode()).hexdigest()[:12]

    def draft(
        self, names: Names, say: Callable[[str], None], clock: Callable[[], float] = time.monotonic
    ) -> Drafted:
        """Put every part of every guide to the model, in order, or take the answers kept. After
        `MAX_FAILURES` one after another, or `DEADLINE_S` by `clock`, the rest are not asked."""
        pieces: list[Piece] = []
        record = self.kept or Record({}, dt.date.min)
        tokens, failures, unasked, started = [0, 0], 0, 0, clock()
        stopped: Stopped | None = None
        for one, official in zip(self.texts, self.official, strict=True):
            if (drafter := self.drafter) is None:
                replies = record.replies.get(one.sha256, ())
                if len(replies) != len(one.chunks):
                    raise guides.GuideError("unreadable", f"no answers were kept for {one.ref}")
                pieces.append(Piece(one, official, replies))
                continue
            asked: list[str | None] = []
            for number, chunk in enumerate(one.chunks, 1):
                if stopped is None:
                    stopped = (
                        "failures"
                        if failures >= MAX_FAILURES
                        else "deadline"
                        if clock() - started > DEADLINE_S
                        else None
                    )
                    if stopped is not None:
                        say(
                            f"{one.ref}: the rest is not put to the model, after {_AFTER[stopped]}."
                        )
                if stopped is not None:
                    unasked += 1
                    asked.append(None)
                    continue
                question = drafting.question(
                    distribution=names.distribution, old=names.old, new=names.new,
                    module=names.module, ref=one.ref, text=chunk,
                )  # fmt: skip
                try:
                    done = drafter.model.complete(drafting.SYSTEM_PROMPT, question)
                except base.ProviderError as error:
                    say(f"{one.ref}, part {number} of {len(one.chunks)}: {error.failure}")
                    failures += 1
                    asked.append(None)
                else:
                    failures = 0
                    asked.append(done.text)
                    tokens[0] += done.tokens_in
                    tokens[1] += done.tokens_out
            pieces.append(Piece(one, official, tuple(asked)))
        if self.drafter is None:
            return Drafted(
                tuple(pieces), "replay", None, stopped=record.stopped, unasked=record.unasked
            )
        return Drafted(
            tuple(pieces), self.drafter.provider, self.drafter.name, tokens[0], tokens[1],
            stopped=stopped, unasked=unasked,
        )  # fmt: skip


def replies_kept(path: Path) -> Record:
    """The record an earlier run left beside its pack, or a `GuideError`: a record is JSON of a
    known shape and a size, read from a regular file, and nothing else is taken for one."""
    problem = guides.GuideError("unreadable", f"{path.name} is not a record of answers")
    raw = guides.file_bytes(path, RECORD_BYTES)
    try:
        document = json.loads(raw)
        found = {}
        for one in document["guides"]:
            replies = one["replies"]
            if not isinstance(one["sha256"], str) or not isinstance(replies, list):
                raise problem
            if not all(isinstance(r, str) or r is None for r in replies):
                raise problem
            found[one["sha256"]] = tuple(replies)
        stopped, unasked = document["stopped"], document["parts_not_asked"]
        if stopped not in (None, "failures", "deadline") or not isinstance(unasked, int):
            raise problem
        return Record(found, dt.date.fromisoformat(document["retrieved_at"]), stopped, unasked)
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise problem from error


def links(fetcher: Fetcher, distribution: str, version: str) -> Mapping[str, str]:
    """The addresses a project lists for itself, none where the index cannot say."""
    try:
        found = index.metadata(fetcher, distribution, version)
    except NetworkError:
        return {}
    return found.project_urls if found is not None else {}


def official(url: str | None, project: Mapping[str, str]) -> bool:
    """Whether a guide is the vendor's own: its address is on the host and port of one the project
    lists for itself, below that address's path, written with no `..`, `.`, backslash or percent
    escape that could lead out of it. A file has no address."""
    here = None if url is None else _address(url)
    if here is None or here[0] != "https" or "%" in here[3] or "\\" in here[3]:
        return False
    if {".", ".."} & set(here[3].split("/")):
        return False
    for link in project.values():
        there = _address(link)
        if there is not None and here[:3] == there[:3]:
            top = there[3].rstrip("/")
            if here[3] == top or here[3].startswith(top + "/"):
                return True
    return False


def _address(url: str) -> tuple[str, str | None, int, str] | None:
    """The scheme, host, port and path of an address; `None` where the port is no port."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return None
    return parts.scheme, parts.hostname, port or 443, parts.path


def accept(drafted: Drafted, view: View) -> Outcome:
    """Hold every claim to the checks, in the order the model gave them."""
    kept: list[Accepted] = []
    rejected: Counter[str] = Counter()
    rows: list[tuple[str, str, str]] = []
    refused = failed = 0
    used: dict[str, list[tuple[int, int]]] = {}
    for piece in drafted.pieces:
        for reply in piece.replies:
            if reply is None:
                failed += 1
                continue
            try:
                found, malformed = drafting.read(reply)
            except drafting.ReplyRefusedError:
                refused += 1
                continue
            rejected["malformed"] += malformed
            for claim in found:
                verdict = _vet(claim, piece, view, kept, used)
                if isinstance(verdict, Accepted):
                    kept.append(verdict)
                    rows.append((claim.legacy, "rewrite" if verdict.automatic else "report", ""))
                else:
                    rejected[verdict[0]] += 1
                    rows.append((claim.legacy, *verdict))
    counts = {name: rejected[name] for name in REASONS if rejected[name]}
    return Outcome(drafted, tuple(kept), counts, refused, failed, tuple(rows))


def reject_all(outcome: Outcome, why: str) -> Outcome:
    """The same claims, none kept: the pack made with them failed its own checks."""
    counts = {**outcome.rejected, "pack_failed": len(outcome.accepted)}
    rows = tuple(
        (legacy, "pack_failed", why) if kind in ("rewrite", "report") else (legacy, kind, detail)
        for legacy, kind, detail in outcome.rows
    )
    return Outcome(outcome.drafted, (), counts, outcome.refused, outcome.failed, rows)


def _vet(
    claim: drafting.Claim,
    piece: Piece,
    view: View,
    kept: Sequence[Accepted],
    used: dict[str, list[tuple[int, int]]],
) -> Accepted | Refused:
    quote = guides.flat(claim.quote)
    if quote not in piece.guide.flat:
        return "quote_missing", "the quote is not in the guide"
    rewrite = claim.kind == "rewrite_pattern"
    if (
        (claim.before is not None, claim.after is not None) != (rewrite, rewrite)
        or (claim.kind != "flag" and claim.new is None)
        or (bool(claim.keywords) and claim.kind != "flag")
    ):
        return "malformed", f"the fields do not fit a {claim.kind}"
    legacy, new = _below(view.module, claim.legacy), _below(view.module, claim.new)
    if not legacy or legacy not in view.olds:
        return "legacy_unknown", f"{claim.legacy} is not in the old release"
    if claim.new is not None and (new is None or new not in view.news):
        return "new_unknown", f"{claim.new} is not in the new release"
    if len(quote) < MIN_QUOTE or not _names(quote, legacy) or (new and not _names(quote, new)):
        return "quote_weak", "the quote is short, or does not name both names"
    # Quotes that overlap in the guide are one quote, however each is cut.
    at = piece.guide.flat.find(quote)
    span, others = (at, at + len(quote)), used.setdefault(piece.guide.sha256, [])
    if sum(a < span[1] and span[0] < b for a, b in others) >= MAX_PER_QUOTE:
        return "quote_reused", f"the quote carries more than {MAX_PER_QUOTE} claims"
    others.append(span)
    keywords = tuple(sorted(set(claim.keywords)))
    params = view.olds[legacy].params
    if keywords and (params is None or not _keywords_ok(keywords, params)):
        return "keyword_unknown", "a keyword is not one the old name takes"
    if not view.in_scope(legacy):
        return "out_of_scope", "the code does not reach it"
    guide = piece.guide
    cite = Cite(_citation(guide, claim.quote), guide.ref, guide.url, guide.sha256, piece.official)
    found = (
        _pattern(claim, legacy, view, view.held.union(one.path for one in kept))
        if rewrite
        else None
    )
    if isinstance(found, tuple):
        return found
    if (clash := _clash(legacy, new, view, kept)) is not None:
        return clash
    if legacy in view.plain:
        around = guides.lines_around(guide, quote)
        got = _promote(claim, cite, legacy, new, view, found, (quote, around))
        if got is None:
            return "in_the_diff", "the diff reports it already, and the claim supports no rewrite"
    elif any(_overlap(legacy, other) for other in view.held):
        return "in_the_diff", "the diff already reports this name or one around it"
    else:
        shape = CallShape(keywords=keywords) if keywords else None
        got = Accepted(claim, cite, "flag", legacy, new, shape=shape)
    return _schema(got, view.module) or got


def _schema(got: Accepted, module: str) -> Refused | None:
    """The parameters of the change a claim becomes, held to the pack's schema."""
    name, leaf = f"{module}.{got.path}", _leaf(got.target or "")
    try:
        match got.route:
            case "flag":
                message, suggestion = got.words()
                calls = {name: got.shape} if got.shape else {}
                FlagOnlyParams(message=message, suggestion=suggestion, symbols=(name,), calls=calls)
            case "rename":
                RenameSymbolParams(
                    renamed={name: leaf}, calls="allowed" if got.calls else "refused"
                )
            case "member":
                takes = {name: got.takes} if got.takes is not None else {}
                RenameMemberParams(members={name: leaf}, takes=takes)
    except ValidationError as error:
        return "params_refused", error.errors()[0]["msg"].removeprefix("Value error, ")
    return None


def _keywords_ok(keywords: Sequence[str], params: Sequence[Param]) -> bool:
    """Whether every keyword is a parameter, or the signature takes any keyword."""
    return set(keywords) <= {one.name for one in params} or any(
        one.kind == "variadic keyword" for one in params
    )


def _overlap(path: str, other: str) -> bool:
    """Whether two names are one, or one is under the other: a pack may hold a surface once."""
    return path == other or path.startswith(f"{other}.") or other.startswith(f"{path}.")


def _below(module: str, name: str | None) -> str | None:
    """A dotted name as the path below the module, `None` if it is not below it."""
    return name.removeprefix(f"{module}.") if name and name.startswith(f"{module}.") else None


def _names(quote: str, path: str | None) -> bool:
    return path is not None and bool(re.search(rf"(?<!\w){re.escape(_leaf(path))}(?!\w)", quote))


def _leaf(path: str) -> str:
    return path.rpartition(".")[2]


def _parent(path: str) -> str:
    return path.rpartition(".")[0]


def _cut(text: str) -> str:
    return text if len(text) <= DISPLAY_TEXT_LIMIT else text[: DISPLAY_TEXT_LIMIT - 1] + "…"


def _citation(source: guides.Guide, quote: str) -> str:
    return _cut(f"{source.url or 'the guide ' + source.ref}: {printable(guides.flat(quote))}")


def _above(path: str, objects: Mapping[str, Obj]) -> str:
    """What holds a name: `module` (the package itself at the top) or `class`."""
    parent = _parent(path)
    return objects[parent].kind if parent in objects else "module" if not parent else ""


def _clash(path: str, target: str | None, view: View, kept: Sequence[Accepted]) -> Refused | None:
    """What the diff or an earlier claim already says of a name."""
    paired = (one.new_path for one in view.changes if one.path == path and one.type in _PAIRED)
    there = view.made.get(path) or next(paired, None)
    if there is not None:
        if target is None or there == target:
            return "in_the_diff", "the diff already pairs this name with another"
        return "contradicts_diff", f"the diff has it become {there}"
    if any(_overlap(path, one.path) for one in kept):
        return "repeated", "an earlier claim is about this name or one around it"
    if len(kept) >= MAX_KEPT:
        return "too_many", f"a pack keeps at most {MAX_KEPT} claims"
    return None


_PAIRED: Final = ("renamed", "moved")
_RENAMED: Final = ("function", "class")


@dataclass(frozen=True, slots=True)
class _Pattern:
    where: Mapping[str, str]
    imports: tuple[str, ...]
    fits: bool


def _pattern(
    claim: drafting.Claim, legacy: str, view: View, taken: frozenset[str]
) -> _Pattern | Refused:
    """A claim's templates, held to the rules a pack's are, and to the new release. `taken` are the
    names the pack looks for, which `after` may not write: a rewritten file would be found again."""
    assert claim.before is not None  # noqa: S101 - `_vet` checked both
    assert claim.after is not None  # noqa: S101
    try:
        before, after = pattern.parse(claim.before), pattern.parse(claim.after)
        held = pattern.receiver(before)
        where = {held: _parent(claim.legacy)} if held else {}
        found = pattern.anchor(before, where)
    except pattern.TemplateError as error:
        return "pattern_refused", f"the template {error}"
    if found.symbol != claim.legacy or (held and _above(legacy, view.olds) != "class"):
        return "pattern_refused", "before is not a call of the legacy name"
    spelled = pattern.new_names(after)
    beside = {name for name in spelled if held is None and name.startswith(f"{view.module}.")}
    imports = tuple(sorted({_parent(name) for name in spelled - beside if "." in name}))
    try:
        RewritePatternParams(before=claim.before, after=claim.after, where=where, imports=imports)
    except ValidationError as error:
        return "pattern_refused", error.errors()[0]["msg"].removeprefix("Value error, ")
    lands = {_below(view.module, name) for name in spelled}
    if held:
        lands |= {f"{_parent(legacy)}.{attribute}" for attribute in after.attributes}
    if any(rel and any(_overlap(rel, other) for other in taken) for rel in lands):
        return "pattern_refused", "after spells a name the pack looks for"
    absent = [name for name in sorted(beside) if _below(view.module, name) not in view.news]
    calls = cast("list[cst.Call]", m.findall(after.tree, m.Call()))
    seen = [_fit(call, where, view, view.olds[legacy].labels) for call in calls]
    if absent or "missing" in seen:
        return (
            "new_unknown",
            f"{absent[0] if absent else 'a member in after'} is not in the new release",
        )
    return _Pattern(where, imports, bool(seen) and all(one == "fits" for one in seen))


def _fit(call: cst.Call, where: Mapping[str, str], view: View, labels: tuple[str, ...]) -> Fit:
    """Whether the new release takes this call as written: what it names, with the marks the old
    name had (`async` and the like), and its arguments."""
    path = _callee(call.func, where, view.module)
    if path is None:
        return "unknown"
    found = view.news.get(path)
    if found is None:
        owner = view.news.get(_parent(path))
        return "unknown" if owner is not None and _leaf(path) in owner.inherited else "missing"
    if found.params is None:
        return "unknown"
    marked = found.kind != "function" or found.labels == labels
    return "fits" if marked and _fits(call, found.params) else "misfits"


def _callee(func: cst.BaseExpression, where: Mapping[str, str], module: str) -> str | None:
    """The path below the module of what a call names: a name, a method of a class it builds or a
    method of the class a receiver is."""
    if isinstance(func, cst.Attribute):
        named = pattern.metavariable(func.value)
        if named is not None:
            held = _below(module, where.get(named))
        else:
            held = (
                _below(module, pattern.dotted(func.value.func))
                if isinstance(func.value, cst.Call)
                else None
            )
        if held:
            return f"{held}.{func.attr.value}"
    return _below(module, pattern.dotted(func))


def _fits(call: cst.Call, params: tuple[Param, ...]) -> bool:
    """Whether a call passes what a signature takes and leaves out nothing it requires."""
    positional = [one for one in call.args if one.keyword is None]
    named = [one.keyword.value for one in call.args if one.keyword is not None]
    placed = [one for one in params if one.kind in _PLACED]
    keyed = {one.name for one in params if one.kind in _KEYED}
    kinds = {one.kind for one in params}
    if len(positional) > len(placed) and "variadic positional" not in kinds:
        return False
    if not set(named) <= keyed and "variadic keyword" not in kinds:
        return False
    given = {one.name for one in placed[: len(positional)]} | set(named)
    return len(given) == min(len(positional), len(placed)) + len(named) and all(
        one.name in given for one in params if one.required
    )


# How a quote may say that one name is replaced by another, from <a> to <b>: in a table row, with an
# arrow, with a verb, or as "use <b> instead of <a>". A name is written as `_spelled` allows, with
# only quotes, ticks, an @ and call brackets beside it.
_VERBS: Final = (
    r"(?i:(?:(?:is|was|has been|are|were|have been)\s+)?(?:now\s+)?renamed\s+(?:to|as)"
    r"|(?:is|are)\s+now(?:\s+(?:called|named|spelled|written\s+as))?"
    r"|(?:is|was|has been|are|were|have been)\s+(?:now\s+)?(?:replaced|superseded)\s+(?:by|with)"
    r"|becomes|has\s+become|have\s+become)"
)
_SAYS: Final = (
    r"<a>\s*\|\s*<b>",
    r"<a>\s*(?:->|-->|=>|\u2192|\u21d2)\s*<b>",
    r"<a>\s+" + _VERBS + r"\s+<b>",
    r"(?i:use)\s+<b>\s+(?i:instead\s+of|in\s+place\s+of)\s+<a>",
)
# What takes a replacement back or limits it, in the lines of the guide the quote touches.
_DENIAL: Final = re.compile(
    r"\b(?:not|no|never|without|different|differs?|differently|unlike|but|however|rather|except"
    r"|unless|only|although|though|whereas|nor|neither|cannot)\b|n['\u2019]t\b",
    re.IGNORECASE,
)


_MARKS: Final = "`'\"\u2018\u2019\u201c\u201d"


def _spelled(path: str, module: str) -> str:
    """A pattern for a name as a quote may write it: whole, from the module, from the class or by
    its last word, not as the end of a longer name, with the brackets of a call."""
    parts = f"{module}.{path}".split(".")
    names = "|".join(re.escape(".".join(parts[at:])) for at in range(len(parts)))
    return (
        rf"(?<![\w.])[{_MARKS}@]*(?:{names})(?!\w)(?:\([^()]*\))?[{_MARKS}]*"
        r"(?:\s+(?:function|class|method|decorator|attribute|helper))?"
    )


def _replaced(module: str, legacy: str, new: str, quote: str, around: str) -> bool:
    """Whether the quote says `new` replaces `legacy`, and its lines do not take it back."""
    old, now = _spelled(legacy, module), _spelled(new, module)
    says = (shape.replace("<a>", old).replace("<b>", now) for shape in _SAYS)
    return any(re.search(shape, quote) for shape in says) and not _DENIAL.search(around)


def _writes(claim: drafting.Claim, new: str) -> bool:
    """Whether `after` spells the new name the claim names."""
    return re.search(rf"(?<!\w){re.escape(_leaf(new))}(?!\w)", claim.after or "") is not None


def _promote(
    claim: drafting.Claim,
    cite: Cite,
    legacy: str,
    new: str | None,
    view: View,
    found: _Pattern | None,
    said: tuple[str, str],
) -> Accepted | None:
    """The rewrite a claim asks for, if the quote, the diff and the two releases agree: the quote
    says in one connector that `legacy` is replaced by `new` and nothing in its lines takes that
    back (`said` is the quote and the lines of the guide it touches), the old name is going, and
    the new one is there, not itself deprecated, written as the old one was and able to take its
    place. `None` where it can only report."""
    old, target = view.olds[legacy], view.news.get(new or "")
    if new is None or target is None or target.deprecated is not None:
        return None
    if not _replaced(view.module, legacy, new, *said):
        return None
    place = _above(legacy, view.olds)
    renamed = _parent(new) == _parent(legacy) and _leaf(new) != _leaf(legacy)
    alike = old.kind == target.kind and old.labels == target.labels and renamed
    if claim.kind == "rename_symbol" and place == "module" and alike and old.kind in _RENAMED:
        calls = old.kind == "function" and accepts(old, target)
        return Accepted(claim, cite, "rename", legacy, new, calls=calls)
    if claim.kind == "rename_member" and place == "class" and alike and old.kind == "function":
        fitted = accepts(old, target)
        keywords = None if fitted else takes(old, target)
        if fitted or keywords is not None:
            return Accepted(claim, cite, "member", legacy, new, takes=keywords)
    if claim.kind == "rewrite_pattern" and found is not None and found.fits and _writes(claim, new):
        return Accepted(
            claim, cite, "pattern", legacy, new, where=found.where, imports=found.imports
        )
    return None


__all__ = [
    "MAX_KEPT",
    "MAX_PER_QUOTE",
    "MIN_QUOTE",
    "REASONS",
    "RECORD",
    "STOPS",
    "Accepted",
    "Cite",
    "Drafted",
    "Drafter",
    "Names",
    "Outcome",
    "Piece",
    "Source",
    "View",
    "accept",
    "links",
    "official",
    "reject_all",
    "replies_kept",
]
