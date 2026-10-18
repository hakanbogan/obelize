"""What changed in a library's public API between two releases, from two `Surface`s.

Only what the two surfaces show is reported. A name that left is paired with another only in two
cases: it kept its name and signature and has a body (a stub says nothing of the function, and a
name with more than one candidate cannot be told from them), or the library's own deprecation
message says to use one name that exists beside it. Everything else that left the API is reported as
removed, for a person or a model to read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from obelize.apidiff.surface import Obj, Param, Surface

ChangeType = Literal[
    "moved",
    "renamed",
    "removed",
    "unseen",
    "kind_changed",
    "bases_changed",
    "param_renamed",
    "param_removed",
    "param_required_added",
    "param_kind_changed",
    "default_changed",
    "deprecated",
]

_VARIADIC: Final = ("variadic positional", "variadic keyword")
_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A name that stands for "not given": private, or one that says so (`_Unset`, `PydanticUndefined`).
_SENTINEL: Final = re.compile(
    r"(?:\w+\.)*(?:_\w+|\w*(?:undefined|unset|missing|sentinel|notset|notgiven)\w*)", re.I
)
# A message that tells the reader what replaces a name, as opposed to one that only warns.
_REPLACEMENT: Final = re.compile(r"\b(use|replaced|renamed|instead|favou?r|supersed\w*)\b", re.I)


# Kinds of name worth offering as what a removed one became.
_NAMED: Final = frozenset({"class", "function", "module", "alias"})
# How alike two spellings must be, when no word is shared, for one to be offered for the other.
_SPELT: Final = 0.6
_WORD: Final = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
# How many names are offered, and how many names below a module are looked at.
SUCCESSORS: Final = 6
_MEMBERS: Final = 30


@dataclass(frozen=True, slots=True)
class ApiChange:
    """One change. `path` is the name in the old release, below the module; `new_path` where it is
    now; `param` the parameter concerned; `message` the library's own words, if it said any;
    `same_signature` that a name paired with another takes the arguments it took."""

    type: ChangeType
    path: str
    new_path: str | None = None
    param: str | None = None
    new_param: str | None = None
    message: str | None = None
    detail: str = ""
    same_signature: bool = False


def diff(old: Surface, new: Surface, *, before: Sequence[Surface] = ()) -> tuple[ApiChange, ...]:
    """The changes from `old` to `new`. `before` are the releases between them, newest first: a
    library warns of what it removes, in the last release that still has the name."""
    olds, news = old.relative(), new.relative()
    warned = [one.relative() for one in before]
    appeared = {path: one for path, one in news.items() if path not in olds}
    # What `_departed` looks a name up by, so a large library is not walked once per removed name.
    leaves: dict[str, list[tuple[str, Obj]]] = {}
    for path, one in appeared.items():
        leaves.setdefault(path.rpartition(".")[2], []).append((path, one))
    members: dict[str, list[tuple[str, Obj]]] = {}
    for path, one in news.items():
        members.setdefault(_parent(path), []).append((path, one))
    # A name the old release already re-exported from the place that is now gone is the same object.
    reexported = {one.target: path for path, one in olds.items() if one.target and path in news}
    found: list[ApiChange] = []
    gone: set[str] = set()
    for path, one in olds.items():
        if _beneath(path, gone) or one.kind == "module":
            continue
        message = _said(path, one, warned)
        if path not in news:
            gone.add(path)
            if _inherits(path, news):
                continue
            if _made_lazily(path, news):
                found.append(ApiChange("unseen", path))
                continue
            found.append(
                _departed(
                    path,
                    one,
                    news,
                    (leaves, members),
                    message,
                    reexported.get(f"{old.module}.{path}"),
                )
            )
        else:
            found.extend(_changed(path, one, news[path], message))
    return tuple(found)


def _said(path: str, one: Obj, warned: Sequence[Mapping[str, Obj]]) -> str | None:
    """What the library said of a name: in the newest release between that still has it, else in
    the old one."""
    for release in warned:
        if path in release:
            return release[path].deprecated or one.deprecated
    return one.deprecated


def _inherits(path: str, news: Mapping[str, Obj]) -> bool:
    """Whether a member that left its class is still there, in a class its new one derives from."""
    parent = news.get(_parent(path))
    return parent is not None and path.rpartition(".")[2] in parent.inherited


def _parent(path: str) -> str:
    return path.rpartition(".")[0]


def _in_class(objects: Mapping[str, Obj], path: str) -> bool:
    above = objects.get(_parent(path))
    return above is not None and above.kind == "class"


def _bases(one: Obj) -> tuple[str, ...]:
    """What a class derives from; `object` is what every class derives from, written or not."""
    return tuple(base for base in one.bases if base != "object")


def _made_lazily(path: str, news: Mapping[str, Obj]) -> bool:
    """Whether the nearest module of the newer release above a name makes names when asked."""
    return next((news[above].lazy for above in _ancestors(path) if above in news), False)


def _ancestors(path: str) -> list[str]:
    """The modules and classes above a name, nearest first, and the module itself (`""`) last."""
    parts = path.split(".")[:-1]
    return [".".join(parts[:end]) for end in range(len(parts), -1, -1)]


def _beneath(path: str, parents: set[str]) -> bool:
    """Whether a name above `path` is in `parents`."""
    while path := _parent(path):
        if path in parents:
            return True
    return False


def _departed(
    path: str,
    one: Obj,
    news: dict[str, Obj],
    indexed: tuple[dict[str, list[tuple[str, Obj]]], dict[str, list[tuple[str, Obj]]]],
    message: str | None,
    reexported: str | None,
) -> ApiChange:
    leaves, members = indexed
    name = path.rpartition(".")[2]
    same = [(new_path, new) for new_path, new in leaves.get(name, ()) if new.kind == one.kind]
    if reexported is not None and reexported in news:
        same.append((reexported, news[reexported]))
    if len(same) > 1:
        return ApiChange("removed", path, message=message, detail=f"{len(same)} candidates")
    if same and not one.trivial and _alike(one, same[0][1]):
        return ApiChange("moved", path, new_path=same[0][0], message=message, same_signature=True)
    named = _named(path, one, members, message)
    if named is not None:
        return ApiChange(
            "renamed",
            path,
            new_path=named[0],
            message=message,
            same_signature=_alike(one, named[1]),
        )
    return ApiChange("removed", path, message=message)


def _named(
    path: str, one: Obj, members: dict[str, list[tuple[str, Obj]]], message: str | None
) -> tuple[str, Obj] | None:
    """The one name beside `path`, of its kind, that the library's message says to use."""
    if message is None or not _REPLACEMENT.search(message):
        return None
    words = set(_IDENTIFIER.findall(message))
    found = [
        (new_path, new)
        for new_path, new in members.get(_parent(path), ())
        if new_path != path and new_path.rpartition(".")[2] in words and new.kind == one.kind
    ]
    return found[0] if len(found) == 1 else None


