"""Withhold an eligible group another module reaches (`model_object_read_elsewhere`).

Deleting the constructor breaks a module that imports the model (`from llm import MODEL`) or reads
it off an instance (`desk.model`); no per-file pass sees that. Only imports and attribute reads
count, never text. A module matches by its last dotted segment, so another package's `llm` also
withholds (the safe side). The code lands only on rows no other code fired on, so it has no rung.
"""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from obelize import fsutil
from obelize.impact import dataflow, planner
from obelize.models import ATOMICITY_BAIL, Binding, Finding, ImpactPlan

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence
    from pathlib import Path

    from obelize.models import BailCode, BindingKind, ImpactPolicy
    from obelize.scan.runner import FileResult

CODE: BailCode = "model_object_read_elsewhere"
BAILS: frozenset[BailCode] = frozenset({CODE})

# A `name` is a function local; a `class_attr` is withheld whatever reads it.
REACHABLE: frozenset[BindingKind] = frozenset({"module_const", "self_attr"})

_STAR = re.compile(rb"import\s+\*")


def revised(
    root: Path, paths: Sequence[str], files: Sequence[FileResult], policy: ImpactPolicy
) -> tuple[FileResult, ...]:
    """`files`, with every eligible group another selected module reaches withheld."""
    wanted = {result.path: [row for row in result.plan.bindings if _open(row)] for result in files}
    names = {_attribute(row) for rows in wanted.values() for row in rows}
    if not names:
        return tuple(files)
    trees = _trees(root, [path for path in paths if path.endswith(".py")], names)
    revision = []
    for result in files:
        reached = [
            row
            for row in wanted[result.path]
            if any(_reaches(tree, _segment(result.path), row) for tree in trees.values())
        ]
        revision.append(
            replace(result, plan=_withheld(result, reached, policy)) if reached else result
        )
    return tuple(revision)


def _open(row: Binding) -> bool:
    return row.scan_status == "eligible" and row.kind in REACHABLE


def _attribute(row: Binding) -> str:
    """The name another module reads: `MODEL`, or the `model` of `self.model`."""
    return row.name.rpartition(".")[2]


def _segment(path: str) -> str:
    """The last dotted segment of the module `path` is: `llm`, or `pkg` for its `__init__`."""
    module = PurePosixPath(path)
    return module.parent.name if module.name == "__init__.py" else module.stem


def _trees(root: Path, paths: Sequence[str], names: set[str]) -> dict[str, ast.Module]:
    """Parse only modules whose bytes hold one of `names` or a star import (which spells none)."""
    trees = {}
    for path in paths:
        try:
            data = fsutil.read(root / path)
        except OSError:
            continue
        if not (_STAR.search(data) or any(name.encode() in data for name in names)):
            continue
        try:
            trees[path] = ast.parse(data)
        except (SyntaxError, ValueError):
            continue
    return trees


def _reaches(tree: ast.Module, segment: str, row: Binding) -> bool:
    """Whether `tree` reaches `row` of module `segment`.

    A constant: imported by name or `*`, or its module imported and the attribute read. An
    instance attribute: anything imported from the module and that attribute read off anything.
    """
    name = _attribute(row)
    imported = module = read = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").rpartition(".")[2] == segment:
                module = True
                imported = imported or any(alias.name in (name, "*") for alias in node.names)
            module = module or any(alias.name == segment for alias in node.names)
        elif isinstance(node, ast.Import):
            module = module or any(alias.name.rpartition(".")[2] == segment for alias in node.names)
        elif isinstance(node, ast.Attribute) and node.attr == name:
            read = True
    if row.kind == "module_const":
        return imported or (module and read)
    return module and read


def _withheld(result: FileResult, reached: Sequence[Binding], policy: ImpactPolicy) -> ImpactPlan:
    """The plan with reached groups withheld, its atomicity undone and asked again.

    Undone first because its recorded causes would be one short; after that every row a reached
    group holds is `eligible`, since only atomicity had withheld any of them.
    """
    groups = [
        dataflow.Group(
            receiver=receiver,
            bail=CODE,
            lines=tuple(sorted({receiver.ctor_line, *receiver.use_lines})),
        )
        for receiver in result.receivers
        if any(
            (row.kind, row.name, row.scope, row.ctor_line)
            == (receiver.kind, receiver.name, receiver.scope, receiver.ctor_line)
            for row in reached
        )
    ]
    findings = []
    for finding in result.plan.findings:
        row = finding
        if row.bail == ATOMICITY_BAIL:
            row = Finding(
                **{**row.model_dump(), "scan_status": "eligible", "bail": None, "caused_by": None}
            )
        if any(group.holds(row) for group in groups):
            row = Finding(**{**row.model_dump(), "scan_status": "needs_review", "bail": CODE})
        findings.append(row)
    return ImpactPlan(
        path=result.plan.path,
        findings=planner.atomicity(findings, policy),
        bindings=tuple(
            Binding(**{**row.model_dump(), "scan_status": "needs_review", "bail": CODE})
            if row in reached
            else row
            for row in result.plan.bindings
        ),
        import_policy=result.plan.import_policy,
    )


__all__ = ["BAILS", "CODE", "REACHABLE", "revised"]
