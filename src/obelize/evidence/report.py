"""The terminal summaries and `REPORT.md` for one run, kept together so they do not drift.

Renderers return lines and never print. The wording is deliberately not a contract
(`findings.json` is). Paths are repository-relative, and the run id and clock appear only in
the `REPORT.md` header, so repeated scans print identical terminal lines apart from the folder.
"""

from __future__ import annotations

import shlex
from collections import Counter
from pathlib import PurePath, PurePosixPath
from typing import TYPE_CHECKING

from obelize.models import WITHHELD, terminal_unsafe
from obelize.native import shell
from obelize.verify import redact
from obelize.verify import status as verdicts

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping, Sequence

    from obelize.models import (
        Finding,
        ManifestPlan,
        PlanDocument,
        ProposalRecord,
        RunCounts,
        RunModel,
        RunRecord,
        ScanCounts,
        UndoRecord,
        VerifyPhaseRecord,
        VerifyRecord,
    )
    from obelize.scan.runner import Scan
    from obelize.scan.runtime import Blocked
    from obelize.transforms.codemod import Run

# A scan's status split in print order, with display words from `Finding.scan_status`,
# not the fixture `verdict`.
SPLIT: tuple[tuple[str, str], ...] = (
    ("eligible", "eligible"),
    ("needs_review", "needs review"),
    ("unsupported", "unsupported"),
    ("not_a_usage", "not a usage"),
)

# A fix run's split, from the fixture `verdict`: `auto` means rewritten, where `eligible`
# means only not withheld.
FIX_SPLIT: tuple[tuple[str, str], ...] = (
    ("auto", "auto"),
    *SPLIT[1:],
)

# A tree dirty only through untracked planned files; the `Next:` line recognises its refusal by it.
UNTRACKED = "commit them (git add, then git commit), or pass --allow-dirty"

# Under a scan's table; `SCAN_VOCABULARY.md`, which defines the codes, is not installed.
LEGEND = (
    "Columns: line, kind, symbol, status, reason. eligible: obelize fix will try to migrate "
    "it; needs_review: left for you, for the reason shown; unsupported: the new SDK has no "
    "equivalent; not_a_usage: shown for context only."
)


# The interpreter the hint about obelize's own environment gives as an example.
_VENV_TESTS = '--verify "/path/to/your/project/.venv/bin/python -m pytest -q"'


def _code(text: str) -> str:
    """A code span in `REPORT.md`; a terminal would print the backticks."""
    return f"`{text}`"


def _bare(text: str) -> str:
    return text


def _tests() -> str:
    return f"--verify {shell.quote(TESTS)}"


def _inside(folder: str, name: str) -> str:
    """A path in the run folder, printed with this system's separator throughout.

    `folder` is spelled as the system spells it, and `name` may hold `/`.
    """
    return str(PurePath(folder, name))


def terminal(scan: Scan, pack: str, evidence: str | None) -> list[str]:
    """`obelize scan`'s non-JSON output."""
    lines = [f"obelize scan  {pack}", ""]
    for blocked in scan.blocked:
        lines.extend([_blocked(blocked, _bare), ""])
    for path, findings in _by_path(scan.findings):
        lines.append(f"  {path}")
        lines.extend(_rows(findings))
        lines.append("")
    if scan.findings:
        lines.extend([LEGEND, ""])
    lines.append(_headline(scan.counts, SPLIT))
    lines.extend(_repository(scan.manifests))
    if scan.limitations or scan.skipped:
        lines.append(
            f"{len(scan.limitations) + len(scan.skipped)} path(s) were skipped or only partly "
            f"read; REPORT.md in the run folder says which and why."
        )
    if evidence is not None:
        lines.append(f"Evidence: {evidence}")
    return lines


# Starts the superseding note; an HTML comment so a repeat `obelize verify` can find and replace it.
SUPERSEDED = "<!-- obelize:verified-again -->"

# The title of the baseline's rows, which the superseding note looks for.
_BASELINE = "Baseline"


# Lines of `patch.diff` a dry run prints; a longer one is named, not scrolled past.
DIFF_LINES = 200