def _alike(old: Obj, new: Obj) -> bool:
    return old.kind != "attribute" and old.params == new.params and _bases(old) == _bases(new)


def _changed(path: str, old: Obj, new: Obj, message: str | None) -> Iterator[ApiChange]:
    if "name" in (old.kind, new.kind):
        # A name declared and not read has no shape to compare, but may say it is going.
        if new.deprecated is not None and old.deprecated is None:
            yield ApiChange("deprecated", path, message=new.deprecated)
        return
    if old.kind != new.kind:
        yield ApiChange("kind_changed", path, detail=f"{old.kind} -> {new.kind}")
        return
    if not set(_bases(old)) <= set(_bases(new)):
        yield ApiChange("bases_changed", path, detail=", ".join(_bases(old)))
    if old.params is not None and new.params is not None:
        yield from _signature(path, old.params, new.params)
    if new.deprecated is not None and old.deprecated is None:
        yield ApiChange("deprecated", path, message=new.deprecated)
    elif message is not None and new.deprecated is None:
        yield ApiChange("deprecated", path, message=message)


def _signature(path: str, old: tuple[Param, ...], new: tuple[Param, ...]) -> Iterator[ApiChange]:
    by_name = {one.name: one for one in new}
    kept = {one.name for one in old}
    open_ended = any(one.kind == "variadic keyword" for one in new)
    added = [one for one in new if one.name not in kept and one.kind not in _VARIADIC]
    for index, one in enumerate(old):
        if one.kind in _VARIADIC:
            continue
        match = by_name.get(one.name)
        if match is None:
            twin = next((other for other in added if _renamed(one, other, index, new)), None)
            if twin is not None:
                added.remove(twin)
                yield ApiChange("param_renamed", path, param=one.name, new_param=twin.name)
            elif not open_ended:
                yield ApiChange("param_removed", path, param=one.name)
            continue
        if match.kind != one.kind:
            detail = f"{one.kind} -> {match.kind}"
            yield ApiChange("param_kind_changed", path, param=one.name, detail=detail)
        # A default added to a parameter that had none breaks nothing. Nor does one that became
        # "not given": the library decides the value elsewhere, which a name cannot show.
        if (
            match.default != one.default
            and one.default is not None
            and not (match.default and _SENTINEL.fullmatch(match.default))
        ):
            detail = f"{one.default} -> {match.default or 'required'}"
            yield ApiChange("default_changed", path, param=one.name, detail=detail)
    # What a caller passed through `*args` still arrives, so only a keyword-only name breaks it.
    spread = any(one.kind == "variadic positional" for one in old)
    for one in added:
        if one.required and not (spread and one.kind != "keyword-only"):
            yield ApiChange("param_required_added", path, param=one.name)


