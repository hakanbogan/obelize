"""The rule kinds the user's own plugins provide, found by entry point and run only when allowed.

A plugin is code the user installed in their own environment: it runs in this process with the
user's rights and sees every file the run reads, so it is not a pack. A pack names it (`kind:
plugin`), and what may run is the user's to say, by distribution and entry point, in their own
configuration; a repository never says, and a bundled pack never asks. Nothing is imported before
that is settled, and what was loaded is recorded in the run folder with the hash of its `RECORD`.
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, ValidationError

from obelize.models.fields import printable
from obelize.packs.loader import PackError
from obelize.packs.schema import PluginChange

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from obelize.packs.schema import PackDocument
    from obelize.transforms.base import Rule

# The entry point group a plugin registers its kinds in, and the version of the interface it is
# written against: a plugin that says another is refused, not guessed at.
GROUP: Final = "obelize.kinds"
API: Final = 1


class PluginError(PackError):
    """A plugin a pack requires that cannot run: missing, not allowed, the wrong release, broken."""


class Params(BaseModel):
    """What a plugin's `params` model derives from: closed, so a mistyped key is an error."""

    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True, slots=True)
class Permit:
    """One entry of the user's `plugins`: a distribution, and the entry point it may provide."""

    distribution: str
    name: str


@dataclass(frozen=True, slots=True)
class Used:
    """A plugin that was loaded, as the run folder records it."""

    name: str
    distribution: str
    version: str
    # The hash of the distribution's `RECORD`, which lists the hash of every file it installed.
    record_sha256: str | None


# What a run has loaded: the kind by entry point name, and what was recorded of it.
_KINDS: dict[str, Any] = {}
_USED: dict[str, Used] = {}