# The tests a next step suggests; the interpreter is the user's to fill in.
TESTS = "<project python> -m pytest -q"


def fixed(
    record: RunRecord,
    plan: PlanDocument,
    pack: str,
    evidence: str,
    blocked: Sequence[Blocked],
    patch: bytes,
    environ: Mapping[str, str],
    repo: str,
) -> list[str]:
    """`obelize fix`'s non-JSON output; a written column on an apply, the diff on a dry run.

    `repo` is `--repo` as typed, so the closing `Next:` command runs where the user is.
    """
    applying = record.mode == "apply"
    written = {row.path for row in record.file_edits}
    mode = _mode(record, _bare, planned=bool(plan.files))
    lines = [f"obelize fix  {pack}", "", f"Mode {mode}", ""]
    for stopped in blocked:
        lines.extend([_blocked(stopped, _bare), ""])
    if not plan.files:
        lines.append("No change planned.")
        lines.extend(_held_back(record))
    for row in plan.files:
        mark = "" if not applying else ("  written" if row.path in written else "  not written")
        rules = ", ".join(_rule(name, record) for name in row.rules)
        lines.append(f"  {row.path}  ({row.hunks} hunk(s), {rules}){mark}")
    if not applying and patch:
        lines.extend(["", *diff(patch, evidence, environ)])
    lines.append("")
    lines.append(_headline(record.counts, FIX_SPLIT))
    for refusal in record.refused:
        subject = f"{refusal.path}: " if refusal.path else ""
        lines.append(f"Not written: {subject}{refusal.detail}")
    # Type narrowing only: `RunRecord` rejects a plan or apply without a verification.
    assert record.verify is not None  # noqa: S101 - see above
    lines.append(_verdict(record.verify))
    lines.extend(f"Hint: {hint}" for hint in _hints(record.verify, _bare))
    if record.model is not None:
        lines.append(_consulted(record.model))
    lines.append(f"Evidence: {evidence}")
    lines.extend(_next(record, evidence, repo))
    return lines


def _held_back(record: RunRecord) -> list[str]:
    """The code that held back the most findings; an atomicity row counts for each of its causes."""
    codes = Counter(code for row in record.withheld for code in row.caused_by or (row.bail,))
    return [
        f"Most common reason a finding was left for review: {code} "
        f"({count} of {len(record.withheld)})."
        for code, count in codes.most_common(1)
    ]


def _next(record: RunRecord, evidence: str, repo: str) -> list[str]:
    """The command after an apply, by exit code; a dry run, `3` and `4` with none left have none."""
    if record.mode != "apply":
        return []
    here = PurePath(repo) == PurePath(".")
    flag = "" if here else f" --repo {shell.quote(repo)}"
    git = "git" if here else f"git -C {shell.quote(repo)}"
    run = f"--run {record.run_id}{flag}"
    # Type narrowing only: `RunRecord` rejects an apply without a verification.
    assert record.verify is not None  # noqa: S101 - see above
    if record.exit_code == 0:
        # `git_sha` is null outside the top of a repository, where `git diff` may have no tree.
        shown = (
            f"{git} diff shows" if record.git_sha else f"{_inside(evidence, 'patch.diff')} holds"
        )
        step = f"{shown} the change; obelize undo {run} puts it back."
    elif record.exit_code == 4 and record.withheld:
        step = (
            f"{len(record.withheld)} finding(s) are left for you to review, listed in "
            f"{_inside(evidence, 'REPORT.md')}."
        )
    elif record.exit_code == 5:
        step = _unblocked(record, record.verify, git, run)
    elif record.exit_code == 6 and verdicts.settled(record.verify):
        step = (
            f"obelize undo {run}, then obelize fix --apply{flag} {_tests()}, with tests that "
            f"pass before the change."
        )
    elif record.exit_code == 6:
        step = f"obelize verify {run} {_tests()} checks the change with your tests."
    else:
        return []
    return [f"Next: {step}"]