def _renamed(old: Param, new: Param, index: int, params: tuple[Param, ...]) -> bool:
    """A parameter that is another's old place, kind and default under a new name."""
    return (
        index < len(params)
        and params[index].name == new.name
        and new.kind == old.kind
        and new.default == old.default
    )


class Successors:
    """What removed names may have become, for any number of them: both releases are read once.

    The names only `new` has that the removed `path` may have become: the path and kind of each,
    closest first. Words in the names and place decide, so it is a guess to put in front of a
    reader, never a name to rewrite to. A module stands for the names in it; a method is offered
    other methods, and any other name the names that are not.
    """

    def __init__(self, old: Surface, new: Surface) -> None:
        self._olds, self._news = old.relative(), new.relative()
        # The new names, by whether each is a member of a class: (path, lower-case leaf, words).
        self._appeared: dict[bool, list[tuple[str, str, frozenset[str]]]] = {False: [], True: []}
        for one, found in self._news.items():
            if one not in self._olds and found.kind in _NAMED:
                leaf = one.rpartition(".")[2]
                self._appeared[_in_class(self._news, one)].append((one, leaf.lower(), _words(leaf)))

    def of(self, path: str) -> list[tuple[str, str]]:
        olds = self._olds
        below = olds.get(path) is not None and olds[path].kind == "module"
        gone = [
            one
            for one in olds
            if (one == path or (below and _parent(one) == path)) and olds[one].kind in _NAMED
        ][:_MEMBERS]
        member = _in_class(olds, path)
        best: dict[str, float] = {}
        for former in gone:
            name = former.rpartition(".")[2]
            words = _words(name)
            for found, leaf, theirs in self._appeared[member]:
                alike = len(words & theirs) / max(1, min(len(words), len(theirs)))
                if not alike:
                    matcher = SequenceMatcher(None, name.lower(), leaf)
                    if matcher.real_quick_ratio() >= _SPELT and matcher.quick_ratio() >= _SPELT:
                        alike = matcher.ratio() if matcher.ratio() >= _SPELT else 0.0
                # A method is offered the other methods of the class, whatever they are called.
                same = member and _parent(found) == _parent(former)
                if not alike and not same:
                    continue
                shared = sum(
                    1 for a, b in zip(found.split("."), former.split("."), strict=False) if a == b
                )
                best[found] = max(
                    best.get(found, 0.0), alike + shared / 10 + (0.5 if same else 0.0)
                )
        ranked = sorted(best, key=lambda one: (-best[one], one))[:SUCCESSORS]
        return [(one, self._news[one].kind) for one in ranked]


def successors(old: Surface, new: Surface, path: str) -> list[tuple[str, str]]:
    """What the removed `path` may have become (see `Successors`)."""
    return Successors(old, new).of(path)


def _words(name: str) -> frozenset[str]:
    """The words of a name: `FastMCP` is `fast` and `mcp`, `old_greet` is `old` and `greet`."""
    return frozenset(one.lower() for one in _WORD.findall(name))


__all__ = ["SUCCESSORS", "ApiChange", "ChangeType", "Successors", "diff", "successors"]