@dataclass(frozen=True, slots=True)
class Activated:
    """What `activate` loaded, and the packs it could not make ready, with why."""

    used: tuple[Used, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()


def activate(
    packs: Iterable[PackDocument], permits: Iterable[Permit], *, skip: bool = False
) -> Activated:
    """Load every plugin the packs require, or raise `PluginError` saying why one cannot be.

    Settled one pack at a time and before any file is read: the plugin is allowed by the user, is
    in a release the pack names, speaks this interface, and takes the params the pack gives it.
    With `skip`, a pack that cannot be made ready is set aside and named instead of stopping the
    run, for a run the user did not name its packs for.
    """
    _KINDS.clear()
    _USED.clear()
    allowed = {(str(canonicalize_name(one.distribution)), one.name) for one in permits}
    skipped: list[tuple[str, str]] = []
    for pack in packs:
        try:
            _ready(pack, allowed)
        except PluginError as error:
            if not skip:
                raise
            skipped.append((pack.id, str(error)))
    return Activated(tuple(_USED.values()), tuple(skipped))


def _ready(pack: PackDocument, allowed: set[tuple[str, str]]) -> None:
    for requirement in pack.requires_plugins:
        found = _load(pack.id, requirement.name, requirement.version, allowed)
        _KINDS[requirement.name] = found[0]
        _USED[requirement.name] = found[1]
    for change in pack.changes:
        if isinstance(change, PluginChange):
            _check_params(pack.id, change)


def used(pack: PackDocument) -> tuple[Used, ...]:
    """What this pack's required plugins recorded, in the pack's order."""
    return tuple(_USED[one.name] for one in pack.requires_plugins if one.name in _USED)


@contextmanager
def _away_from_here() -> Iterator[None]:
    """`sys.path` without the working directory, while plugins are found and imported.

    `python -m obelize` puts it first, and a repository the person is in could then hold a
    distribution of the allowed name, or a module of the allowed plugin's, that is found before the
    one installed. The list is put back as it was.
    """
    here = {os.path.normcase(os.path.realpath(entry or ".")) for entry in ("", os.getcwd())}
    kept = list(sys.path)
    sys.path[:] = [
        entry for entry in kept if os.path.normcase(os.path.realpath(entry or ".")) not in here
    ]
    try:
        yield
    finally:
        sys.path[:] = kept


def _load(pack: str, name: str, wanted: str, allowed: set[tuple[str, str]]) -> tuple[Any, Used]:
    with _away_from_here():
        here = [
            one
            for one in metadata.entry_points(group=GROUP)
            if one.name == name and one.dist is not None and one.dist.metadata.get("Name")
        ]
        permitted = [one for one in here if (canonicalize_name(_named(one)), name) in allowed]
        if len(permitted) == 1:
            kind = _import(pack, name, permitted[0], wanted)
    if not here:
        raise PluginError(
            f"{pack} requires the plugin {name!r}, which no installed distribution provides "
            f"(entry point group {GROUP}). Install it in the environment obelize runs in."
        )
    if len(permitted) != 1:
        who = ", ".join(sorted({_named(one) for one in here}))
        raise PluginError(
            f"{pack} requires the plugin {name!r}, provided by {who}, and "
            f"{'none of them is' if not permitted else 'more than one is'} allowed. A plugin is "
            f"code that runs with your rights: allow one in ~/.config/obelize/config.yml, "
            f"under plugins, as `- distribution: <name>` and `name: {name}`."
        )
    dist = permitted[0].dist
    assert dist is not None  # noqa: S101 - `here` holds no entry without one
    return kind, Used(name, dist.name, dist.version, _record(dist))


def _named(entry: metadata.EntryPoint) -> str:
    assert entry.dist is not None  # noqa: S101 - `_load` keeps only entries that have one
    return entry.dist.name


def _import(pack: str, name: str, entry: metadata.EntryPoint, wanted: str) -> Any:
    """The kind an allowed entry point names, once its release is the one the pack wants."""
    dist = entry.dist
    assert dist is not None  # noqa: S101 - `_load` keeps only entries that have one
    try:
        fits = Version(dist.version) in SpecifierSet(wanted)
    except InvalidVersion:
        fits = False
    if not fits:
        raise PluginError(
            f"{pack} requires {name!r} in {wanted}, and {dist.name} {dist.version} is installed."
        )
    try:
        kind = entry.load()
    except Exception as error:
        raise PluginError(
            f"the plugin {name!r} ({dist.name}) did not load: {type(error).__name__}"
        ) from error
    if getattr(kind, "api", None) != API or not _takes(kind):
        raise PluginError(
            f"the plugin {name!r} ({dist.name}) does not speak plugin interface {API}: a kind has "
            f"`api = {API}`, a `params` model derived from obelize.plugin.Params and a `rule` "
            f"method."
        )
    return kind


def _record(dist: metadata.Distribution) -> str | None:
    """The sha256 of the bytes of the distribution's `RECORD`, as `sha256sum` gives them."""
    try:
        path = next(
            (
                one.locate()
                for one in dist.files or ()
                if one.name == "RECORD" and one.parent.name.endswith(".dist-info")
            ),
            None,
        )
        return None if path is None else hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return None


def _takes(kind: Any) -> bool:
    params = getattr(kind, "params", None)
    return (
        isinstance(params, type)
        and issubclass(params, Params)
        and callable(getattr(kind, "rule", None))
    )


def _check_params(pack: str, change: PluginChange) -> None:
    try:
        _KINDS[change.plugin].params.model_validate(change.params)
    except ValidationError as error:
        said = "; ".join(
            f"{'.'.join(map(str, one['loc']))}: {one['msg']}" if one["loc"] else one["msg"]
            for one in error.errors()
        )
        raise PluginError(
            f"{pack}: the params of {change.id!r} are not valid: {printable(said)}"
        ) from error
    except Exception as error:
        raise PluginError(
            f"{pack}: the plugin {change.plugin!r} failed reading the params of {change.id!r}: "
            f"{type(error).__name__}"
        ) from error


def rule(change: PluginChange) -> Rule:
    """The rule a plugin makes of one change, which `activate` has loaded and read the params of."""
    kind = _KINDS.get(change.plugin)
    if kind is None:
        raise PluginError(
            f"the plugin {change.plugin!r} was not loaded, so {change.id!r} cannot run"
        )
    return kind.rule(change.id, kind.params.model_validate(change.params))  # type: ignore[no-any-return]


def clear() -> None:
    """Forget what was loaded."""
    _KINDS.clear()
    _USED.clear()


__all__ = [
    "API",
    "GROUP",
    "Activated",
    "Params",
    "Permit",
    "PluginError",
    "Used",
    "activate",
    "clear",
    "rule",
    "used",
]
