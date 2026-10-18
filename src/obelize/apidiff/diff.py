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
# A message that tells the reader what replaces a name, as opposed to one that only warns.
_REPLACEMENT: Final = re.compile(r"\b(use|replaced|renamed|instead|favou?r|supersed\w*)\b", re.I)


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
    # A name the old release already re-exported from the place that is now gone is the same object.
    reexported = {one.target: path for path, one in olds.items() if one.target and path in news}
    lazy = {path for path, one in news.items() if one.lazy}
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
            if lazy.intersection(_ancestors(path)):
                found.append(ApiChange("unseen", path))
                continue
            found.append(
                _departed(
                    path, one, news, appeared, message, reexported.get(f"{old.module}.{path}")
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


def _bases(one: Obj) -> tuple[str, ...]:
    """What a class derives from; `object` is what every class derives from, written or not."""
    return tuple(base for base in one.bases if base != "object")


def _ancestors(path: str) -> list[str]:
    """The modules and classes above a name, nearest first, and the module itself (`""`) last."""
    parts = path.split(".")[:-1]
    return [".".join(parts[:end]) for end in range(len(parts), -1, -1)]


def _beneath(path: str, parents: set[str]) -> bool:
    return any(path.startswith(f"{parent}.") for parent in parents)


def _departed(
    path: str,
    one: Obj,
    news: dict[str, Obj],
    appeared: dict[str, Obj],
    message: str | None,
    reexported: str | None,
) -> ApiChange:
    name = path.rpartition(".")[2]
    same = [
        (new_path, new)
        for new_path, new in appeared.items()
        if new_path.rpartition(".")[2] == name and new.kind == one.kind
    ]
    if reexported is not None and reexported in news:
        same.append((reexported, news[reexported]))
    if len(same) > 1:
        return ApiChange("removed", path, message=message, detail=f"{len(same)} candidates")
    if same and not one.trivial and _alike(one, same[0][1]):
        return ApiChange("moved", path, new_path=same[0][0], message=message, same_signature=True)
    named = _named(path, one, news, message)
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
    path: str, one: Obj, news: dict[str, Obj], message: str | None
) -> tuple[str, Obj] | None:
    """The one name beside `path`, of its kind, that the library's message says to use."""
    if message is None or not _REPLACEMENT.search(message):
        return None
    parent, words = path.rpartition(".")[0], set(_IDENTIFIER.findall(message))
    found = [
        (new_path, new)
        for new_path, new in news.items()
        if new_path != path
        and new_path.rpartition(".")[0] == parent
        and new_path.rpartition(".")[2] in words
        and new.kind == one.kind
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
        # A default added to a parameter that had none breaks nothing.
        if match.default != one.default and one.default is not None:
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


__all__ = ["ApiChange", "ChangeType", "diff"]
