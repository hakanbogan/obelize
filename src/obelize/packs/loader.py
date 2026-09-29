"""The only place a pack is read: its bytes, their hash, validation, and the scanner's projection.

`sha256` hashes the bytes as on disk, before parsing, since the run folder copies them verbatim.
Loading never fetches `source.url` (a test blocks sockets). `scan/*` and `impact/*` never import
`packs.schema`; `to_scan_spec` is their only view. Exit codes: not found 2, rejected 7, and a
bundled pack that fails validation 1 (an obelize defect), hence `PackInvalidError.bundled`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from obelize import _yaml
from obelize.models import FlagOnlyPattern, MethodReturn, ProvidedModule, ReceiverMethods, ScanSpec
from obelize.packs.schema import (
    _PACK_ID,
    CHANGE_KINDS,
    ConfigureToClientChange,
    FlagOnlyChange,
    GenerativeModelCallsChange,
    PackDocument,
)

# Bundled packs ship in the wheel at `<provider>/<slug>/pack.yaml` here: the id is the directory.
BUNDLED: Final[Path] = Path(__file__).resolve().parent
PACK_FILENAME: Final = "pack.yaml"
SOURCES_FILENAME: Final = "SOURCES.md"


class PackError(Exception):
    """Base for the two ways a `--pack` value fails to produce a pack."""


class PackNotFoundError(PackError):
    """No pack at that reference: a usage error."""


class PackInvalidError(PackError):
    """A pack that was read and cannot be used; `problems` names each defect's YAML path."""

    def __init__(self, reference: str, problems: list[str], *, bundled: bool) -> None:
        super().__init__(
            "\n".join(
                [f"{reference} is not a valid pack:", *(f"  - {problem}" for problem in problems)]
            )
        )
        self.reference = reference
        self.problems = problems
        self.bundled = bundled


@dataclass(frozen=True, slots=True)
class LoadedPack:
    """A validated pack. `path` is for tests only: an absolute path never reaches a run folder."""

    pack: PackDocument
    sha256: str
    data: bytes
    reference: str
    bundled: bool
    path: Path


def bundled_ids(root: Path | None = None) -> tuple[str, ...]:
    """Every pack that ships inside the wheel, sorted."""
    base = BUNDLED if root is None else root
    found = [
        f"{candidate.parent.parent.name}/{candidate.parent.name}"
        for candidate in sorted(base.glob(f"*/*/{PACK_FILENAME}"))
    ]
    return tuple(identifier for identifier in found if _PACK_ID.fullmatch(identifier))


def resolve(reference: str, root: Path | None = None) -> tuple[Path, bool]:
    """Turn a `--pack` value into a file, and whether it is bundled.

    A bundled id wins over a same-spelled path; `_PACK_ID` admits no dot, so the join stays inside
    the packs directory. Anything else, including an id with no bundled pack, is tried as a path.
    """
    base = BUNDLED if root is None else root
    if _PACK_ID.fullmatch(reference):
        provider, slug = reference.split("/", 1)
        candidate = base / provider / slug / PACK_FILENAME
        if candidate.is_file():
            return candidate, True
    return Path(reference), False


def load(reference: str, root: Path | None = None) -> LoadedPack:
    """Read and validate the pack `reference` names."""
    path, bundled = resolve(reference, root)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise PackNotFoundError(
            f"no pack at {reference!r}: {error.strerror}. Pass a bundled pack id "
            f"({', '.join(bundled_ids(root)) or 'none are bundled'}) or a path to a pack file."
        ) from error
    digest = hashlib.sha256(data).hexdigest()
    document = _document(reference, data, bundled=bundled)
    try:
        pack = PackDocument.model_validate(document)
    except ValidationError as error:
        raise PackInvalidError(reference, problems(error), bundled=bundled) from error
    return LoadedPack(
        pack=pack,
        sha256=digest,
        data=data,
        reference=reference,
        bundled=bundled,
        path=path,
    )


