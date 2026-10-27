"""`obelize pack synth`: a migration pack made from what two releases of a library offer.

The pack is data like any other. It renames the names the library renamed (where the library's own
message says to use another), moves up the ones that left a submodule, flags the rest for a person
(removed, moved elsewhere, a signature that changed, deprecated) with the library's words where it
gave any, and moves the dependency line. Its fixtures are written from the comparison and its
answer keys from the rules, as `pack new` does, and the pack is held to `pack test` before it is
kept. What two surfaces cannot show, what a function does, is written into its limitations: the
tests of the repository decide it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from obelize import pattern
from obelize.apidiff.diff import ApiChange, Successors, accepts, names_only
from obelize.apidiff.surface import Obj
from obelize.models import CallShape
from obelize.models.fields import DISPLAY_TEXT_LIMIT, printable
from obelize.packs import loader
from obelize.packs.schema import under_any
from obelize.packtools import check, guided

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from packaging.version import Version

    from obelize import libdiff
    from obelize.apidiff.surface import Param, Surface

# More groups of one kind than this are folded into one that says less.
MAX_GROUPS: Final = 60
# Beside the pack: for a removed name, the new names it may have become, for a model to read.
HINTS: Final = "hints.json"
HINTS_LIMIT: Final = 1 << 20
# The most names one fixture uses: a pack for a large library names thousands, and the fixtures
# only have to show each kind of change working, which a sample does.
FIXTURE_NAMES: Final = 60
# The most a pack file may be, with room under the loader's limit for the answer keys.
PACK_BYTES: Final = 900_000
_QUOTE_CHARS: Final = 240
# The kinds of parameter a call may give by position.
_PLACED: Final = ("positional-only", "positional or keyword")
_LISTED: Final = 20
_GENERIC: Final = {
    "removed": "Removed in {label}.",
    "moved": "Moved in {label}.",
    "signature": "Its signature changed in {label}.",
    "deprecated": "Deprecated in {label}.",
    "guide": "The migration guide says it changed in {label}.",
}
_SUGGESTED: Final = {
    "removed": "Find what replaces it in the release notes.",
    "moved": "Use its new place.",
    "signature": "Read the new signature.",
    "deprecated": "Replace it before it is removed.",
    "guide": "Follow the guide.",
}
_LIMITATIONS: Final = (
    "Made from the public API of two releases: a change in what a function does, not in what it "
    "is called or takes, is not here. Only the tests of the repository show it.",
    "Names built at import time, exported through __getattr__ or implemented in compiled code "
    "are not seen, so they are neither renamed nor flagged.",
    "A method called on an object whose class obelize cannot tell is not found; names reached "
    "through the module are.",
)
_CALL_NOTE: Final = (
    "A name flagged for its signature is reported at a call that passes what changed, leaves out "
    "what it now needs or has a * or ** argument, and at a use that is no call unless the name is "
    "imported, annotated or handed to a call; what receives a handed name may call it with "
    "anything. A class whose bases changed is reported where code derives from it, not at a call."
)
_CLASS_NOTE: Final = (
    "A name under a class whose parameters changed is reported as that class, and a class flagged "
    "only for its bases or its kind is left to the members flagged under it."
)
_GUIDE_NOTE: Final = (
    "Some changes were drafted from a migration guide by a model and kept only after code checked "
    "each against the guide's text and the API of both releases. A change from a guide reports "
    "unless the API diff itself shows the old name going and the new one able to take its place; "
    "what a guide says a function does is not checked."
)


class _Plain(yaml.SafeDumper):
    """A pack is edited by hand, so a value that repeats (the day) is written out and never as an
    alias."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


class SynthError(ValueError):
    """Why a pack could not be made, in words for the person who asked."""


class SynthTooLargeError(SynthError):
    """A pack that would name more than a pack may hold: the library changed too much to flag name
    by name, and only the names a repository uses can be."""


class SynthDefectError(SynthError):
    """A pack obelize made that its own checks refuse: a bug, not a request to change."""


@dataclass(frozen=True, slots=True)
class Request:
    """Two releases of one distribution, the module compared, and where the newer was read."""

    distribution: str
    old: Version
    new: Version
    module: str
    requires_python: str
    url: str
    sha256: str
    retrieved: dt.date
    # The paths below the module that a repository uses: only changes to these, to what is under
    # them and to what they are under are in the pack. `None` is every change.
    scope: frozenset[str] | None = None
    # A digest of the guides the pack takes claims from: another guide is another pack.
    guide: str | None = None
    # The extras the newer release lists as `Provides-Extra`, which its dependency line may keep.
    extras: tuple[str, ...] = ()

    @property
    def pack_id(self) -> str:
        return pack_id(self.distribution, self.old, self.new, self.scope, self.guide)

    @property
    def label(self) -> str:
        return f"{self.distribution} {self.new}"

    @property
    def target(self) -> str:
        return f">={self.new},<{self.new.major + 1}"


@dataclass(frozen=True, slots=True)
class Made:
    """The pack's folder, how many names each change covers, and how many names it could not judge
    because the newer release makes its exports when it is imported."""

    folder: Path
    pack_id: str
    covered: Mapping[str, int]
    unseen: int
    guided: guided.Outcome | None = None
    # A pack that an earlier run left, which this one wrote nothing into.
    reused: bool = False


@dataclass(frozen=True, slots=True)
class _Member:
    """A method the library deprecated for another of its class: the new name, the keywords the new
    one takes where a call must be checked against them, and what the library said."""

    new: str
    takes: tuple[str, ...] | None
    message: str


@dataclass(frozen=True, slots=True)
class _Flag:
    category: str
    message: str
    suggestion: str
    # Whether a parameter of it changed, which no message about its members says.
    params: bool = False
    # The calls its parameter changes are about; `None` where it is flagged wherever it is used.
    shape: CallShape | None = None