def _unblocked(record: RunRecord, verify: VerifyRecord, git: str, run: str) -> str:
    """Exit 5: what refused the run, and the flag that permits it where one does.

    `git_dirty` is read before the baseline, which can change a tracked file, so the refusal says
    whether the tree was dirty only through untracked files.
    """
    codes = {row.code for row in record.refused}
    if any(row.detail.endswith(UNTRACKED) for row in record.refused):
        return (
            "commit the file(s) git does not track (git add, then git commit), "
            "or run again with --allow-dirty."
        )
    if "tree_dirty" in codes:
        return "commit or stash your changes, or run again with --allow-dirty."
    if "tree_unknown" in codes:
        return f"run {git} status to see why git failed, or run again with --allow-dirty."
    if verify.reason == "policy_refused":
        return f"obelize verify {run} --trust-repo-config runs the commands in .obelize.yml."
    return "fix what the Not written line names and run again; no flag skips this check."


def diff(patch: bytes, evidence: str, environ: Mapping[str, str]) -> list[str]:
    """`patch.diff` up to `DIFF_LINES` lines, then where the whole of it is.

    Redacted as command output is, since a terminal can be a CI log (TM-3); the file is not. A byte
    that is not UTF-8 prints as `\\xNN`.
    """
    text = redact.redact(patch.decode("utf-8", "backslashreplace"), environ)
    rows = text.removesuffix("\n").split("\n")
    cut = f" ({DIFF_LINES} of {len(rows)} lines shown)" if len(rows) > DIFF_LINES else ""
    return [*map(_printable, rows[:DIFF_LINES]), f"Diff: {_inside(evidence, 'patch.diff')}{cut}"]


def _printable(row: str) -> str:
    """The row with every character a terminal acts on spelled out, tab aside.

    A CRLF line's CR is dropped, since the line ends there anyway.
    """
    return "".join(
        character
        if terminal_unsafe(character, allowed="\t") is None
        else character.encode("unicode_escape").decode("ascii")
        for character in row.removesuffix("\r")
    )


def _consulted(model: RunModel) -> str:
    return (
        f"Model: {model.model} at {model.host}, {model.proposals} proposal(s), "
        f"{model.accepted} written, {model.tokens_in}+{model.tokens_out} tokens"
    )


def verified(record: RunRecord, evidence: str) -> list[str]:
    """`obelize verify`'s output: the new verdict and where it is written."""
    assert record.verify is not None  # noqa: S101 - `verify` is what this command rewrote
    return [
        f"obelize verify  {record.run_id}",
        "",
        _verdict(record.verify),
        f"Evidence: {evidence}",
    ]


def reverted(record: UndoRecord, folder: str, evidence: str) -> list[str]:
    """`obelize undo`'s output; a skipped file lists both hashes and the kept original to diff.

    A snapshot is named by its sha256, so a file whose hash is that name holds the original.
    """
    done = [row for row in record.files if row.outcome == "reverted"]
    lines = [f"obelize undo  {record.run_id}", ""]
    for row in record.files:
        lines.append(
            f"  {row.path}  {row.outcome}"
            + (f"  {row.reason}" if row.reason else "")
            + (
                "  (already the original)"
                if PurePosixPath(row.snapshot).name == row.current_sha256
                else ""
            )
        )
        if row.outcome == "reverted":
            continue
        lines.extend(
            [
                f"      recorded  {row.recorded_sha256}",
                f"      now       {row.current_sha256 or 'unreadable'}",
                f"      original  {_inside(folder, row.snapshot)}",
            ]
        )
    return [
        *lines,
        "",
        f"{len(done)} of {len(record.files)} file(s) put back.",
        f"Evidence: {evidence}",
    ]


