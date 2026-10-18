"""A library with no pack, listed: the modules it installs and the scan spec that finds its uses.

An inventory is a scan whose every place is withheld with `no_pack_for_usage`. It names no
rewrite, so nothing here reads a pack; it reads an environment kept in the repository, by name
only, and imports nothing from it.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from packaging.utils import canonicalize_name

from obelize.models import QUALIFIED_NAME, ScanSpec
from obelize.scan import installed

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from obelize.scan.runner import Tree

# Files of a distribution that are no module: its metadata, bytecode and scripts.
_NOT_MODULES: Final = ("__pycache__",)

# The first name an absolute `import` or `from` statement imports, at the start of a line.
_FROM: Final = re.compile(rb"^[ \t]*from[ \t]+([A-Za-z_]\w*)", re.MULTILINE)
_IMPORT: Final = re.compile(
    rb"^[ \t]*import[ \t]+([A-Za-z_][\w.]*(?:[ \t]*,[ \t]*[A-Za-z_][\w.]*)*)", re.MULTILINE
)


def spec(distribution: str, modules: Sequence[str]) -> ScanSpec:
    """The scan spec of an inventory of `distribution`, whose uses are the imports of `modules`.

    The pack id and hash are those of the inventory itself, so two runs over the same library
    and modules agree on them and `run.json` can say what was listed.
    """
    chosen = tuple(sorted(set(modules)))
    named = canonicalize_name(distribution)
    made = {
        "pack_id": f"inventory/{named}",
        "pack_version": "0",
        "legacy_modules": chosen,
        "legacy_distribution": distribution,
        "new_distribution": distribution,
        "prefilter_tokens": tuple(sorted({module.rpartition(".")[2] for module in chosen})),
        "requires_python": "",
        "inventory": True,
    }
    digest = hashlib.sha256(json.dumps(made, sort_keys=True).encode("utf-8")).hexdigest()
    return ScanSpec(pack_sha256=digest, **made)


def modules(root: Path, distribution: str) -> tuple[str, ...]:
    """The modules `distribution` installed in an environment kept in `root`, or `()`.

    Read from the installed `RECORD`, which lists the files, so a namespace package (`google`)
    gives the package under it (`google.generativeai`) and not every library that shares the
    namespace. `top_level.txt` answers for a distribution whose `RECORD` is gone.
    """
    spelled = "[-_.]+".join(re.escape(part) for part in canonicalize_name(distribution).split("-"))
    metadata = re.compile(rf"{spelled}-\d[\w.!+]*\.dist-info", re.IGNORECASE)
    found: set[str] = set()
    for environment in installed.ENVIRONMENTS:
        for packages in installed.site_packages(root / environment):
            for name in installed.names(root / environment / packages):
                if metadata.fullmatch(name):
                    found |= _one(root / environment / packages / name)
    return tuple(sorted(found))


def _one(info: Path) -> set[str]:
    try:
        record = (info / "RECORD").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        record = ""
    paths = [line.rpartition(",,")[0] or line.split(",")[0] for line in record.splitlines()]
    found = _packages(paths)
    if found:
        return found
    try:
        top = (info / "top_level.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {name for name in map(str.strip, top.splitlines()) if _valid(name)}


def _packages(paths: Iterable[str]) -> set[str]:
    """The outermost packages and top-level modules the files of a distribution make."""
    packages = {
        posixpath.dirname(path).replace("/", ".")
        for path in paths
        if posixpath.basename(path) == "__init__.py" and ".." not in path.split("/")
    }
    roots = {name for name in packages if _valid(name) and not _inside(name, packages)}
    singles = {
        posixpath.splitext(path)[0]
        for path in paths
        if "/" not in path and path.endswith(".py") and _valid(posixpath.splitext(path)[0])
    }
    return roots | singles


def _inside(name: str, packages: set[str]) -> bool:
    parent = name.rpartition(".")[0]
    return bool(parent) and (parent in packages or _inside(parent, packages))


def _valid(name: str) -> bool:
    return bool(QUALIFIED_NAME.fullmatch(name)) and not name.startswith(_NOT_MODULES)


def imported(tree: Tree, limit: int = 5) -> tuple[tuple[str, int], ...]:
    """The modules the selected files import most, by the number of files, most first.

    Not the standard library and not the repository's own top-level names, so what is left is
    what a person could ask `scan --library` to list. A statement is read by its first name only;
    this is a pointer to where to look and no inventory.
    """
    own = {PurePosixPath(path).parts[0].removesuffix(".py") for path in tree.walk.files}
    skip = own | set(sys.stdlib_module_names)
    counts: Counter[str] = Counter()
    for path in tree.walk.files:
        data, _ = tree.contents(path)
        if data is None:
            continue
        names = {match.decode() for match in _FROM.findall(data)}
        for statement in _IMPORT.findall(data):
            names |= {part.strip().split(".")[0] for part in statement.decode().split(",")}
        counts.update(names - skip)
    ranked = sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    return tuple(ranked[:limit])


__all__ = ["imported", "modules", "spec"]