def pack_id(
    distribution: str,
    old: Version,
    new: Version,
    scope: frozenset[str] | None = None,
    guide: str | None = None,
) -> str:
    """`<distribution>/<old>-to-<new>`, in the characters a pack id may have; a pack for the names a
    repository uses ends with a digest of them, so it is not mistaken for the whole, and one with
    claims from guides with a digest of those."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{old}-to-{new}".lower()).strip("-")
    if scope is not None:
        slug += "-for-" + hashlib.sha256("\n".join(sorted(scope)).encode()).hexdigest()[:8]
    if guide is not None:
        slug += f"-with-{guide}"
    return f"{canonicalize_name(distribution)}/{slug}"


def today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def free(directory: Path, request: Request) -> Path:
    """The folder a pack made from `request` goes in. One that exists is never written into, so it
    is refused before anything is asked of a model."""
    folder = directory / request.pack_id
    if folder.exists():
        raise SynthError(
            f"{folder} exists already; pack synth makes a folder and never writes into one."
        )
    return folder


def make(
    directory: Path,
    request: Request,
    old: Surface,
    changes: Sequence[ApiChange],
    new: Surface | None = None,
    drafted: guided.Drafted | None = None,
) -> Made:
    """Make `<directory>/<provider>/<slug>/`, load it and check it; a folder that exists is never
    written into, and one that does not pass `pack test` is removed. With the newer surface, the
    names a removed one may have become are written beside the pack (`HINTS`). With what a model
    drafted from a guide, the claims that pass `guided.accept` are in the pack, and what became of
    each is written beside it (`guided.RECORD`); if the pack with them fails its own checks, it is
    made without them, under the id of a pack made without a guide, and so is not taken for one."""
    folder = free(directory, request)
    plan = _Plan.build(request, old, changes, new)
    if drafted is None or new is None:
        return _write(folder, request, plan, old, new)
    outcome = guided.accept(drafted, plan.view(new, changes))
    written = True
    try:
        made = _write(
            folder, request, _Plan.build(request, old, changes, new, outcome.accepted), old, new
        )
    except SynthError as error:
        if not outcome.accepted:
            raise
        outcome = guided.reject_all(outcome, str(error).splitlines()[0])
        request = replace(request, guide=None)
        plan = _Plan.build(request, old, changes, new)
        folder = directory / request.pack_id
        # An earlier pack from these two releases is this one, which the claims would not change.
        written = not folder.exists()
        made = (
            _write(folder, request, plan, old, new)
            if written
            else Made(folder, request.pack_id, plan.covered(), plan.unseen, reused=True)
        )
    if written:
        record = {**outcome.document(request.retrieved), "pack": request.pack_id}
        (folder / guided.RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return replace(made, guided=outcome)


def _write(folder: Path, request: Request, plan: _Plan, old: Surface, new: Surface | None) -> Made:
    if not plan.symbols:
        hidden = (
            f" {plan.unseen} name(s) could not be judged, since the newer release makes its "
            f"exports when it is imported."
            if plan.unseen
            else ""
        )
        raise SynthError(
            f"{request.distribution} {request.old} and {request.new} export the same names with "
            f"the same signatures, so there is nothing to synthesize.{hidden}"
        )
    files = plan.files()
    if len(files["pack.yaml"].encode()) > PACK_BYTES:
        raise SynthTooLargeError(
            f"{request.distribution} {request.old} to {request.new} changed {len(plan.symbols)} "
            f"names, more than a pack holds."
        )
    try:
        for name, text in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        loaded = loader.load(str(folder / loader.PACK_FILENAME))
        keys = _keys(loaded, folder)
        for name, data in keys.items():
            (folder / name).write_bytes(data)
        _agree(plan, keys)
        problems = [
            f"{result.name}: {problem}"
            for result in check.run(loaded)
            for problem in result.problems
        ]
        if problems:
            raise SynthDefectError("the pack made fails pack test:\n  " + "\n  ".join(problems))
    except loader.PackInvalidError as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise SynthDefectError(str(error)) from error
    except SynthDefectError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if new is not None:
        _hint(folder, plan, old, new)
    return Made(folder, request.pack_id, plan.covered(), plan.unseen)


def _hint(folder: Path, plan: _Plan, old: Surface, new: Surface) -> None:
    request = plan.request
    found: dict[str, str] = {}
    later = Successors(old, new)
    for path, one in plan.flags.items():
        names = later.of(path) if one.category == "removed" and path else []
        if names:
            listed = ", ".join(f"{request.module}.{name} ({kind})" for name, kind in names)
            found[f"{request.module}.{path}"] = _text(
                f"Names {request.label} has that the older release did not, closest in spelling "
                f"first: {listed}."
            )
    if found:
        (folder / HINTS).write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")


def hints_for(reference: str) -> dict[str, str]:
    """What `make` wrote beside the pack at `reference`; none for a pack that is not a file's."""
    try:
        with (Path(reference).parent / HINTS).open("rb") as handle:
            document = json.loads(handle.read(HINTS_LIMIT))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    return {
        printable(name): printable(text)
        for name, text in document.items()
        if isinstance(name, str) and isinstance(text, str)
    }


def request(
    distribution: str,
    old: Version,
    new: Version,
    compared: libdiff.Comparison,
    scope: frozenset[str] | None = None,
    guide: str | None = None,
    retrieved: dt.date | None = None,
) -> Request:
    """The request for two releases that were compared: the newer file is what the pack cites, on
    the day it is read, or the day a record of an earlier run says."""
    file = compared.new
    try:
        SpecifierSet(file.requires_python or "")
        python = file.requires_python or ">=3.9"
    except InvalidSpecifier:
        python = ">=3.9"
    page = f"https://pypi.org/project/{canonicalize_name(distribution)}/{new}/"
    return Request(
        distribution=distribution,
        old=old,
        new=new,
        module=compared.module,
        requires_python=python,
        url=file.url if file.url.startswith("https://") else page,
        sha256=file.sha256,
        retrieved=retrieved or today(),
        scope=scope,
        guide=guide,
        extras=compared.extras,
    )


def _keys(loaded: loader.LoadedPack, folder: Path) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="obelize-synth-") as work:
        decided = check.migrated(loaded, folder, Path(work))
    keys = {
        f"fixtures/positive/{name.replace('.before.', '.after.')}": data
        for name, (written, data) in decided.items()
        if written
    }
    manifest = check.manifest_output(loaded, folder)
    assert manifest is not None  # noqa: S101 - every pack made here has the fixture and the change
    keys["fixtures/positive/requirements.after.txt"] = manifest
    return keys