def superseded(document_text: str, record: RunRecord, when: str) -> str:
    """The report plus one note naming the current verdict; a repeat replaces the note.

    The report cannot be rebuilt: its scan and driver run are not in the folder. It says whether
    tests ran before the change, which a re-verified record no longer does.
    """
    assert record.verify is not None  # noqa: S101 - only a re-verification supersedes
    body = document_text.split(SUPERSEDED)[0].rstrip("\n")
    verdict = f"`{record.verify.status}`" + (
        f" (`{record.verify.reason}`)" if record.verify.reason else ""
    )
    # Tests that print nothing leave no `verify/baseline/`, so the note points at their section.
    before = (
        f"The {_BASELINE} section above still shows the tests run before the change."
        if f"\n### {_BASELINE}\n" in body
        else "No tests ran before the change."
    )
    return "\n".join(
        [
            body,
            "",
            SUPERSEDED,
            "",
            "## Verified again",
            "",
            f"`obelize verify` checked this run again at {when}: {verdict}. The section "
            f"above shows the first result; `run.json` and `verify/verify.json` hold the new "
            f"one. {before}",
            "",
        ]
    )


def _verdict(verify: VerifyRecord) -> str:
    reason = f" ({verify.reason})" if verify.reason else ""
    return f"Verification: {verify.status}{reason}, {_ran(verify)}"


def _ran(verify: VerifyRecord) -> str:
    """The commands that started; a baseline that stopped the after-phase ran its own alone."""
    if verify.commands or verify.baseline is None:
        return f"{_started(verify)} command(s) ran"
    return f"{_started(verify.baseline)} command(s) ran before the patch"


def _started(phase: VerifyPhaseRecord) -> int:
    return sum(row.reason != "command_not_executable" for row in phase.commands)


def _hints(verify: VerifyRecord, code: Callable[[str], str]) -> list[str]:
    """A hint per baseline command that failed or timed out, found in obelize's own environment
    (`uv run obelize`), and per one that never started.

    The environment is inherited by design, so this does not guess which program was meant.
    """
    if verify.baseline is None:
        return []
    rows = verify.baseline.commands
    return [
        *(
            f"{code(row.command)} {'timed out' if row.reason == 'timeout' else 'failed'}, and "
            "its program came from the environment obelize runs in, which may not be your "
            "project's. To run your project's tests, name its interpreter: "
            f"{code(_VENV_TESTS)}."
            for row in rows
            if row.status != "pass" and row.in_obelize_environment
        ),
        *(
            f"{code(shlex.split(row.command)[0])} did not start: there is no such program, or "
            f"no permission to run it. To run your project's tests, name its interpreter: "
            f"{code(_tests())}."
            for row in rows
            if row.reason == "command_not_executable"
        ),
    ]


def document(
    record: RunRecord,
    scan: Scan,
    run: Run | None = None,
    plan: PlanDocument | None = None,
    proposals: Sequence[ProposalRecord] = (),
) -> str:
    """`REPORT.md`: everything the run learned, in the order it learned it.

    `run` (driver output) and `plan` must match the mode, else ValueError. A fix keeps the findings
    table beside the edits: a file the scan refused has no edit, and that is not a hole.
    `proposals` (from `model/`) are inlined because model hunks most need a human reader.
    """
    _agree(record, run, plan)
    lines = _preamble(record, scan, run is not None, planned=plan is not None and bool(plan.files))
    if scan.blocked:
        lines.extend(["## Blocked", ""])
        for blocked in scan.blocked:
            lines.extend([_blocked(blocked, _code), ""])
    if run is not None and plan is not None:
        lines.extend(_changes_section(record, plan))
        lines.extend(_edits_section(run))
        lines.extend(_refused_section(record))
        lines.extend(_findings_section(run.findings))
    else:
        lines.extend(_findings_section(scan.findings))
    lines.extend(_withheld_section(record))
    lines.extend(_manifest_section(scan.manifests if run is None else run.manifest_plan))
    if record.verify is not None:
        lines.extend(_verification_section(record.verify))
    if record.model is not None:
        lines.extend(_model_section(record.model, proposals))
    lines.extend(_limitations_section(record))
    return "\n".join(lines).rstrip("\n") + "\n"


def _agree(record: RunRecord, run: Run | None, plan: PlanDocument | None) -> None:
    if (record.mode == "scan") == (run is None and plan is None):
        return
    raise ValueError(
        f"a {record.mode!r} record was rendered with "
        f"{'a' if run is not None else 'no'} driver run and "
        f"{'a' if plan is not None else 'no'} plan; the mode says which it needs"
    )


