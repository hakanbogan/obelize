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
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from obelize.apidiff.diff import successors
from obelize.models.fields import DISPLAY_TEXT_LIMIT, printable
from obelize.packs import loader
from obelize.packs.schema import under_any
from obelize.packtools import check

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from packaging.version import Version

    from obelize import libdiff
    from obelize.apidiff.diff import ApiChange
    from obelize.apidiff.surface import Obj, Surface

# More groups of one kind than this are folded into one that says less.
MAX_GROUPS: Final = 60
# Beside the pack: for a removed name, the new names it may have become, for a model to read.
HINTS: Final = "hints.json"
HINTS_LIMIT: Final = 1 << 20
_QUOTE_CHARS: Final = 240
_LISTED: Final = 20
_GENERIC: Final = {
    "removed": "Removed in {label}.",
    "moved": "Moved in {label}.",
    "signature": "Its signature changed in {label}.",
    "deprecated": "Deprecated in {label}.",
}
_SUGGESTED: Final = {
    "removed": "Find what replaces it in the release notes.",
    "moved": "Use its new place.",
    "signature": "Read the new signature.",
    "deprecated": "Replace it before it is removed.",
}
_LIMITATIONS: Final = (
    "Made from the public API of two releases: a change in what a function does, not in what it "
    "is called or takes, is not here. Only the tests of the repository show it.",
    "Names built at import time, exported through __getattr__ or implemented in compiled code "
    "are not seen, so they are neither renamed nor flagged.",
    "A method called on an object whose class obelize cannot tell is not found; names reached "
    "through the module are.",
)
_CLASS_NOTE: Final = (
    "A name under a class whose parameters changed is reported as that class, and a class flagged "
    "only for its bases or its kind is left to the members flagged under it."
)


class SynthError(ValueError):
    """Why a pack could not be made, in words for the person who asked."""


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

    @property
    def pack_id(self) -> str:
        return pack_id(self.distribution, self.old, self.new)

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


@dataclass(frozen=True, slots=True)
class _Flag:
    category: str
    message: str
    suggestion: str
    # Whether a parameter of it changed, which no message about its members says.
    params: bool = False