def _agree(plan: _Plan, keys: Mapping[str, bytes]) -> None:
    """The rules must write what the comparison says into each fixture of a rename."""
    for name, expected in plan.expected().items():
        written = keys.get(f"fixtures/positive/{name.replace('.before.', '.after.')}")
        if written is None or written.decode("utf-8") != expected:
            raise SynthDefectError(
                f"the rules do not write what the comparison says into {name}, so a rename "
                f"that obelize cannot make as one is not made by this pack."
            )


def _quote(text: str) -> str:
    cleaned = printable(" ".join(text.split()))
    return cleaned if len(cleaned) <= _QUOTE_CHARS else cleaned[: _QUOTE_CHARS - 1] + "…"


def _text(text: str) -> str:
    return text if len(text) <= DISPLAY_TEXT_LIMIT else text[: DISPLAY_TEXT_LIMIT - 1] + "…"


def _in_scope(path: str, scope: frozenset[str] | None) -> bool:
    """Whether a repository that uses `scope` meets `path`: one of them, under one, or above one."""
    if scope is None:
        return True
    parts = path.split(".")
    return any(".".join(parts[:end]) in scope for end in range(1, len(parts) + 1)) or any(
        used.startswith(f"{path}.") for used in scope
    )


def _lands(module: str, path: str, landed: str, exported: bool) -> str:
    """Where the pack's rename of `path` puts it, as the schema reads it."""
    stem = f"{module}.{path}".rpartition(".")[0]
    return f"{_parent(stem) if exported else stem}.{_leaf(landed)}"


def _leaf(path: str) -> str:
    return path.rpartition(".")[2]


def _parent(path: str) -> str:
    return path.rpartition(".")[0]


def _at_module(path: str, olds: Mapping[str, Obj]) -> bool:
    """Whether `path` is a name of a module, and not a member of a class."""
    parent = _parent(path)
    return not parent or (parent in olds and olds[parent].kind == "module")


def _of_class(path: str, olds: Mapping[str, Obj]) -> bool:
    """Whether `path` is a member of a class."""
    parent = olds.get(_parent(path))
    return parent is not None and parent.kind == "class"


def _member_move(change: ApiChange) -> bool:
    """Whether a deprecation or a removal names the method to use, and a call of the old one can
    move to it."""
    return (
        change.type in ("deprecated", "renamed")
        and change.new_path is not None
        and (change.same_signature or change.takes is not None)
        and names_only(change.message)
    )


def _up_one(path: str, target: str, olds: Mapping[str, Obj]) -> bool:
    """Whether `target` is `path` taken out of its submodule into the package above it."""
    parent = _parent(path)
    return bool(parent) and _at_module(path, olds) and _parent(parent) == _parent(target)


def _removed(label: str, change: ApiChange) -> tuple[str, str]:
    if not change.message:
        return f"Removed in {label}.", _SUGGESTED["removed"]
    return f"Removed in {label}. The library said: {_quote(change.message)}", "Follow its message."


def _signature_text(label: str, change: ApiChange) -> str:
    param = f"`{change.param}`"
    match change.type:
        case "param_renamed":
            return (
                f"Parameter {param} was removed in {label}; `{change.new_param}` takes its place."
            )
        case "param_removed":
            swallowed = f", and {change.detail}, so a call that passes it may raise or do nothing"
            return f"Parameter {param} was removed in {label}{swallowed if change.detail else ''}."
        case "param_required_added":
            return f"Parameter {param} is required in {label}."
        case "param_kind_changed":
            return f"Parameter {param} changed from {change.detail} in {label}."
        case "default_changed":
            return f"The default of {param} changed from {change.detail} in {label}."
        case "bases_changed":
            return f"It no longer derives from {change.detail} in {label}."
        case _:
            return f"It changed from {change.detail} in {label}."


def _merge(entries: Sequence[tuple[str, str, str, bool, CallShape | None]]) -> _Flag:
    """One name's reasons as one flag: the first's category and advice, every message in order, and
    the calls that all of them are about, if each is about some."""
    category, _, suggestion, _, _ = entries[0]
    seen: list[str] = []
    for _, message, _, _, _ in entries:
        if message not in seen:
            seen.append(message)
    params = any(entry[3] for entry in entries)
    shapes = [entry[4] for entry in entries]
    shape = None if None in shapes else _union([one for one in shapes if one is not None])
    return _Flag(category, _text(" ".join(seen)), suggestion, params, shape)


def _union(shapes: Sequence[CallShape]) -> CallShape:
    firsts = [one.positional_from for one in shapes if one.positional_from is not None]
    omits = {name: at for one in shapes for name, at in one.omits.items()}
    return CallShape(
        keywords=tuple(sorted({name for one in shapes for name in one.keywords})),
        positional_from=min(firsts, default=None),
        omits=dict(sorted(omits.items())),
        bases=any(one.bases for one in shapes),
    )


def _piece(
    change: ApiChange, olds: Mapping[str, Obj], built: tuple[_Built, _Built] | None = None
) -> CallShape | None:
    """The calls one parameter change is about, from where the old release has the parameter, or
    `None` where they cannot be told: a method, which a call may pass its object to, and a change
    that the arguments of the calls it breaks do not show."""
    old, name = olds.get(change.path), change.param or ""
    if old is None or _of_class(change.path, olds) or not name.isascii():
        return None
    at, kind = next(
        ((at, one.kind) for at, one in enumerate(old.params or ()) if one.name == name), (0, "")
    )
    placed = at if kind in _PLACED else None
    match change.type:
        case "bases_changed":
            # Only where the class is built with what it was: else a call of it may be affected.
            return CallShape(bases=True) if built and _alike(change.path, *built) else None
        case "param_removed":
            return CallShape(
                keywords=() if kind == "positional-only" else (name,), positional_from=placed
            )
        case "param_renamed":
            return CallShape(keywords=(name,))
        case "param_kind_changed" if change.detail.endswith("-> keyword-only"):
            return CallShape(positional_from=at)
        case "param_kind_changed" if change.detail.endswith("-> positional-only"):
            return CallShape(keywords=(name,))
        case "default_changed":
            return CallShape(omits={name: placed})
        case "param_required_added":
            return CallShape(omits={name: None})
    return None


