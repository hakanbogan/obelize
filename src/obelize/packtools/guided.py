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
        return "; ".join(parts) + "."

    def document(self) -> dict[str, Any]:
        """The record kept beside the pack, from which the answers can be fed back."""
        drafted = self.drafted
        return {
            "version": 1,
            "provider": drafted.provider,
            "model": drafted.model,
            "tokens_in": drafted.tokens_in,
            "tokens_out": drafted.tokens_out,
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
class Source:
    """Guides read, and how they are put to a model: by asking one, or from answers kept."""

    texts: tuple[guides.Guide, ...]
    official: tuple[bool, ...]
    drafter: Drafter | None = None
    replies: Mapping[str, tuple[str | None, ...]] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        """A short name for these texts, which the id of the pack made from them ends with."""
        return hashlib.sha256("\n".join(one.sha256 for one in self.texts).encode()).hexdigest()[:8]

    def draft(self, names: Names, say: Callable[[str], None]) -> Drafted:
        """Put every chunk of every guide to the model, in order, or take the answers kept."""
        pieces: list[Piece] = []
        spent = [0, 0]
        for one, official in zip(self.texts, self.official, strict=True):
            if self.drafter is None:
                kept = self.replies.get(one.sha256, ())
                if len(kept) != len(one.chunks):
                    raise guides.GuideError("unreadable", f"no answers were kept for {one.ref}")
                pieces.append(Piece(one, official, kept))
            else:
                asked = self._ask(self.drafter.model, one, names, say, spent)
                pieces.append(Piece(one, official, asked))
        drafter = self.drafter
        if drafter is None:
            return Drafted(tuple(pieces), "replay", None, *spent)
        return Drafted(tuple(pieces), drafter.provider, drafter.name, *spent)

    @staticmethod
    def _ask(
        model: base.TextModel,
        one: guides.Guide,
        names: Names,
        say: Callable[[str], None],
        spent: list[int],
    ) -> tuple[str | None, ...]:
        replies: list[str | None] = []
        for number, chunk in enumerate(one.chunks, 1):
            asked = drafting.question(
                distribution=names.distribution, old=names.old, new=names.new,
                module=names.module, ref=one.ref, text=chunk,
            )  # fmt: skip
            try:
                done = model.complete(drafting.SYSTEM_PROMPT, asked)
            except base.ProviderError as error:
                say(f"{one.ref}, part {number} of {len(one.chunks)}: {error.failure}")
                replies.append(None)
            else:
                replies.append(done.text)
                spent[0] += done.tokens_in
                spent[1] += done.tokens_out
        return tuple(replies)


def replies_kept(path: Path) -> dict[str, tuple[str | None, ...]]:
    """The answers a record keeps, by the hash of the guide each was given."""
    problem = guides.GuideError("unreadable", f"{path.name} is not a record of answers")
    try:
        with path.open("rb") as handle:
            document = json.loads(handle.read(RECORD_BYTES))
        found = {one["sha256"]: tuple(one["replies"]) for one in document["guides"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise problem from error
    if not all(isinstance(r, str) or r is None for replies in found.values() for r in replies):
        raise problem
    return found


def links(fetcher: Fetcher, distribution: str, version: str) -> Mapping[str, str]:
    """The addresses a project lists for itself, none where the index cannot say."""
    try:
        found = index.metadata(fetcher, distribution, version)
    except NetworkError:
        return {}
    return found.project_urls if found is not None else {}


def official(url: str | None, project: Mapping[str, str]) -> bool:
    """Whether a guide is the vendor's own: its address is on the host of one the project lists for
    itself, below that address's path. A file has no address."""
    if url is None:
        return False
    here = urlsplit(url)
    for link in project.values():
        there = urlsplit(link)
        top = there.path.rstrip("/")
        if (
            there.scheme == here.scheme == "https"
            and there.hostname == here.hostname
            and (here.path == top or here.path.startswith(top + "/"))
        ):
            return True
    return False


def accept(drafted: Drafted, view: View) -> Outcome:
    """Hold every claim to the checks, in the order the model gave them."""
    kept: list[Accepted] = []
    rejected: Counter[str] = Counter()
    rows: list[tuple[str, str, str]] = []
    refused = failed = 0
    used: Counter[str] = Counter()
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
    rows = (*outcome.rows, ("", "pack_failed", why))
    return Outcome(outcome.drafted, (), counts, outcome.refused, outcome.failed, rows)


def _vet(
    claim: drafting.Claim, piece: Piece, view: View, kept: Sequence[Accepted], used: Counter[str]
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
    used[quote] += 1
    if used[quote] > MAX_PER_QUOTE:
        return "quote_reused", f"the quote carries more than {MAX_PER_QUOTE} claims"
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
        got = _promote(claim, cite, legacy, new, view, found)
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
    seen = [_fit(call, where, view) for call in calls]
    if absent or "missing" in seen:
        return (
            "new_unknown",
            f"{absent[0] if absent else 'a member in after'} is not in the new release",
        )
    return _Pattern(where, imports, "misfits" not in seen and "fits" in seen)


def _fit(call: cst.Call, where: Mapping[str, str], view: View) -> Fit:
    """Whether the new release takes this call as written: what it names, and its arguments."""
    path = _callee(call.func, where, view.module)
    if path is None:
        return "unknown"
    found = view.news.get(path)
    if found is None:
        owner = view.news.get(_parent(path))
        return "unknown" if owner is not None and _leaf(path) in owner.inherited else "missing"
    if found.params is None:
        return "unknown"
    return "fits" if _fits(call, found.params) else "misfits"


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


def _promote(
    claim: drafting.Claim,
    cite: Cite,
    legacy: str,
    new: str | None,
    view: View,
    found: _Pattern | None,
) -> Accepted | None:
    """The rewrite a claim asks for, if the diff supports it: the old name is going, the new one
    is there, not itself deprecated, and takes its place. `None` where it can only report."""
    old, target = view.olds[legacy], view.news.get(new or "")
    if new is None or target is None or target.deprecated is not None:
        return None
    place = _above(legacy, view.olds)
    renamed = _parent(new) == _parent(legacy) and _leaf(new) != _leaf(legacy)
    alike = old.kind == target.kind and renamed
    if claim.kind == "rename_symbol" and place == "module" and alike and old.kind in _RENAMED:
        calls = old.kind == "function" and accepts(old, target)
        return Accepted(claim, cite, "rename", legacy, new, calls=calls)
    if claim.kind == "rename_member" and place == "class" and alike and old.kind == "function":
        fitted = accepts(old, target)
        keywords = None if fitted else takes(old, target)
        if fitted or keywords is not None:
            return Accepted(claim, cite, "member", legacy, new, takes=keywords)
    if claim.kind == "rewrite_pattern" and found is not None and found.fits:
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
