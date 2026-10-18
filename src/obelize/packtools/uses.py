"""The names of one library that a repository's code uses, read without importing anything.

Only `import` statements and the attribute chains that start at what they bind are read, so a name
reached any other way (an object's attribute, a string) is not found. It is the repository's share
of a large library's changes, not proof of what the repository does not use.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from obelize.models import Config
from obelize.scan import walker

if TYPE_CHECKING:
    from pathlib import Path

# A file larger than this is not read: it is generated, or data.
FILE_BYTES: Final = 2 << 20


def names(root: Path, module: str) -> frozenset[str] | None:
    """The paths below `module`, as `Client.ping` for `module.Client.ping`, that code under `root`
    reaches through its imports; `None` when a star import means any name may be used."""
    found: set[str] = set()
    for name in walker.walk(root, Config()).files:
        try:
            data = (root / name).read_bytes()
            tree = ast.parse(data) if len(data) <= FILE_BYTES else None
        except (OSError, SyntaxError, ValueError, RecursionError):
            continue
        if tree is None:
            continue
        used = _used(tree, module)
        if used is None:
            return None
        found |= used
    return frozenset(found)


def _used(tree: ast.Module, module: str) -> set[str] | None:
    bound: dict[str, str] = {}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(_below(alias.name, module) or "")
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    first = alias.name.partition(".")[0]
                    bound[first] = first
                    bound[alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                if alias.name == "*":
                    if _below(node.module, module) is not None:
                        return None
                else:
                    bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                    found.add(_below(f"{node.module}.{alias.name}", module) or "")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name | ast.Attribute):
            path = _path(node)
            head = next((one for one in _heads(path) if one in bound), None)
            if head is not None:
                relative = _below(f"{bound[head]}{path[len(head) :]}", module)
                if relative:
                    found.add(relative)
    found.discard("")
    return found


def _path(node: ast.expr) -> str:
    """`a.b.c` for the chain `a.b.c`; empty for one that starts at anything but a name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else ""


def _heads(path: str) -> list[str]:
    """The prefixes of a dotted path, longest first."""
    parts = path.split(".") if path else []
    return [".".join(parts[:end]) for end in range(len(parts), 0, -1)]


def _below(path: str, module: str) -> str | None:
    """`path` relative to `module`, `""` for the module itself, or `None` if it is elsewhere."""
    if path == module:
        return ""
    return path.removeprefix(f"{module}.") if path.startswith(f"{module}.") else None


__all__ = ["names"]