class _Built:
    """What the classes of one release are built with, through the names their bases go by."""

    def __init__(self, objects: Mapping[str, Obj]) -> None:
        self.objects = objects
        self._paths = {one.path: one for one in objects.values()}
        self._named: dict[str, set[str]] = {}
        for one in objects.values():
            if one.kind == "class":
                leaf = one.path.rpartition(".")[2]
                self._named.setdefault(leaf, set()).add(one.target or one.path)

    def of(self, one: Obj, seen: frozenset[str] = frozenset()) -> tuple[Param, ...] | None:
        """The parameters of the class's own `__init__`, else of the first base's that has one, else
        none; `None` where a base cannot be told from another class of its name."""
        if one.params is not None:
            return one.params
        if "__init__" not in one.inherited:
            return ()
        for base in one.bases:
            found = self._named.get(base.partition("[")[0].rpartition(".")[2], set())
            parent = self._paths.get(next(iter(found))) if len(found) == 1 else None
            if parent is None or parent.path in seen | {one.path}:
                return None
            if parent.params is not None or "__init__" in parent.inherited:
                return self.of(parent, seen | {one.path})
        return None


def _alike(path: str, before: _Built, after: _Built) -> bool:
    """Whether a class is built with what it was: both releases give it an `__init__` of its own,
    which the diff compares, or what it gets from its bases takes what it took."""
    old, new = before.objects[path], after.objects.get(path)
    if new is None or (old.params is not None and new.params is not None):
        return new is not None
    was, now = before.of(old), after.of(new)
    return (
        was is not None
        and now is not None
        and accepts(Obj("", "function", was), Obj("", "function", now))
    )


def _warned(
    change: ApiChange, parameters: Collection[str], olds: Mapping[str, Obj]
) -> CallShape | None:
    """The calls a deprecation is about, where its message names, as a word, a parameter of the same
    name that the diff reports changed: those that pass it. A message that names none may be about
    the whole name."""
    named = [
        name
        for name in sorted(parameters)
        if re.search(rf"\b{re.escape(name)}\b", change.message or "")
    ]
    pieces = [_piece(ApiChange("param_removed", change.path, param=name), olds) for name in named]
    return (
        _union([one for one in pieces if one is not None])
        if pieces and None not in pieces
        else None
    )


def _outermost(flags: Mapping[str, _Flag]) -> tuple[dict[str, _Flag], tuple[str, ...]]:
    """The flagged names no other flagged name contains, and the ones left out.

    Two changes may not flag one surface, so a class and its members cannot both be. A class whose
    parameters changed stands for its members; one flagged for anything else (its bases, its kind,
    a notice) gives way to the members flagged under it, whose words say more.
    """
    # Every name with a flag somewhere below it: a prefix of a flagged path's parent.
    holding = {prefix for path in flags for prefix in _prefixes(_parent(path))}
    yielding = {
        path
        for path, one in flags.items()
        if one.category in ("signature", "deprecated") and not one.params and path in holding
    }
    kept: dict[str, _Flag] = {}
    dropped: list[str] = sorted(yielding)
    for path in sorted(set(flags) - yielding):
        if any(prefix in kept for prefix in _prefixes(_parent(path))):
            dropped.append(path)
        else:
            kept[path] = flags[path]
    return kept, tuple(dropped)


def _prefixes(path: str) -> list[str]:
    """`a.b.c`, `a.b`, `a`: the names a dotted path is at or below."""
    out = []
    while path:
        out.append(path)
        path = _parent(path)
    return out


def _args(obj: Obj, shape: CallShape | None = None, *, matching: bool = True) -> str:
    """Arguments a call may be written with: a zero for each parameter that is required. With the
    shape of a flag, a call it is about, or if not `matching`, one it is not."""
    params = [one for one in obj.params or () if one.required and one.kind != "variadic keyword"]
    positional = ["0" for one in params if one.kind != "keyword-only"]
    named = [one.name for one in params if one.kind == "keyword-only"]
    if shape is not None and matching:
        if shape.keywords:
            named.append(shape.keywords[0])
        elif shape.positional_from is not None:
            positional += ["0"] * (shape.positional_from + 1 - len(positional))
    elif shape is not None:
        positional = positional[: shape.positional_from]
        named = [name for name in named if name not in shape.keywords] + list(shape.omits)
    return ", ".join([*positional, *(f"{name}=0" for name in named)])


