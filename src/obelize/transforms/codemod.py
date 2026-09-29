"""The fix driver: a pack's rules over a scanned repository, then a re-grade. Writes nothing.

Order is a dependency: every `Rule` over every file, then the manifest survey, then every
`ManifestRule`; within a file, the pack's declaration order (the import rule reserves the names
the client and model rules spell against). A file with anything withheld comes back unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import libcst as cst
from libcst.metadata import MetadataWrapper, ScopeProvider

from obelize.impact import planner
from obelize.models import (
    ATOMICITY_BAIL,
    Edit,
    Finding,
    ImpactPlan,
    ImpactPolicy,
    ManifestPlan,
)
from obelize.scan import manifests, parse
from obelize.transforms import base, registry
from obelize.transforms import manifest as manifest_context

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Collection, Mapping, Sequence

    from libcst.metadata import Scope

    from obelize.models import BailCode, ScanSpec
    from obelize.packs.schema import PackDocument
    from obelize.scan.runner import FileResult, Scan

# An eligible row no rule claims: the pack's limitation, not the code's defect.
UNCLAIMED: BailCode = "usage_unmapped"

# The output parse/compile gate; a file gate, so it lands on every row.
GATE: BailCode = "output_does_not_parse"

# The second output gate, asked of bytes the first passed; also a file gate.
UNRESOLVED: BailCode = "output_names_unresolved"

# A `configure` another module still runs on: about the file, stamped on the call's row.
CONSUMED: BailCode = "configure_consumed_elsewhere"

# Deliberately not in `planner.LADDER`: fix-time codes, only ever stamped on an `eligible` row.
BAILS: frozenset[BailCode] = frozenset({UNCLAIMED, GATE, UNRESOLVED, CONSUMED})


class CodemodError(Exception):
    """A misuse of the driver (bad sources, the `dual` policy), not a bail about user code."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """One file before and after; `after` is `before` for every file the run does not write."""

    path: str
    before: bytes
    after: bytes
    edits: tuple[Edit, ...]

    @property
    def written(self) -> bool:
        """Whether this run changes the file at all."""
        return self.after != self.before


@dataclass(frozen=True, slots=True)
class Run:
    """One repository after one pack; `plans` (scan order) records why a file was not written."""

    files: tuple[Outcome, ...]
    manifests: tuple[Outcome, ...]
    plans: tuple[ImpactPlan, ...]
    manifest_plan: ManifestPlan

    @property
    def outcomes(self) -> tuple[Outcome, ...]:
        """Every file this run looked at, the manifests after the sources."""
        return self.files + self.manifests

    @property
    def edits(self) -> tuple[Edit, ...]:
        """Every row the run reports, in the order the files are written in."""
        return tuple(row for outcome in self.outcomes for row in outcome.edits)

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Every row as re-graded, in document order; `run.json`'s `counts.auto` counts from it.

        The manifest pin check grades one manifest declaration twice, so this can outnumber
        `Scan.findings`.
        """
        return tuple(
            sorted(
                [row for plan in self.plans for row in plan.findings]
                + list(self.manifest_plan.findings),
                key=lambda finding: finding.sort_key,
            )
        )

    @property
    def written(self) -> tuple[Outcome, ...]:
        """The files this run changes, and the whole of what it would write."""
        return tuple(outcome for outcome in self.outcomes if outcome.written)


def run(
    scan: Scan,
    sources: Mapping[str, bytes],
    pack: PackDocument,
    spec: ScanSpec,
    policy: ImpactPolicy | None = None,
) -> Run:
    """Run `pack` over `sources` (scan path to bytes, manifests included) and re-grade.

    A scanned file missing from `sources` is left alone; one with an `eligible` row raises.
    """
    policy = policy or ImpactPolicy()
    if policy.import_policy != "atomic":
        raise CodemodError(
            f"no rule implements the {policy.import_policy!r} import policy, which leaves "
            f"both imports in place and rewrites what resolved; running under it would write "
            f"a file whose import was renamed and whose refused group was not"
        )
    results = {result.path: result for result in scan.results}
    _check(results, sources)

    files: list[Outcome] = []
    plans: list[ImpactPlan] = []
    for result in scan.results:
        data = sources.get(result.path)
        if data is None or not result.parsed:
            plans.append(result.plan)
            continue
        outcome, plan = _file(result, data, pack, spec, policy)
        files.append(outcome)
        plans.append(plan)

    if any(_relies(plan, spec) for plan in plans):
        files, plans = _elsewhere(files, plans, pack, spec, policy)
    graded = _manifest_plan(scan, sources, plans, spec)
    return Run(
        files=tuple(files),
        manifests=tuple(_manifest(name, sources[name], graded, pack) for name in _named(graded)),
        plans=tuple(plans),
        manifest_plan=graded,
    )