def _preamble(record: RunRecord, scan: Scan, fixing: bool, *, planned: bool) -> list[str]:
    counts = record.counts
    return [
        f"# obelize {'fix' if fixing else 'scan'}",
        "",
        f"`{record.run_id}` · {record.timings.finished_at} · obelize {record.obelize_version}",
        "",
        *([f"- **Mode** {_mode(record, _code, planned=planned)}"] if fixing else []),
        *(
            f"- **Pack** `{pack.id}` {pack.pack_version} ({pack.source}), sha256 `{pack.sha256}`"
            for pack in record.packs
        ),
        f"- **Selection** {counts.files_selected} file(s) from the "
        f"{'git listing' if scan.source == 'git' else 'directory walk'}, "
        f"{counts.files_parsed} parsed, {scan.workers} worker process(es)",
        f"- **Configuration** {record.config.source}, "
        f"include `{record.config.include}`, "
        f"{len(record.config.exclude)} extra exclusion(s)",
        "",
        _headline(counts, FIX_SPLIT if fixing else SPLIT),
        "",
    ]


def _rule(name: str, record: RunRecord) -> str:
    """A rule as a person reads it: the pack is named only where more than one ran."""
    return name if len(record.packs) > 1 else name.partition(":")[2] or name


def _mode(record: RunRecord, code: Callable[[str], str], *, planned: bool) -> str:
    """An empty `patch.diff` is not called a change."""
    if record.mode == "plan":
        change = f"; {code('patch.diff')} holds the change it would make" if planned else ""
        return f"{code('plan')}: a dry run. Nothing in the repository was written{change}."
    return f"{code('apply')}: {len(record.file_edits)} file(s) written."


def _changes_section(record: RunRecord, plan: PlanDocument) -> list[str]:
    """What the run would write and, on an apply, whether it did (`plan.json` vs `file_edits[]`)."""
    lines = ["## Changes", ""]
    if not plan.files:
        return [*lines, "This run had no file to write.", ""]
    applying = record.mode == "apply"
    written = {row.path for row in record.file_edits}
    lines.append("| File | Hunks | Rules |" + (" Written |" if applying else ""))
    lines.append("|---|---|---|" + ("---|" if applying else ""))
    for row in plan.files:
        rules = ", ".join(f"`{_rule(name, record)}`" for name in row.rules)
        cells = f"| `{row.path}` | {row.hunks} | {rules} |"
        lines.append(cells + (f" {'yes' if row.path in written else 'no'} |" if applying else ""))
    return [*lines, ""]


def _edits_section(run: Run) -> list[str]:
    lines = ["## Edits", ""]
    if not run.edits:
        return [*lines, "No rule matched anything in this repository.", ""]
    lines.extend(
        ["| File | Line | Status | Rule | Reason | Warnings |", "|---|---|---|---|---|---|"]
    )
    for row in sorted(run.edits, key=lambda edit: (edit.path, edit.line)):
        reason = f"`{row.reason}`" if row.reason else "--"
        if row.caused_by:
            reason += " (" + ", ".join(f"`{code}`" for code in row.caused_by) + ")"
        lines.append(
            f"| `{row.path}` | {row.line} | {row.status} "
            f"| {f'`{row.rule_id}`' if row.rule_id else '--'} | {reason} "
            f"| {', '.join(f'`{code}`' for code in row.warnings) or '--'} |"
        )
    return [*lines, ""]


def _refused_section(record: RunRecord) -> list[str]:
    """Planned writes that did not land; without it a refused apply reads as nothing to do."""
    if not record.refused:
        return []
    lines = ["## Not written", "", "| Path | Code | Detail |", "|---|---|---|"]
    for row in record.refused:
        lines.append(f"| {f'`{row.path}`' if row.path else '--'} | `{row.code}` | {row.detail} |")
    return [*lines, ""]