@dataclass(frozen=True, slots=True)
class _Plan:
    """What the pack says, before it is written, each part derived from the changes."""

    request: Request
    # Renamed in place (old path -> new path), with and without the claim that calls carry.
    with_calls: Mapping[str, str]
    references: Mapping[str, str]
    # Taken out of a submodule (old path -> new path, in the package above it).
    exports: Mapping[str, str]
    # Methods of a class that the library deprecated for another (old path -> the new one).
    members: Mapping[str, _Member]
    flags: Mapping[str, _Flag]
    dropped: tuple[str, ...]
    olds: Mapping[str, Obj]
    unseen: int
    # What was taken from a guide: where each such name was read, and the calls it asks to rewrite.
    cited: Mapping[str, guided.Cite] = field(default_factory=dict)
    patterns: tuple[guided.Accepted, ...] = ()

    @property
    def names(self) -> frozenset[str]:
        """What the scan looks for, below the module: the names, and the submodules the exports
        leave, whose imports are rewritten with them."""
        names = {*self.with_calls, *self.references, *self.exports, *self.members, *self.flags}
        names |= {_parent(path) for path in self.exports} | {one.path for one in self.patterns}
        return frozenset(names)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(f"{self.request.module}.{name}" for name in self.names))

    def view(self, new: Surface, changes: Sequence[ApiChange]) -> guided.View:
        """What a claim from a guide is held against: this plan, the diff and the two releases."""
        made = {**self.with_calls, **self.references, **self.exports}
        made |= {path: f"{_parent(path)}.{one.new}" for path, one in self.members.items()}
        plain = {
            path
            for path, one in self.flags.items()
            if one.category in ("removed", "deprecated") and not one.params and one.shape is None
        }
        return guided.View(
            self.request.module,
            self.olds,
            new.relative(),
            changes,
            self.names,
            made,
            frozenset(plain),
            lambda path: _in_scope(path, self.request.scope),
        )

    @classmethod
    def build(
        cls,
        request: Request,
        old: Surface,
        changes: Sequence[ApiChange],
        new: Surface | None = None,
        claims: Sequence[guided.Accepted] = (),
    ) -> _Plan:
        olds = old.relative()
        built = None if new is None else (_Built(olds), _Built(new.relative()))
        label = request.label
        with_calls: dict[str, str] = {}
        references: dict[str, str] = {}
        exports: dict[str, str] = {}
        members: dict[str, _Member] = {}
        parts: dict[str, list[tuple[str, str, str, bool, CallShape | None]]] = {}

        def flag(
            path: str,
            category: str,
            message: str,
            suggestion: str,
            *,
            params: bool = False,
            shape: CallShape | None = None,
        ) -> None:
            parts.setdefault(path, []).append((category, message, suggestion, params, shape))

        moved = {
            change.path
            for change in changes
            if _member_move(change) and _of_class(change.path, olds)
        }
        # The parameters each name's diff reports as changed.
        parameters: dict[str, set[str]] = {}
        for change in changes:
            if change.param and (
                change.type.startswith("param_") or change.type == "default_changed"
            ):
                parameters.setdefault(change.path, set()).add(change.param)
        for change in changes:
            path, target = change.path, change.new_path
            if change.type == "unseen" or not _in_scope(path, request.scope):
                continue
            if path in moved:
                # What the old spelling's own signature says is no more than the new one's.
                if change.type in ("deprecated", "renamed") and target is not None:
                    members[path] = _Member(_leaf(target), change.takes, change.message or "")
                continue
            if change.type == "renamed" and target is not None and _at_module(path, olds):
                (with_calls if change.same_signature else references)[path] = target
            elif change.type == "moved" and target is not None and _up_one(path, target, olds):
                exports[path] = target
            elif change.type in ("moved", "renamed") and target is not None:
                place = f"{request.module}.{target}"
                flag(path, "moved", f"Moved in {label}: it is now {place}.", _SUGGESTED["moved"])
            elif change.type == "removed":
                flag(path, "removed", *_removed(label, change))
            elif change.type == "deprecated":
                said = f" The library said: {_quote(change.message)}" if change.message else ""
                shape = _warned(change, parameters.get(path, ()), olds)
                text = f"Deprecated in {label}.{said}"
                flag(path, "deprecated", text, _SUGGESTED["deprecated"], shape=shape)
            else:
                changed = change.type.startswith("param_") or change.type == "default_changed"
                text = _signature_text(label, change)
                shape = _piece(change, olds, built)
                flag(path, "signature", text, _SUGGESTED["signature"], params=changed, shape=shape)
        cited: dict[str, guided.Cite] = {}
        patterns: list[guided.Accepted] = []
        for got in claims:
            # What a claim becomes stands for the diff's report of the name, which it replaces.
            parts.pop(got.path, None)
            cited[got.path] = got.cite
            target = got.target or ""
            match got.route:
                case "rename":
                    (with_calls if got.calls else references)[got.path] = target
                case "member":
                    members[got.path] = _Member(_leaf(target), got.takes, "")
                case "pattern":
                    patterns.append(got)
                case _:
                    flag(got.path, "guide", *got.words(), shape=got.shape)
        flags = {path: _merge(entries) for path, entries in parts.items()}
        # A new name must not be one the pack looks for, or the rewritten file is a finding again.
        flagged = tuple(f"{request.module}.{path}" for path in flags)
        for table in (with_calls, references, exports):
            for path, landed in list(table.items()):
                if under_any(f"{request.module}.{landed}", flagged):
                    place = f"{request.module}.{landed}"
                    message = f"Moved in {label}: it is now {place}."
                    flags[path] = _Flag("moved", message, _SUGGESTED["moved"])
                    del table[path]
        # Two old names that become one cannot both be renamed (the import would name it twice).
        for table in (with_calls, references, exports):
            landing = {
                path: _lands(request.module, path, landed, table is exports)
                for path, landed in table.items()
            }
            for path, landed in list(table.items()):
                if sum(1 for there in landing.values() if there == landing[path]) > 1:
                    place = f"{request.module}.{landed}"
                    message = f"Moved in {label}: it is now {place}."
                    flags[path] = _Flag("moved", message, _SUGGESTED["moved"])
                    del table[path]
        kept, dropped = _outermost(flags)
        # A new name that is one the pack looks for, or one another member lands on, is flagged.
        standing = tuple(f"{request.module}.{path}" for path in kept)
        landing = {
            path: f"{request.module}.{_parent(path)}.{one.new}" for path, one in members.items()
        }
        looked = {f"{request.module}.{path}" for path in members}
        for path, one in list(members.items()):
            twice = sum(1 for there in landing.values() if there == landing[path]) > 1
            if twice or landing[path] in looked or under_any(landing[path], standing):
                said = f" The library said: {_quote(one.message)}" if one.message else ""
                note = f"Deprecated in {label}.{said}"
                flags[path] = _Flag("deprecated", note, _SUGGESTED["deprecated"])
                del members[path]
        kept, dropped = _outermost(flags)
        unseen = sum(1 for change in changes if change.type == "unseen")
        # A rename turned into a plain report by the checks above has no words of the guide's.
        rewritten = {*with_calls, *references, *members, *(one.path for one in patterns)}
        cited = {
            path: cite
            for path, cite in cited.items()
            if path in rewritten or (path in kept and kept[path].category == "guide")
        }
        return cls(
            request, with_calls, references, exports, members, kept, dropped, olds, unseen, cited,
            tuple(patterns),
        )  # fmt: skip

    def covered(self) -> dict[str, int]:
        return {change["id"]: len(_names(change)) for change in self.changes()}

    def expected(self) -> dict[str, str]:
        """Each rename fixture as the rules must leave it: the old spellings read as the new."""
        module, fixtures = self.request.module, self.fixtures()
        found = {}
        for label, table in (
            ("with_calls", self.with_calls),
            ("references", self.references),
            ("exports", self.exports),
        ):
            if not table:
                continue
            name = _FIXTURES[label]
            text = fixtures[f"fixtures/positive/{name}"]
            for path, landed in table.items():
                text = re.sub(rf"\b{re.escape(f'{module}.{path}')}\b", f"{module}.{landed}", text)
                if label == "exports":
                    old, new = self._home(path), self._home(landed)
                    text = re.sub(rf"\bimport {re.escape(old)}\b", f"import {new}", text)
            found[name] = text
        if self.members:
            found[_MEMBERS_FIXTURE] = self._members_program(renamed=True)
        return found

    def changes(self) -> list[dict[str, Any]]:
        request = self.request
        out: list[dict[str, Any]] = []
        numbers = itertools.count(1)
        for name, calls, table, label in (
            ("rename-with-calls", "allowed", self.with_calls, "with_calls"),
            ("rename-references", "refused", self.references, "references"),
            ("move-up", "allowed", self.exports, "exports"),
        ):
            key = "symbols" if label == "exports" else "renamed"
            for ids, cite, names in self._split(name, table):
                found = {f"{request.module}.{path}": _leaf(table[path]) for path in sorted(names)}
                out.append(
                    self._cited(
                        {
                            "id": ids if cite is None else f"guide-rename-{next(numbers)}",
                            "kind": "rename_symbol",
                            "citation": _text(
                                f"{request.distribution} {request.old} and {request.new}, public "
                                f"API: {_RENAME_CITATION[label]}"
                            ),
                            "params": {"calls": calls, key: found},
                            "fixtures": [
                                "fixtures/negative/already_new.py",
                                f"fixtures/positive/{_FIXTURES[label]}",
                            ],
                        },
                        cite,
                    )
                )
        module = request.module
        numbers = itertools.count(1)
        for ids, cite, names in self._split("rename-members", self.members):
            params: dict[str, Any] = {
                "members": {f"{module}.{path}": self.members[path].new for path in sorted(names)}
            }
            takes = {
                f"{module}.{path}": list(taken)
                for path in sorted(names)
                if (taken := self.members[path].takes) is not None
            }
            if takes:
                params["takes"] = takes
            out.append(
                self._cited(
                    {
                        "id": ids if cite is None else f"guide-member-{next(numbers)}",
                        "kind": "rename_member",
                        "citation": _text(
                            f"{request.distribution} {request.old} and {request.new}, public API: "
                            f"a method the library's deprecation message replaces"
                        ),
                        "params": params,
                        "fixtures": [
                            "fixtures/negative/already_new.py",
                            f"fixtures/positive/{_MEMBERS_FIXTURE}",
                        ],
                    },
                    cite,
                )
            )
        for number, one in enumerate(self.patterns, 1):
            claim = one.claim
            out.append(
                self._cited(
                    {
                        "id": f"guide-pattern-{number}",
                        "kind": "rewrite_pattern",
                        "citation": one.cite.text,
                        "params": {
                            "before": claim.before,
                            "after": claim.after,
                            **({"where": dict(one.where)} if one.where else {}),
                            **({"imports": list(one.imports)} if one.imports else {}),
                        },
                        "fixtures": [
                            "fixtures/negative/already_new.py",
                            f"fixtures/positive/{_PATTERNS_FIXTURE}",
                        ],
                    },
                    one.cite,
                )
            )
        grouped: dict[str, dict[tuple[str, str], list[str]]] = {}
        for path, flag in self.flags.items():
            grouped.setdefault(flag.category, {}).setdefault(
                (flag.message, flag.suggestion), []
            ).append(path)
        for category in _GENERIC:
            groups = _fold(request, category, grouped.get(category, {}))
            for number, ((message, suggestion), paths) in enumerate(groups, 1):
                shapes = {
                    f"{request.module}.{path}": shape.model_dump(mode="json", exclude_defaults=True)
                    for path in sorted(paths)
                    if (shape := self.flags[path].shape) is not None
                }
                out.append(
                    self._cited(
                        {
                            "id": f"{category}-{number}",
                            "kind": "flag_only",
                            "citation": _text(
                                f"{request.distribution} {request.old} and {request.new}, public "
                                f"API"
                            ),
                            "params": {
                                "message": message,
                                "suggestion": suggestion,
                                "symbols": sorted(f"{request.module}.{path}" for path in paths),
                                **({"calls": shapes} if shapes else {}),
                            },
                            "fixtures": [
                                "fixtures/negative/already_new.py",
                                "fixtures/positive/flagged.before.py",
                            ],
                        },
                        self.cited.get(sorted(paths)[0]) if category == "guide" else None,
                    )
                )
        out.append(
            {
                "id": "dependency-line",
                "kind": "manifest_dependency",
                "citation": _text(
                    f"{request.distribution} {request.new} on the index"
                    + (", and the Provides-Extra lines of its METADATA" if request.extras else "")
                ),
                "params": {
                    "from_name": request.distribution,
                    "to_name": request.distribution,
                    "to_spec": request.target,
                    **({"provides_extras": list(request.extras)} if request.extras else {}),
                },
                "fixtures": [
                    "fixtures/negative/requirements_already_new.txt",
                    "fixtures/positive/requirements.before.txt",
                ],
            }
        )
        return out

    def _split(
        self, name: str, table: Mapping[str, Any]
    ) -> list[tuple[str, guided.Cite | None, list[str]]]:
        """The names of a table of renames the library's own words give, as one change under `name`,
        and each name a guide gave as a change of its own."""
        own = [path for path in table if path not in self.cited]
        return [
            *([(name, None, own)] if own else []),
            *((name, self.cited[path], [path]) for path in table if path in self.cited),
        ]

    def _cited(self, change: dict[str, Any], cite: guided.Cite | None) -> dict[str, Any]:
        """A change from a guide: cited by the quote, and by the guide where it has an address."""
        if cite is None:
            return change
        source = cite.source(self.request.retrieved)
        change = {**change, "citation": cite.text}
        return {**change, "source": source.model_dump()} if source is not None else change

    def files(self) -> dict[str, str]:
        return {
            "pack.yaml": self._pack(),
            "SOURCES.md": self._sources(),
            **self.fixtures(),
        }

    def fixtures(self) -> dict[str, str]:
        request = self.request
        found: dict[str, str] = {}
        for label, table in (
            ("with_calls", self.with_calls),
            ("references", self.references),
            ("exports", self.exports),
        ):
            if table:
                names = sorted(table)
                if label == "exports":
                    # An import of each of two submodules binds the package twice, and the rules
                    # leave such a file alone: the fixture shows the names of one.
                    names = [path for path in names if self._home(path) == self._home(names[0])]
                uses = [
                    self._use(path, label != "references", n)
                    for n, path in enumerate(names[:FIXTURE_NAMES])
                ]
                found[f"fixtures/positive/{_FIXTURES[label]}"] = _program(_DOCS[label], uses)
        if self.members:
            found[f"fixtures/positive/{_MEMBERS_FIXTURE}"] = self._members_program(renamed=False)
        if self.patterns:
            found[f"fixtures/positive/{_PATTERNS_FIXTURE}"] = self._patterns_program()
        if self.flags:
            names = sorted(self.flags)[:FIXTURE_NAMES]
            uses = [self._use(path, True, n) for n, path in enumerate(names)]
            found["fixtures/positive/flagged.before.py"] = _program(_DOCS["flagged"], uses)
        # A name both passed and left out is flagged at every call, so none is shown to be let by.
        shaped = [
            path
            for path in sorted(self.flags)
            if (shape := self.flags[path].shape) and not set(shape.keywords) & set(shape.omits)
        ][:FIXTURE_NAMES]
        landed = sorted(
            {*self.with_calls.values(), *self.references.values(), *self.exports.values()}
        )[:FIXTURE_NAMES]
        kept = [self._read(path) for path in landed]
        kept += [
            self._read(f"{_parent(path)}.{one.new}")
            for path, one in sorted(self.members.items())[:FIXTURE_NAMES]
        ]
        # Through the package, since a submodule's import may be one the pack moves.
        kept += [(request.module, self._use(path, True, 0, matching=False)[1]) for path in shaped]
        found["fixtures/negative/already_new.py"] = _program(_DOCS["new"], kept)
        old = f"{request.distribution}=={request.old}"
        if request.extras:
            old += f"\n{request.distribution}[{request.extras[0]}]=={request.old}"
        found["fixtures/positive/requirements.before.txt"] = _requirements(old, _NOTE)
        found["fixtures/negative/requirements_already_new.txt"] = _requirements(
            f"{request.distribution}{request.target}", "Already migrated, and the rule adds no pin."
        )
        return found

    def _members_program(self, *, renamed: bool) -> str:
        """A class derived from each library class that has a renamed method, and a call of each
        method on an instance of it: as the old release spells it, or as the rules write it."""
        chosen = sorted(self.members)[:FIXTURE_NAMES]
        classes = sorted({_parent(path) for path in chosen})
        module = self.request.module
        imports = sorted({self._home(parent) for parent in classes})
        head = "\n".join(f"import {name}" for name in imports)
        bases = "\n\n\n".join(
            f"class Derived{number}({module}.{parent}):\n    pass"
            for number, parent in enumerate(classes)
        )
        calls = "\n".join(
            f"    Derived{classes.index(_parent(path))}()."
            f"{self.members[path].new if renamed else _leaf(path)}({_args(self.olds[path])})"
            for path in chosen
        )
        return f'"""{_DOCS["members"]}"""\n\n{head}\n\n\n{bases}\n\n\ndef uses():\n{calls}\n'

    def _patterns_program(self) -> str:
        """A call of each name a guide's pattern rewrites, written as its `before` says, with a
        class derived from the library's as the receiver of a method."""
        chosen = self.patterns[:FIXTURE_NAMES]
        classes = sorted({cls for one in chosen for cls in one.where.values()})
        head = sorted({self._home(one.path) for one in chosen})
        calls = []
        for one in chosen:
            receiver = pattern.receiver(pattern.parse(one.claim.before or ""))
            number = classes.index(one.where[receiver]) if receiver else 0

            def fill(
                found: re.Match[str], number: int = number, held: str | None = receiver
            ) -> str:
                return f"Derived{number}()" if found[1] == held else "0"

            calls.append(f"    {_META.sub(fill, one.claim.before or '')}")
        bases = "\n\n\n".join(
            f"class Derived{number}({cls}):\n    pass" for number, cls in enumerate(classes)
        )
        imports = "\n".join(f"import {name}" for name in head)
        body = (bases + "\n\n\n") if bases else ""
        return (
            f'"""{_DOCS["patterns"]}"""\n\n{imports}\n\n\n{body}def uses():\n'
            + "\n".join(calls)
            + "\n"
        )

    def _home(self, path: str) -> str:
        """The module a name is imported from: the nearest one above it, or the package."""
        parent = _parent(path)
        while parent and (parent not in self.olds or self.olds[parent].kind != "module"):
            parent = _parent(parent)
        return f"{self.request.module}.{parent}" if parent else self.request.module

    def _use(self, path: str, call: bool, number: int, *, matching: bool = True) -> tuple[str, str]:
        """A line that uses a name of the old release, and the module it needs imported. A name
        flagged for some calls is called as one of them, or, if not `matching`, as none of them."""
        obj, dotted = self.olds[path], f"{self.request.module}.{path}"
        shape = self.flags[path].shape if path in self.flags else None
        # A class that only its bases changed is read, to be derived from: no call is about it.
        called = not matching or shape is None or shape.about_calls
        if call and called and obj.kind in ("function", "class"):
            return self._home(path), f"{dotted}({_args(obj, shape, matching=matching)})"
        return self._home(path), f"handler_{number} = {dotted}"

    def _read(self, path: str) -> tuple[str, str]:
        """A line that reads a name of the new release, at the module level."""
        parent = _parent(path)
        module = f"{self.request.module}.{parent}" if parent else self.request.module
        return module, f"_ = {self.request.module}.{path}"

    def _pack(self) -> str:
        request = self.request
        doc: dict[str, Any] = {
            "id": request.pack_id,
            "pack_version": "0.1.0",
            "provider": request.pack_id.split("/", 1)[0],
            "language": "python",
            "source": {
                "type": "api_diff",
                "url": request.url,
                "retrieved_at": request.retrieved,
                "sha256": request.sha256,
            },
            "from": {"package": request.distribution, "version": f">={request.old},<{request.new}"},
            "to": {
                "package": request.distribution,
                "version": request.target,
                "requires_python": request.requires_python,
            },
            "match": {
                "imports": [request.module],
                "shared": True,
                "symbols": list(self.symbols),
                "prefilter_tokens": [request.module],
            },
            "changes": self.changes(),
            "limitations": [
                *_LIMITATIONS,
                *([_CALL_NOTE] if any(one.shape for one in self.flags.values()) else []),
                *([_CLASS_NOTE] if self.dropped else []),
                *([_GUIDE_NOTE] if self.cited else []),
            ],
        }
        body = yaml.dump(doc, Dumper=_Plain, sort_keys=False, default_flow_style=False, width=100)
        header = _HEADER.format(name=request.distribution, old=request.old, new=request.new)
        return header + body

    def _guides(self) -> str:
        """The guides some changes were drafted from, and whether each is the vendor's own."""
        found = {(one.ref, one.url, one.sha256, one.official) for one in self.cited.values()}
        if not found:
            return ""
        rows = "\n".join(
            f"| {f'<{url}>' if url else ref} | {self.request.retrieved.isoformat()} | `{sha}` | "
            f"{'yes' if official else 'not shown'} |"
            for ref, url, sha, official in sorted(found, key=lambda one: (one[0], one[2]))
        )
        return (
            "\n## The guides\n\n"
            "A model drafted the changes named `guide-...` from these, and code kept only those it "
            "could check. The hash is of the text the model was given.\n\n"
            "| Guide | `retrieved_at` | sha256 of its text | The vendor's own |\n"
            f"|---|---|---|---|\n{rows}\n"
        )

    def _sources(self) -> str:
        request = self.request
        sections = []
        for change in self.changes():
            names = _names(change)
            shown = ", ".join(f"`{name}`" for name in names[:_LISTED])
            more = f", and {len(names) - _LISTED} more" if len(names) > _LISTED else ""
            sections.append(
                f"## {change['id']}\n\n{change['citation'].rstrip('.')}.\n\nNames: {shown}{more}.\n"
            )
        dropped = ", ".join(f"`{name}`" for name in self.dropped[:_LISTED])
        left = f"\nLeft out, as a class above them stands for them: {dropped}.\n" if dropped else ""
        return (
            f"""# Sources for `{request.pack_id}`

Made by `obelize pack synth` from the public API of {request.distribution} {request.old} and
{request.new}, read statically from their files. One section per `changes[].id`. The `.after` files
beside the fixtures are what the rules wrote into them when this pack was made: read each one
before you trust it.

## The retrieved page

| Source | URL | `retrieved_at` |
|---|---|---|
| The release's file | <{request.url}> | {request.retrieved.isoformat()} |

The file's sha256 is `{request.sha256}`.
{self._guides()}
---

"""
            + "\n".join(sections)
            + left
        )