def _check(results: Mapping[str, FileResult], sources: Mapping[str, bytes]) -> None:
    """Refuse bytes no scan read, and eligible files handed no bytes."""
    unknown = sorted(name for name in sources if name not in results and not _is_manifest(name))
    if unknown:
        raise CodemodError(f"{unknown} were not in this scan; a plan grades the bytes it read")
    missing = sorted(
        path
        for path, result in results.items()
        if path not in sources
        and any(row.scan_status == "eligible" for row in result.plan.findings)
    )
    if missing:
        raise CodemodError(
            f"{missing} have eligible findings and no bytes were handed over; the dependency "
            f"edit would report them migrated while the run wrote nothing for them"
        )


def _is_manifest(path: str) -> bool:
    """The walker's own predicate, so the partition here is not a second one."""
    return manifests.is_manifest(path)


def _file(
    result: FileResult, data: bytes, pack: PackDocument, spec: ScanSpec, policy: ImpactPolicy
) -> tuple[Outcome, ImpactPlan]:
    """Every rule over one file, then the atomicity check; rules are built fresh per file, as
    the corpora do."""
    rules = registry.rules(pack)
    module = cst.parse_module(data)
    context = base.RuleContext.build(result.plan, module, spec, rules, pack.layout)

    # Keyed by `id(finding)`: two rows can share a line. `result.plan.findings` outlives this call.
    edits: list[Edit] = []
    withheld: dict[int, BailCode] = {}
    for rule in rules:
        reported = rule.apply(context)
        edits.extend(reported)
        _refusals(result.plan.findings, rule, reported, withheld)
    for finding in result.plan.findings:
        if finding.scan_status == "eligible" and not any(rule.claims(finding) for rule in rules):
            withheld[id(finding)] = UNCLAIMED
            edits.append(_row(finding, UNCLAIMED))

    produced = base.finish(context).bytes

    # A file that does not round-trip has no eligible row, but libcst's re-render still differs
    # from its bytes: writing `produced` would change a file the run decided not to change.
    faithful = module.bytes == data
    gate = (
        _gate(result.path, module, produced)
        if not withheld and faithful and produced != data
        else None
    )
    if gate is not None:
        withheld = {
            id(finding): gate
            for finding in result.plan.findings
            if finding.scan_status == "eligible"
        }

    plan = _revised(result.plan, withheld, policy)
    rows = _ordered(edits)
    if withheld:
        rows = [_held(row, plan, gate) for row in rows]
    return Outcome(
        path=result.path,
        before=data,
        after=data if withheld or not faithful else produced,
        edits=tuple(rows),
    ), plan


def _gate(path: str, module: cst.Module, produced: bytes) -> BailCode | None:
    """Do the bytes parse and compile, and read no unbound name the input did not already read."""
    read = parse.gates(path, produced)
    if read.module is None:
        return GATE
    if _unresolved(read.module) - _unresolved(module):
        return UNRESOLVED
    return None


def _unresolved(module: cst.Module) -> frozenset[str]:
    """Names the module reads that nothing binds, builtins aside; string annotations count."""
    scopes = MetadataWrapper(module, unsafe_skip_copy=True).resolve(ScopeProvider)
    # Typed `Scope | None`, but no node has been seen to map to `None`.
    every = cast("Collection[Scope]", set(scopes.values()))
    return frozenset(
        module.code_for_node(access.node)
        for scope in every
        for access in scope.accesses
        if not access.referents
    )


def _refusals(
    findings: Sequence[Finding],
    rule: base.Rule,
    produced: Sequence[Edit],
    withheld: dict[int, BailCode],
) -> None:
    """Put one rule's refusals on its rows by line and `claims`; no row has two claimants."""
    reasons = {row.line: row.reason for row in produced if row.reason is not None}
    for finding in findings:
        code = reasons.get(finding.line)
        if code is not None and finding.scan_status == "eligible" and rule.claims(finding):
            withheld[id(finding)] = code


def _revised(
    plan: ImpactPlan, withheld: Mapping[int, BailCode], policy: ImpactPolicy
) -> ImpactPlan:
    """The plan re-graded with `withheld`, rebuilt so `ImpactPlan` asserts atomicity again.

    Bindings are kept: a refusal is about the rewrite, not how the object was bound.
    """
    findings = tuple(
        _withheld(row, withheld[id(row)]) if id(row) in withheld else row for row in plan.findings
    )
    return ImpactPlan(
        path=plan.path,
        findings=planner.atomicity(findings, policy),
        bindings=plan.bindings,
        import_policy=plan.import_policy,
    )


def _withheld(finding: Finding, code: BailCode) -> Finding:
    return Finding(**{**finding.model_dump(), "scan_status": "needs_review", "bail": code})


def _row(finding: Finding, code: BailCode) -> Edit:
    """The driver's own row, which names no rule because no rule claimed it."""
    return Edit(path=finding.path, line=finding.line, status="needs_review", reason=code)