def pack_id(distribution: str, old: Version, new: Version) -> str:
    """`<distribution>/<old>-to-<new>`, in the characters a pack id may have."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{old}-to-{new}".lower()).strip("-")
    return f"{canonicalize_name(distribution)}/{slug}"


def make(
    directory: Path,
    request: Request,
    old: Surface,
    changes: Sequence[ApiChange],
    new: Surface | None = None,
) -> Made:
    """Make `<directory>/<provider>/<slug>/`, load it and check it; a folder that exists is never
    written into, and one that does not pass `pack test` is removed. With the newer surface, the
    names a removed one may have become are written beside the pack (`HINTS`)."""
    folder = directory / request.pack_id
    if folder.exists():
        raise SynthError(
            f"{folder} exists already; pack synth makes a folder and never writes into one."
        )
    plan = _Plan.build(request, old, changes)
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
    try:
        for name, text in plan.files().items():
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
    for path, one in plan.flags.items():
        names = successors(old, new, path) if one.category == "removed" and path else []
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


def request(distribution: str, old: Version, new: Version, compared: libdiff.Comparison) -> Request:
    """The request for two releases that were compared: the newer file is what the pack cites."""
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
        retrieved=dt.datetime.now(dt.UTC).date(),
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


def _leaf(path: str) -> str:
    return path.rpartition(".")[2]


def _parent(path: str) -> str:
    return path.rpartition(".")[0]


def _at_module(path: str, olds: Mapping[str, Obj]) -> bool:
    """Whether `path` is a name of a module, and not a member of a class."""
    parent = _parent(path)
    return not parent or (parent in olds and olds[parent].kind == "module")


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
            return f"Parameter {param} was removed in {label}."
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


def _merge(entries: Sequence[tuple[str, str, str, bool]]) -> _Flag:
    """One name's reasons as one flag: the first's category and advice, every message in order."""
    category, _, suggestion, _ = entries[0]
    seen: list[str] = []
    for _, message, _, _ in entries:
        if message not in seen:
            seen.append(message)
    params = any(params for *_, params in entries)
    return _Flag(category, _text(" ".join(seen)), suggestion, params)


def _outermost(flags: Mapping[str, _Flag]) -> tuple[dict[str, _Flag], tuple[str, ...]]:
    """The flagged names no other flagged name contains, and the ones left out.

    Two changes may not flag one surface, so a class and its members cannot both be. A class whose
    parameters changed stands for its members; one flagged for anything else (its bases, its kind,
    a notice) gives way to the members flagged under it, whose words say more.
    """
    yielding = {
        path
        for path, one in flags.items()
        if one.category in ("signature", "deprecated")
        and not one.params
        and any(other.startswith(f"{path}.") for other in flags)
    }
    kept: dict[str, _Flag] = {}
    dropped: list[str] = sorted(yielding)
    for path in sorted(set(flags) - yielding):
        if any(path.startswith(f"{outer}.") for outer in kept):
            dropped.append(path)
        else:
            kept[path] = flags[path]
    return kept, tuple(dropped)


def _args(obj: Obj) -> str:
    """Arguments a call may be written with: a zero for each parameter that is required."""
    given = []
    for param in obj.params or ():
        if param.required and param.kind == "keyword-only":
            given.append(f"{param.name}=0")
        elif param.required and param.kind != "variadic keyword":
            given.append("0")
    return ", ".join(given)


@dataclass(frozen=True, slots=True)
class _Plan:
    """What the pack says, before it is written, each part derived from the changes."""

    request: Request
    # Renamed in place (old path -> new path), with and without the claim that calls carry.
    with_calls: Mapping[str, str]
    references: Mapping[str, str]
    # Taken out of a submodule (old path -> new path, in the package above it).
    exports: Mapping[str, str]
    flags: Mapping[str, _Flag]
    dropped: tuple[str, ...]
    olds: Mapping[str, Obj]
    unseen: int

    @property
    def symbols(self) -> tuple[str, ...]:
        """What the scan looks for: the names, and the submodules the exports leave, whose
        imports are rewritten with them."""
        names = {*self.with_calls, *self.references, *self.exports, *self.flags}
        names |= {_parent(path) for path in self.exports}
        return tuple(sorted(f"{self.request.module}.{name}" for name in names))

    @classmethod
    def build(cls, request: Request, old: Surface, changes: Sequence[ApiChange]) -> _Plan:
        olds = old.relative()
        label = request.label
        with_calls: dict[str, str] = {}
        references: dict[str, str] = {}
        exports: dict[str, str] = {}
        parts: dict[str, list[tuple[str, str, str, bool]]] = {}

        def flag(
            path: str, category: str, message: str, suggestion: str, *, params: bool = False
        ) -> None:
            parts.setdefault(path, []).append((category, message, suggestion, params))

        for change in changes:
            path, target = change.path, change.new_path
            if change.type == "unseen":
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
                flag(path, "deprecated", f"Deprecated in {label}.{said}", _SUGGESTED["deprecated"])
            else:
                changed = change.type.startswith("param_") or change.type == "default_changed"
                text = _signature_text(label, change)
                flag(path, "signature", text, _SUGGESTED["signature"], params=changed)
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
        kept, dropped = _outermost(flags)
        unseen = sum(1 for change in changes if change.type == "unseen")
        return cls(request, with_calls, references, exports, kept, dropped, olds, unseen)

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
        return found

    def changes(self) -> list[dict[str, Any]]:
        request = self.request
        out: list[dict[str, Any]] = []
        for name, calls, table, label in (
            ("rename-with-calls", "allowed", self.with_calls, "with_calls"),
            ("rename-references", "refused", self.references, "references"),
            ("move-up", "allowed", self.exports, "exports"),
        ):
            if not table:
                continue
            key = "symbols" if label == "exports" else "renamed"
            out.append(
                {
                    "id": name,
                    "kind": "rename_symbol",
                    "citation": _text(
                        f"{request.distribution} {request.old} and {request.new}, public API: "
                        f"{_RENAME_CITATION[label]}"
                    ),
                    "params": {
                        "calls": calls,
                        key: {
                            f"{request.module}.{path}": _leaf(landed)
                            for path, landed in sorted(table.items())
                        },
                    },
                    "fixtures": [
                        "fixtures/negative/already_new.py",
                        f"fixtures/positive/{_FIXTURES[label]}",
                    ],
                }
            )
        grouped: dict[str, dict[tuple[str, str], list[str]]] = {}
        for path, flag in self.flags.items():
            grouped.setdefault(flag.category, {}).setdefault(
                (flag.message, flag.suggestion), []
            ).append(path)
        for category in _GENERIC:
            groups = _fold(request, category, grouped.get(category, {}))
            for number, ((message, suggestion), paths) in enumerate(groups, 1):
                out.append(
                    {
                        "id": f"{category}-{number}",
                        "kind": "flag_only",
                        "citation": _text(
                            f"{request.distribution} {request.old} and {request.new}, public API"
                        ),
                        "params": {
                            "message": message,
                            "suggestion": suggestion,
                            "symbols": sorted(f"{request.module}.{path}" for path in paths),
                        },
                        "fixtures": [
                            "fixtures/negative/already_new.py",
                            "fixtures/positive/flagged.before.py",
                        ],
                    }
                )
        out.append(
            {
                "id": "dependency-line",
                "kind": "manifest_dependency",
                "citation": _text(f"{request.distribution} {request.new} on the index"),
                "params": {
                    "from_name": request.distribution,
                    "to_name": request.distribution,
                    "to_spec": request.target,
                },
                "fixtures": [
                    "fixtures/negative/requirements_already_new.txt",
                    "fixtures/positive/requirements.before.txt",
                ],
            }
        )
        return out

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
                uses = [
                    self._use(path, label != "references", n)
                    for n, path in enumerate(sorted(table))
                ]
                found[f"fixtures/positive/{_FIXTURES[label]}"] = _program(_DOCS[label], uses)
        if self.flags:
            uses = [self._use(path, True, n) for n, path in enumerate(sorted(self.flags))]
            found["fixtures/positive/flagged.before.py"] = _program(_DOCS["flagged"], uses)
        landed = sorted(
            {*self.with_calls.values(), *self.references.values(), *self.exports.values()}
        )
        kept = [self._read(path) for path in landed]
        found["fixtures/negative/already_new.py"] = _program(_DOCS["new"], kept)
        found["fixtures/positive/requirements.before.txt"] = _requirements(
            f"{request.distribution}=={request.old}", _NOTE
        )
        found["fixtures/negative/requirements_already_new.txt"] = _requirements(
            f"{request.distribution}{request.target}", "Already migrated, and the rule adds no pin."
        )
        return found

    def _home(self, path: str) -> str:
        """The module a name is imported from: the nearest one above it, or the package."""
        parent = _parent(path)
        while parent and (parent not in self.olds or self.olds[parent].kind != "module"):
            parent = _parent(parent)
        return f"{self.request.module}.{parent}" if parent else self.request.module

    def _use(self, path: str, call: bool, number: int) -> tuple[str, str]:
        """A line that uses a name of the old release, and the module it needs imported."""
        obj, dotted = self.olds[path], f"{self.request.module}.{path}"
        if call and obj.kind in ("function", "class"):
            return self._home(path), f"{dotted}({_args(obj)})"
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
            "limitations": [*_LIMITATIONS, *([_CLASS_NOTE] if self.dropped else [])],
        }
        body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=100)
        header = _HEADER.format(name=request.distribution, old=request.old, new=request.new)
        return header + body

    def _sources(self) -> str:
        request = self.request
        sections = []
        for change in self.changes():
            names = _names(change)
            shown = ", ".join(f"`{name}`" for name in names[:_LISTED])
            more = f", and {len(names) - _LISTED} more" if len(names) > _LISTED else ""
            sections.append(
                f"## {change['id']}\n\n{change['citation']}.\n\nNames: {shown}{more}.\n"
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
_DOCS: Final = {
    "with_calls": "Names the library renamed, which obelize reads and calls the old way.",
    "references": "Names the library renamed, which obelize reads and never calls.",
    "exports": "Names the library moved out of a submodule into its package.",
    "flagged": "Names that need a person: obelize reports them and writes nothing.",
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
    return sorted(params.get("symbols") or params.get("renamed") or ())


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