def _verification_section(verify: VerifyRecord) -> list[str]:
    lines = [
        "## Verification",
        "",
        f"**{verify.status}**" + (f" (`{verify.reason}`)" if verify.reason else ""),
        "",
    ]
    for hint in _hints(verify, _code):
        lines.extend([f"**Hint:** {hint}", ""])
    if verify.baseline is not None:
        lines.extend(_phase_rows(_BASELINE, verify.baseline))
    lines.extend(_phase_rows("After the patch", verify))
    return lines


def _phase_rows(title: str, phase: VerifyPhaseRecord) -> list[str]:
    lines = [
        f"### {title}",
        "",
        f"`{phase.status}`" + (f" (`{phase.reason}`)" if phase.reason else ""),
        "",
    ]
    if not phase.commands:
        return [*lines, "No command ran.", ""]
    lines.extend(
        ["| Command | Source | Status | Exit | Duration | Output |", "|---|---|---|---|---|---|"]
    )
    for row in phase.commands:
        lines.append(
            f"| `{row.command}` | {row.source} | {row.status} "
            f"| {'--' if row.exit_code is None else row.exit_code} | {row.duration_ms} ms "
            f"| {f'`{row.log}`' if row.log else '--'}"
            f"{' (truncated)' if row.truncated else ''} |"
        )
    return [*lines, ""]


def _findings_section(findings: tuple[Finding, ...]) -> list[str]:
    if not findings:
        return ["## Findings", "", "Nothing in this repository matched the pack.", ""]
    lines = ["## Findings", ""]
    for path, grouped in _by_path(findings):
        lines.extend(
            [
                f"### `{path}`",
                "",
                "| Line | Kind | Symbol | Status | Why |",
                "|---|---|---|---|---|",
            ]
        )
        for finding in grouped:
            lines.append(
                f"| {finding.line} | {finding.kind} | {_symbol(finding)} | "
                f"{finding.scan_status} | {finding.bail or finding.confidence_reason} |"
            )
        lines.append("")
    return lines


def _withheld_section(record: RunRecord) -> list[str]:
    if not record.withheld:
        return []
    lines = [
        "## Withheld",
        "",
        "| File | Line | Symbol | Reason | Caused by |",
        "|---|---|---|---|---|",
    ]
    for row in record.withheld:
        caused = ", ".join(row.caused_by) if row.caused_by else "--"
        lines.append(
            f"| `{row.path}` | {row.line} | {f'`{row.symbol}`' if row.symbol else '--'} "
            f"| `{row.bail}` | {caused} |"
        )
    return [*lines, ""]


def _manifest_section(plan: ManifestPlan) -> list[str]:
    lines = ["## Dependency manifests", ""]
    if not plan.findings:
        return [*lines, "No manifest declares the legacy distribution.", ""]
    for finding in plan.findings:
        lines.append(
            f"- `{finding.path}`:{finding.line} `{finding.symbol}`: "
            f"{finding.scan_status}" + (f" (`{finding.bail}`)" if finding.bail else "")
        )
    if plan.blocking:
        lines.extend(
            ["", "Still importing the legacy distribution:", ""]
            + [f"- `{path}`" for path in plan.blocking]
        )
    if plan.excluded:
        lines.extend(
            ["", "Excluded from the scan but still importing it:", ""]
            + [f"- `{path}`" for path in plan.excluded]
        )
    return [*lines, ""]


def _model_section(model: RunModel, proposals: Sequence[ProposalRecord]) -> list[str]:
    """One row per consultation, not per proposal: a down endpoint yields none but must show."""
    lines = [
        "## Model",
        "",
        f"`{model.provider}`, `{model.model}` at `{model.host}`. "
        f"{model.proposals} proposal(s) from {len(proposals)} question(s), "
        f"{model.accepted} written; {model.tokens_in} token(s) in, "
        f"{model.tokens_out} out.",
        "",
        "Proposals are written only with `--apply` and `--accept-model`. Review every "
        "written one: validation shows that an edit is safe to apply, not that it is "
        "correct.",
        "",
        "| # | Site | Outcome | Reason | Detail |",
        "|---|---|---|---|---|",
    ]
    for row in proposals:
        word = row.failure or row.refusal
        lines.append(
            f"| {row.index} | `{row.path}:{row.line}` | `{row.outcome}` | "
            f"{f'`{word}`' if word else '--'} | {row.detail or '--'} |"
        )
    return [*lines, ""]