def _held(edit: Edit, plan: ImpactPlan, gate: BailCode | None) -> Edit:
    """One row of an unwritten file: an `auto` row takes the gate, or atomicity and its causes."""
    if edit.status != "auto":
        return edit
    reason = gate or ATOMICITY_BAIL
    causes = None if gate else _causes(plan)
    return Edit(
        **{**edit.model_dump(), "status": "needs_review", "reason": reason, "caused_by": causes}
    )


def _causes(plan: ImpactPlan) -> tuple[BailCode, ...]:
    """Exactly what atomicity put in `caused_by`, read from where it put it."""
    return tuple(
        sorted({row.bail for row in plan.findings if row.bail and row.bail != ATOMICITY_BAIL})
    )


def _ordered(edits: Sequence[Edit]) -> list[Edit]:
    """Line order; stable, so rules keep their order in a line and the driver's rows fit in."""
    return sorted(edits, key=lambda row: row.line)


def _relies(plan: ImpactPlan, spec: ScanSpec) -> bool:
    """Whether the module stays on the legacy SDK with no `configure` of its own.

    It then runs on any other module's `configure`. A `mock.patch` target does not count.
    """
    return not any(planner.configures(row, spec) for row in plan.findings) and any(
        row.scan_status != "eligible" and row.kind in manifests.IMPORTING for row in plan.findings
    )


def _elsewhere(
    files: Sequence[Outcome],
    plans: Sequence[ImpactPlan],
    pack: PackDocument,
    spec: ScanSpec,
    policy: ImpactPolicy,
) -> tuple[list[Outcome], list[ImpactPlan]]:
    """Leave every file whose `configure` this run would rewrite as it was.

    `configure` sets a process-wide default; deleting it breaks the relying module while a mocked
    suite stays green. Asked after all rules, which can leave an `eligible` module on legacy.
    """
    revised = {}
    for plan in plans:
        withheld = {
            id(row): CONSUMED
            for row in plan.findings
            if row.scan_status == "eligible" and planner.configures(row, spec)
        }
        if withheld:
            revised[str(plan.path)] = _revised(plan, withheld, policy)
    return (
        [
            _kept(outcome, revised[outcome.path], pack) if outcome.path in revised else outcome
            for outcome in files
        ],
        [revised.get(str(plan.path), plan) for plan in plans],
    )


def _kept(outcome: Outcome, plan: ImpactPlan, pack: PackDocument) -> Outcome:
    """A file kept as it was: the `configure`'s row (by `claims`) is `CONSUMED`, the rest name it.

    Every row was `auto`: a file with anything withheld has no eligible `configure`.
    """
    rules: dict[str | None, base.Rule] = {
        change.id: rule for change in pack.changes if (rule := registry.rule_for(change))
    }
    consumed = [row for row in plan.findings if row.bail == CONSUMED]
    rows = []
    for edit in outcome.edits:
        if any(rules[edit.rule_id].claims(row) for row in consumed):
            edit = Edit(**{**edit.model_dump(), "status": "needs_review", "reason": CONSUMED})
        rows.append(_held(edit, plan, None))
    return Outcome(
        path=outcome.path, before=outcome.before, after=outcome.before, edits=tuple(rows)
    )


def _manifest_plan(
    scan: Scan, sources: Mapping[str, bytes], plans: Sequence[ImpactPlan], spec: ScanSpec
) -> ManifestPlan:
    """The manifest pin check over what the rules leave, re-reading declarations from the
    bytes (one reader)."""
    migration = manifests.survey(plans, scan.manifests.excluded, scan.unanalysed, scan.transitive)
    declared = [
        declaration
        for name in sorted(sources)
        if _is_manifest(name)
        for declaration in manifests.declarations(name, sources[name])
    ]
    return manifests.plan(declared, migration, spec)


def _named(plan: ManifestPlan) -> tuple[str, ...]:
    """The manifests the pin check graded a declaration in, in path order."""
    return tuple(sorted({str(row.path) for row in plan.findings}))


def _manifest(name: str, data: bytes, plan: ManifestPlan, pack: PackDocument) -> Outcome:
    """Every manifest rule over one manifest; deliberately no gate (not Python) and no atomicity.

    The pin check grades one declaration twice, so an applied edit beside a withheld one is normal.
    """
    context = manifest_context.ManifestContext.build(name, data, plan)
    edits = [row for rule in registry.manifest_rules(pack) for row in rule.apply(context)]
    return Outcome(
        path=name,
        before=data,
        after=manifest_context.finish(context),
        edits=tuple(_ordered(edits)),
    )


__all__ = ["BAILS", "CONSUMED", "GATE", "UNCLAIMED", "CodemodError", "Outcome", "Run", "run"]