def _document(reference: str, data: bytes, *, bundled: bool) -> dict[str, Any]:
    """The bytes as a mapping, or one `PackInvalidError` saying why they are not."""

    def refuse(problem: str) -> PackInvalidError:
        return PackInvalidError(reference, [problem], bundled=bundled)

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise refuse(f"not UTF-8: {error.reason} at byte {error.start}") from error
    try:
        parsed = _yaml.parse(text)
    except _yaml.DuplicateKeyError as error:
        raise refuse(
            f"line {error.line}: {error}. YAML keeps the last one and discards the first."
        ) from error
    except yaml.YAMLError as error:
        located = _yaml.where(error)
        if located is None:
            raise refuse(f"not valid YAML: {' '.join(str(error).split())}") from error
        line, column, problem = located
        raise refuse(f"line {line}, column {column}: {problem}") from error
    if parsed is None:
        raise refuse("the file is empty")
    if not isinstance(parsed, dict):
        raise refuse(
            f"a pack is a mapping at the top level, and this one is a {type(parsed).__name__}"
        )
    return parsed


def problems(error: ValidationError) -> list[str]:
    """A pydantic report as the YAML paths a pack author wrote.

    Drops the union tag and the `[key]` segment pydantic inserts, neither of which is in the file,
    and renders a list index as `[0]` so `changes.0.id` does not read as a key named `0`.
    """
    lines: list[str] = []
    for item in error.errors():
        path = ""
        for part in item["loc"]:
            if isinstance(part, int):
                path += f"[{part}]"
            elif part in CHANGE_KINDS or part == "[key]":
                continue
            else:
                path = f"{path}.{part}" if path else str(part)
        message = item["msg"].removeprefix("Value error, ")
        lines.append(f"{path}: {message}" if path else message)
    return lines


def to_scan_spec(loaded: LoadedPack) -> ScanSpec:
    """The scan's view of a pack; rewrite-only data stays out, so it cannot move `spec_digest`."""
    pack = loaded.pack
    constructors: set[str] = set()
    methods: dict[str, tuple[str, ...]] = {}
    returns: dict[str, str] = {}
    attributes: set[str] = set()
    flagged: set[str] = set()
    patterns: set[FlagOnlyPattern] = set()
    client_symbol = ""
    for change in pack.changes:
        if isinstance(change, ConfigureToClientChange):
            client_symbol = change.params.legacy_symbol
        elif isinstance(change, GenerativeModelCallsChange):
            constructors.add(change.params.ctor_symbol)
            methods.update(change.params.methods)
            returns.update(change.params.method_returns)
        elif isinstance(change, FlagOnlyChange):
            attributes.update(change.params.attributes)
            flagged.update(change.params.symbols)
            patterns.update(change.params.patterns)
    return ScanSpec(
        pack_id=pack.id,
        pack_version=pack.pack_version,
        pack_sha256=loaded.sha256,
        legacy_modules=pack.match.imports,
        legacy_distribution=pack.from_.package,
        new_distribution=pack.to.package,
        prefilter_tokens=pack.match.prefilter_tokens,
        symbols=pack.match.symbols,
        client_symbol=client_symbol,
        constructor_symbols=tuple(sorted(constructors)),
        supported_methods=tuple(
            ReceiverMethods(receiver=receiver, methods=methods[receiver])
            for receiver in sorted(methods)
        ),
        method_returns=tuple(
            MethodReturn(method=method, receiver=returns[method]) for method in sorted(returns)
        ),
        removed_attributes=tuple(sorted(attributes)),
        flag_only_symbols=tuple(sorted(flagged)),
        flag_only_patterns=tuple(sorted(patterns)),
        transitive_modules=tuple(
            ProvidedModule(module=module, distribution=distribution)
            for module, distribution in sorted(pack.match.transitive.items())
        ),
    )


# Fields that name the pack rather than describe the scan; `spec_digest` leaves them out.
_IDENTITY: Final[frozenset[str]] = frozenset({"pack_id", "pack_version", "pack_sha256"})


def spec_digest(spec: ScanSpec) -> str:
    """Hash of the scan's view minus pack identity: two packs with one digest agree on findings."""
    payload = {
        key: value for key, value in spec.model_dump(mode="json").items() if key not in _IDENTITY
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


__all__ = [
    "BUNDLED",
    "PACK_FILENAME",
    "SOURCES_FILENAME",
    "LoadedPack",
    "PackError",
    "PackInvalidError",
    "PackNotFoundError",
    "bundled_ids",
    "load",
    "problems",
    "resolve",
    "spec_digest",
    "to_scan_spec",
]