def _limitations_section(record: RunRecord) -> list[str]:
    if not record.limitations:
        return ["## Limitations", "", "Every selected path was read.", ""]
    lines = ["## Limitations", "", "| Path | Code | Detail |", "|---|---|---|"]
    for row in record.limitations:
        lines.append(f"| {f'`{row.path}`' if row.path else '--'} | `{row.code}` | {row.detail} |")
    return [*lines, ""]


def _blocked(blocked: Blocked, code: Callable[[str], str]) -> str:
    needed, package = code(blocked.needed), code(blocked.package)
    if blocked.reason == "runtime_unsupported":
        path = code(blocked.path)
        return (
            f"{path} declares Python {code(blocked.declared or '')}, which allows versions "
            f"{package} does not install on, so this run reports its findings and plans no "
            f"change. To migrate, raise the minimum in {path} to {needed} and run again."
        )
    if not blocked.path:
        return (
            f"No manifest declares {package}, so the version in use is not known and this run "
            f"reports its findings and plans no change. To migrate, declare {package} {needed} "
            f"in a manifest obelize reads and run again."
        )
    path = code(blocked.path)
    if blocked.declared is None:
        return (
            f"{path} declares {package} in a form obelize cannot read, so this run reports its "
            f"findings and plans no change. To migrate, write it as a plain requirement such as "
            f"{code(f'{blocked.package}{blocked.needed}')} in {path} and run again."
        )
    declared = code(blocked.declared) if blocked.declared else "with no version"
    return (
        f"{path} declares {package} {declared}, which allows versions this migration does not "
        f"cover, so this run reports its findings and plans no change. To migrate, pin {package} "
        f"to {needed} in {path} and run again."
    )


def _headline(counts: ScanCounts | RunCounts, names: tuple[tuple[str, str], ...]) -> str:
    split = ", ".join(
        f"{getattr(counts, field)} {word}" for field, word in names if getattr(counts, field)
    )
    return (
        f"{counts.files_selected} file(s) selected, {counts.files_parsed} parsed, "
        f"{counts.findings} finding(s)" + (f": {split}" if split else "")
    )


def _repository(plan: ManifestPlan) -> list[str]:
    if not plan.findings:
        return []
    return [
        f"{len(plan.findings)} dependency declaration(s)"
        + (
            f", blocked by {len(plan.blocking)} file(s) that still import it"
            if plan.blocking
            else ""
        )
    ]


def _rows(findings: list[Finding]) -> list[str]:
    width = max(len(f"{finding.line}") for finding in findings)
    kind = max(len(finding.kind) for finding in findings)
    symbol = max(len(_symbol(finding)) for finding in findings)
    rows = []
    for finding in findings:
        reason = finding.bail or finding.confidence_reason
        rows.append(
            f"    {finding.line:>{width}}  {finding.kind:<{kind}}  "
            f"{_symbol(finding):<{symbol}}  {finding.scan_status:<12}  {reason}"
        )
    return rows


def _symbol(finding: Finding) -> str:
    """The symbol, or `--` for a `parse_error`, which `Finding` never lets carry one."""
    return finding.symbol or "--"


def _by_path(findings: tuple[Finding, ...]) -> list[tuple[str, list[Finding]]]:
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.path, []).append(finding)
    return list(grouped.items())


def withheld_rows(findings: tuple[Finding, ...]) -> list[Finding]:
    return [finding for finding in findings if finding.scan_status in WITHHELD]


__all__ = [
    "DIFF_LINES",
    "FIX_SPLIT",
    "LEGEND",
    "SPLIT",
    "SUPERSEDED",
    "diff",
    "document",
    "fixed",
    "reverted",
    "superseded",
    "terminal",
    "verified",
    "withheld_rows",
]
