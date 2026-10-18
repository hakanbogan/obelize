"""What changed in a library's public API between two releases, from two `Surface`s.

Only what the two surfaces show is reported, and only a name that moved with its signature intact,
and that has a body, is paired with its new place: a stub says nothing of the function, and a name
with more than one candidate cannot be told from them. Everything else that left the API is
reported as removed, for a person or a model to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

    from obelize.apidiff.surface import Obj, Param, Surface

ChangeType = Literal[
    "moved",
    "removed",
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


@dataclass(frozen=True, slots=True)
class ApiChange:
    """One change. `path` is the name in the old release, below the module; `new_path` where it is
    now; `param` the parameter concerned; `message` the library's own words, if it said any."""

    type: ChangeType
    path: str
    new_path: str | None = None
    param: str | None = None
    new_param: str | None = None
    message: str | None = None
    detail: str = ""


def diff(old: Surface, new: Surface, *, before: Surface | None = None) -> tuple[ApiChange, ...]:
    """The changes from `old` to `new`. `before` is the newest release before `new` that still has
    the names, which is where a library warned of what `new` removed."""
    olds, news = old.relative(), new.relative()
    warned = before.relative() if before is not None else {}
    appeared = {path: one for path, one in news.items() if path not in olds}
    found: list[ApiChange] = []
    gone: set[str] = set()
    for path, one in olds.items():
        if _beneath(path, gone) or one.kind == "module":
            continue
        message = (warned.get(path) or one).deprecated
        if path not in news:
            gone.add(path)
            found.append(_departed(path, one, appeared, message))
        else:
            found.extend(_changed(path, one, news[path], message))
    return tuple(found)


def _beneath(path: str, parents: set[str]) -> bool:
    return any(path.startswith(f"{parent}.") for parent in parents)


def _departed(path: str, one: Obj, appeared: dict[str, Obj], message: str | None) -> ApiChange:
    name = path.rpartition(".")[2]
    same = [
        (new_path, new)
        for new_path, new in appeared.items()
        if new_path.rpartition(".")[2] == name and new.kind == one.kind
    ]
    if len(same) > 1:
        return ApiChange("removed", path, message=message, detail=f"{len(same)} candidates")
    if same and not one.trivial and _alike(one, same[0][1]):
        return ApiChange("moved", path, new_path=same[0][0], message=message)
    return ApiChange("removed", path, message=message)


def _alike(old: Obj, new: Obj) -> bool:
    return old.params is not None and old.params == new.params and old.bases == new.bases


def _changed(path: str, old: Obj, new: Obj, message: str | None) -> Iterator[ApiChange]:
    if old.kind != new.kind:
        yield ApiChange("kind_changed", path, detail=f"{old.kind} -> {new.kind}")
        return
    if old.bases and not set(old.bases) <= set(new.bases):
        yield ApiChange("bases_changed", path, detail=", ".join(old.bases))
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
    for one in added:
        if one.required:
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