_FIXTURES: Final = {
    "with_calls": "renamed_calls.before.py",
    "references": "renamed_references.before.py",
    "exports": "moved_up.before.py",
}
_META: Final = re.compile(r"\$([A-Za-z_]\w*)")
_MEMBERS_FIXTURE: Final = "renamed_members.before.py"
_PATTERNS_FIXTURE: Final = "guided_patterns.before.py"
_DOCS: Final = {
    "members": "Methods the library deprecated for another, called on a class derived from theirs.",
    "with_calls": "Names the library renamed, which obelize reads and calls the old way.",
    "references": "Names the library renamed, which obelize reads and never calls.",
    "exports": "Names the library moved out of a submodule into its package.",
    "flagged": "Names that need a person: obelize reports them and writes nothing.",
    "patterns": "Calls a migration guide says to write another way, written the old way.",
    "new": "Code on the new release already, which the pack must leave alone.",
}
_RENAME_CITATION: Final = {
    "with_calls": "a name the library's deprecation message replaces, with the arguments it took",
    "references": "a name the library's deprecation message replaces, with other arguments",
    "exports": "a name that left a submodule for the package above it",
}
_NOTE: Final = "The dependency declaration the migration has to move with the code."
_HEADER: Final = """# Made by `obelize pack synth` from the public API of {name} {old} and {new}.
# A pack is data: edit it, then run `obelize pack test` on this folder to check it.
"""


