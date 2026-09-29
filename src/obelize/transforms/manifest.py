"""Context and protocol for rules that edit a dependency manifest: unparsed, spans on lines.

Declarations are re-read from the bytes by `scan/manifests.py`, so an edit uses the address the
scan recorded. Lines split on `\\n` only, as that reader does: a CRLF file keeps `\\r` on every
line, an added line inherits it from the line it copies, and an untouched file round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol

from obelize.scan.manifests import declarations

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Edit, Finding, ManifestPlan
    from obelize.packs.schema import ChangeKind
    from obelize.scan.manifests import Declaration

# `surrogateescape`: a non-UTF-8 byte in a user's manifest round-trips instead of stopping the
# run. `scan/manifests.py` decodes the same way.
ENCODING = "utf-8"
ERRORS = "surrogateescape"


class Lines:
    """Every span a rule replaced, and every line it added, by line number."""

    def __init__(self) -> None:
        self._spans: dict[int, list[tuple[int, int, str]]] = {}
        self._after: dict[int, list[str]] = {}

    def splice(self, line: int, start: int, end: int, text: str) -> None:
        """Replace `[start, end)` on `line` with `text`."""
        self._spans.setdefault(line, []).append((start, end, text))

    def after(self, line: int, text: str) -> None:
        """Add `text` as a new line immediately below `line`."""
        self._after.setdefault(line, []).append(text)

    def wrote(self) -> bool:
        return bool(self._spans or self._after)

    def apply(self, lines: list[str]) -> list[str]:
        """`lines` with every recorded change made, in one pass.

        Spans apply right to left so each one's columns stay the reader's; added lines go in
        after, so no line number moves under a pending span.
        """
        out: list[str] = []
        for number, text in enumerate(lines, 1):
            body = text
            for start, end, new in sorted(self._spans.get(number, ()), reverse=True):
                body = body[:start] + new + body[end:]
            out.append(body)
            out.extend(self._after.get(number, ()))
        return out


@dataclass(frozen=True, slots=True)
class ManifestContext:
    """One manifest as a rule sees it; `findings` holds only this file's rows of the plan."""

    path: str
    data: bytes
    lines: tuple[str, ...]
    findings: tuple[Finding, ...]
    declarations: tuple[Declaration, ...]
    rewrites: Lines = field(default_factory=Lines)

    @classmethod
    def build(cls, path: str, data: bytes, plan: ManifestPlan) -> ManifestContext:
        """The only constructor a rule should see."""
        return cls(
            path=path,
            data=data,
            lines=tuple(data.decode(ENCODING, ERRORS).split("\n")),
            findings=tuple(row for row in plan.findings if row.path == path),
            declarations=declarations(path, data),
        )

    def declaration(self, finding: Finding) -> Declaration | None:
        """The declaration at the address a row records, or `None`.

        Unreachable from a scan's plan; returned rather than raised so a rule refuses a foreign
        plan under the code it already has.
        """
        by_address = {(found.line, found.column): found for found in self.declarations}
        return by_address.get((finding.line, finding.column))

    def line(self, number: int) -> str:
        return self.lines[number - 1]


class ManifestRule(Protocol):
    """What `registry.MANIFEST_RULES` maps a manifest `kind` to."""

    kind: ClassVar[ChangeKind]

    def claims(self, finding: Finding) -> bool:
        """Whether this rule would rewrite `finding`."""

    def apply(self, context: ManifestContext) -> tuple[Edit, ...]:
        """Record this rule's changes in `context` and return its edits."""


def finish(context: ManifestContext) -> bytes:
    """The manifest with every recorded change; untouched, the input bytes, never re-encoded."""
    if not context.rewrites.wrote():
        return context.data
    return "\n".join(context.rewrites.apply(list(context.lines))).encode(ENCODING, ERRORS)


__all__ = ["ENCODING", "ERRORS", "Lines", "ManifestContext", "ManifestRule", "finish"]
