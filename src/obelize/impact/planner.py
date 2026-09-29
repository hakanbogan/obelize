"""Grade one file whole: rung 4 (the module's client), rung 6 (atomicity) and the merged ladder.

Exactly one `configure(...)` anywhere in a module, at any scope, is its client.
Atomicity is the last rung because it names no defect of its own. A later pass may only move a
finding to a more specific code, never out of `needs_review`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from obelize.impact import dataflow
from obelize.models import (
    ATOMICITY_BAIL,
    BailCode,
    Binding,
    Finding,
    FindingKind,
    ImpactPlan,
    ImpactPolicy,
    ScanSpec,
)
from obelize.scan import analysis, parse

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

BAILS: frozenset[BailCode] = frozenset(
    {
        "client_source_unresolved",
        "file_not_fully_migrated",
        "multiple_configure_calls",
    }
)

RUNG: Final[dict[BailCode, int]] = {
    "multiple_configure_calls": 4,
    "client_source_unresolved": 4,
    "file_not_fully_migrated": 6,
}

# `input_does_not_parse` is numbered here: that gate collapses a file to one finding, so
# `scan/parse.py` never compares against it.
LADDER: Final[dict[BailCode, int]] = {
    parse.PARSE_BAIL: 2,
    **analysis.RUNG,
    **dataflow.RUNG,
    **RUNG,
}

# Most specific first, rungs 1-6. Within a rung only two orders co-fire: `dataflow.ORDER`, and
# `receiver_unresolved` after the group codes, since the group names a real binding.
ORDER: Final[tuple[BailCode, ...]] = (
    "attribute_removed",
    "flag_only_surface",
    parse.PARSE_BAIL,
    "roundtrip_mismatch",
    "star_import",
    "conditional_binding",
    "module_alias_rebound",
    "local_import",
    "multiple_configure_calls",
    "client_source_unresolved",
    *dataflow.ORDER,
    "receiver_unresolved",
    ATOMICITY_BAIL,
)

_RANK: Final[dict[BailCode, int]] = {code: index for index, code in enumerate(ORDER)}

# Not `text_mention`: a patched `"...configure"` string needs no client. No plan can show this,
# so `needs_client` is public and tested directly.
_CLIENT_KINDS: Final[frozenset[FindingKind]] = frozenset({"call", "method_call", "attribute"})


def configures(finding: Finding, spec: ScanSpec) -> bool:
    """Whether this row is a `configure(...)` call: it counts calls, not a patched-target
    string."""
    return finding.kind == "call" and finding.symbol == spec.client_symbol


def needs_client(finding: Finding, spec: ScanSpec) -> bool:
    """Whether this row's rewrite needs the module's client.

    Only what the new SDK routes through a `Client` does: `configure`, a constructor, a read of a
    pack-declared receiver. A type rename does not, so a file of those needs no `configure`.
    """
    if finding.kind not in _CLIENT_KINDS:
        return False
    symbol = finding.symbol or ""
    if symbol == spec.client_symbol or symbol in spec.constructor_symbols:
        return True
    return bool(spec.methods_for(symbol.rpartition(".")[0]))


def atomicity(findings: Sequence[Finding], policy: ImpactPolicy) -> tuple[Finding, ...]:
    """Once any row bails, withhold every otherwise-eligible row, so the file is left as it was.

    `caused_by` is exactly the bails the findings carry, never the binding table's: a group can
    bail while all its findings are withheld a rung higher. `transforms/codemod.py` writes fix-time
    codes onto their rows and calls this again, so it takes no extra causes.
    """
    if policy.import_policy == "dual":
        return tuple(findings)
    causes = tuple(sorted({row.bail for row in findings if row.bail is not None}))
    if not causes:
        return tuple(findings)
    return tuple(
        Finding(
            **{
                **row.model_dump(),
                "scan_status": "needs_review",
                "bail": ATOMICITY_BAIL,
                "caused_by": causes,
            }
        )
        if row.scan_status == "eligible"
        else row
        for row in findings
    )


def more_specific(codes: Iterable[BailCode | None]) -> BailCode | None:
    """The most specific of the codes that fired, or `None` if none did."""
    fired = [code for code in codes if code is not None]
    if not fired:
        return None
    return min(fired, key=_RANK.__getitem__)


def plan(
    result: analysis.Analysis, spec: ScanSpec, policy: ImpactPolicy | None = None
) -> ImpactPlan:
    """Grade one analysed file: the client rung, the group rung, then atomicity."""
    return _Plan(result, spec, policy or ImpactPolicy()).run()


class _Plan:
    """One file's plan; single use."""

    def __init__(self, result: analysis.Analysis, spec: ScanSpec, policy: ImpactPolicy) -> None:
        self._result = result
        self._spec = spec
        self._policy = policy
        self._groups = dataflow.groups(result)
        self._client = self._client_source()

    def run(self) -> ImpactPlan:
        findings = atomicity(
            [self._graded(finding) for finding in self._result.findings], self._policy
        )
        return ImpactPlan(
            path=self._result.path,
            findings=tuple(findings),
            bindings=tuple(self._binding(group, findings) for group in self._groups),
            import_policy=self._policy.import_policy,
        )

    def _client_source(self) -> BailCode | None:
        """Real `configure` calls only (see `configures`)."""
        calls = [finding for finding in self._result.findings if configures(finding, self._spec)]
        if len(calls) > 1:
            return "multiple_configure_calls"
        if calls:
            return None
        return "client_source_unresolved"

    def _graded(self, finding: Finding) -> Finding:
        """The most specific code that fired on this row, of every rung's."""
        if finding.scan_status == "not_a_usage":
            # A prose mention is no edit, and `Finding` refuses a bail on it.
            return finding
        codes = [finding.bail, *(group.bail for group in self._groups if group.holds(finding))]
        if needs_client(finding, self._spec):
            codes.append(self._client)
        code = more_specific(codes)
        if code == finding.bail:
            return finding
        return Finding(**{**finding.model_dump(), "scan_status": "needs_review", "bail": code})

    def _binding(self, group: dataflow.Group, findings: Sequence[Finding]) -> Binding:
        """The group's own defect, else the most specific non-atomicity code on its rows.

        Atomicity is a file property `Binding` refuses, so a closed-world group in a file withheld
        only by atomicity is `eligible`.
        """
        code = group.bail or more_specific(
            row.bail for row in findings if row.bail != ATOMICITY_BAIL and group.holds(row)
        )
        return group.row(self._result.path, code)


__all__ = [
    "BAILS",
    "LADDER",
    "ORDER",
    "RUNG",
    "atomicity",
    "configures",
    "more_specific",
    "needs_client",
    "plan",
]
