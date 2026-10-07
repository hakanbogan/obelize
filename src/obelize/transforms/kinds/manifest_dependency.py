"""`manifest_dependency`: the legacy distribution's manifest declaration; never touches Python.

Writes the pin edits as `scan/manifests.py` graded them repository-wide, one edit per row: a
legacy row is replaced in place; a new-distribution row is inserted below the legacy line, which
stays because something still imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from packaging.utils import canonicalize_name

from obelize.models import BailCode, Edit
from obelize.scan.manifests import SHAPE_BAIL
from obelize.transforms.base import BailError

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, ManifestDependencyChange
    from obelize.scan.manifests import Declaration
    from obelize.transforms.manifest import ManifestContext

# The one bail this rule raises; the corpus grades the set.
SHAPE: Final[BailCode] = SHAPE_BAIL
BAILS: frozenset[BailCode] = frozenset({SHAPE})

# An `=` before the declaration means the line also names its field (`install_requires = acme==1`),
# which a copy would declare twice. A declaration's own `=` never precedes it.
_KEY: Final = "="


class ManifestDependency:
    kind: ClassVar[ChangeKind] = "manifest_dependency"

    def __init__(self, change: ManifestDependencyChange) -> None:
        self._id = change.id
        self._legacy = canonicalize_name(change.params.from_name)
        self._new = canonicalize_name(change.params.to_name)
        # The pack's spelling: PEP 503 folding is for comparison, not for a file people read.
        self._written = change.params.to_name
        self._spec = change.params.to_spec

    def claims(self, finding: Finding) -> bool:
        """Every manifest row about either side of this rule's migration."""
        return finding.kind == "manifest" and _named(finding) in {self._legacy, self._new}

    def apply(self, context: ManifestContext) -> tuple[Edit, ...]:
        """One edit per claimed row, in reader order; a `not_a_usage` row is context, not edited."""
        return tuple(
            self._edit(context, finding)
            for finding in context.findings
            if self.claims(finding) and finding.scan_status != "not_a_usage"
        )

    def _edit(self, context: ManifestContext, finding: Finding) -> Edit:
        if finding.scan_status != "eligible":
            # Withheld by the scan for a repository-wide reason; report its code, not a second one.
            return Edit(
                path=context.path,
                line=finding.line,
                status="needs_review",
                rule_id=self._id,
                reason=finding.bail,
            )
        try:
            self._write(context, finding)
        except BailError as bail:
            return Edit(
                path=context.path,
                line=finding.line,
                status="needs_review",
                rule_id=self._id,
                reason=bail.reason,
            )
        return Edit(path=context.path, line=finding.line, status="auto", rule_id=self._id)

    def _write(self, context: ManifestContext, finding: Finding) -> None:
        """Record the replacement or the insertion one eligible row asks for.

        A declaration without a plain pin (extras, a direct URL, a non-version table value) is
        refused: none of those survives a change of distribution.
        """
        declaration = context.declaration(finding)
        if declaration is None or declaration.pin is None:
            raise BailError(SHAPE)
        line = context.line(declaration.line)
        if _named(finding) == self._legacy:
            context.rewrites.splice(declaration.line, *declaration.pin, self._spec)
            context.rewrites.splice(
                declaration.line, declaration.column, declaration.end, self._written
            )
            return
        self._check_the_line_carries_nothing_a_copy_would_duplicate(context, declaration, line)
        context.rewrites.after(declaration.line, self._swapped(declaration, declaration.pin, line))

    def _check_the_line_carries_nothing_a_copy_would_duplicate(
        self, context: ManifestContext, declaration: Declaration, line: str
    ) -> None:
        if _KEY in line[: declaration.column]:
            raise BailError(SHAPE)
        beside = [
            other
            for other in context.declarations
            if other.line == declaration.line and other.column != declaration.column
        ]
        if beside:
            raise BailError(SHAPE)

    def _swapped(self, declaration: Declaration, pin: tuple[int, int], line: str) -> str:
        """`line` with only the name and pin spans swapped; indent, quotes and comment stay."""
        return (
            line[: declaration.column]
            + self._written
            + line[declaration.end : pin[0]]
            + self._spec
            + line[pin[1] :]
        )


def _named(finding: Finding) -> str:
    """The distribution a manifest row is about, folded under PEP 503 (a manifest row has one)."""
    return canonicalize_name(finding.symbol or "")


__all__ = ["BAILS", "SHAPE", "ManifestDependency"]
