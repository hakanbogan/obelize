"""The packages under `src/obelize/` form a line, with one cycle written down.

A top-level module counts as a package of its own. Every import counts, those under
`TYPE_CHECKING` and inside a function too, since they are still a dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "obelize"

# `scan/reach.py` and `scan/runner.py` call `impact/planner.py`, which reads `scan/analysis.py` and
# `scan/parse.py`. The modules themselves are acyclic; only the two packages are not.
KNOWN = {frozenset({"impact", "scan"})}


def packages() -> set[str]:
    return {path.stem if path.is_file() else path.name for path in SRC.iterdir()} - {"__pycache__"}


def edges() -> dict[str, set[str]]:
    known = packages()
    found: dict[str, set[str]] = {name: set() for name in known}
    for path in SRC.rglob("*.py"):
        package = path.relative_to(SRC).parts[0].removesuffix(".py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                parts = node.module.split(".")
                if parts[0] == "obelize":
                    named = parts[1:2] or [alias.name for alias in node.names]
                    found[package] |= known.intersection(named)
            elif isinstance(node, ast.Import):
                found[package] |= known.intersection(
                    alias.name.split(".")[1] for alias in node.names if "." in alias.name
                )
    for package, imported in found.items():
        imported.discard(package)
    return found


def cycles() -> set[frozenset[str]]:
    """The groups of packages that each reach every other of the group."""
    graph = edges()
    reach = {name: set(targets) for name, targets in graph.items()}
    for _ in graph:
        for name in reach:
            reach[name] |= {far for near in reach[name] for far in reach[near]}
    return {
        frozenset({name, *(other for other in reach[name] if name in reach[other])})
        for name in graph
        if name in reach[name]
    }


def test_the_packages_form_a_line_but_for_the_cycle_written_down() -> None:
    assert cycles() == KNOWN, "a cycle appeared, or the known one is gone: update KNOWN"