def _requirements(line: str, note: str) -> str:
    return f"# {note}\n{line}\nrequests>=2.31\n"


def _program(doc: str, uses: Sequence[tuple[str, str]]) -> str:
    """A module of `(module, line)` uses, each module imported, in one function; or, with no use,
    a module that holds code of some other library."""
    if not uses:
        return f'"""{doc}"""\n\nimport json\n\n\ndef dump(value):\n    return json.dumps(value)\n'
    head = "\n".join(f"import {name}" for name in sorted({module for module, _ in uses}))
    body = "\n".join(f"    {line}" for _, line in uses)
    return f'"""{doc}"""\n\n{head}\n\n\ndef uses():\n{body}\n'


def _names(change: Mapping[str, Any]) -> list[str]:
    params = change["params"]
    if change["kind"] == "manifest_dependency":
        return [params["to_name"]]
    if change["kind"] == "rewrite_pattern":
        return [params["before"]]
    return sorted(params.get("symbols") or params.get("renamed") or params.get("members") or ())


def _fold(
    request: Request, category: str, groups: Mapping[tuple[str, str], list[str]]
) -> list[tuple[tuple[str, str], list[str]]]:
    """The groups of a kind, biggest first, and those past the limit as one that says less."""
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    if len(ordered) <= MAX_GROUPS:
        return ordered
    rest = [path for _, paths in ordered[MAX_GROUPS - 1 :] for path in paths]
    generic = (_GENERIC[category].format(label=request.label), _SUGGESTED[category])
    return [*ordered[: MAX_GROUPS - 1], (generic, rest)]


__all__ = ["Made", "Request", "SynthDefectError", "SynthError", "make", "pack_id", "request"]
