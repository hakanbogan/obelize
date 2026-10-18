"""The terminal summaries and `REPORT.md` for one run, kept together so they do not drift.

Renderers return lines and never print. The wording is deliberately not a contract
(`findings.json` is). Paths are repository-relative, and the run id and clock appear only in
the `REPORT.md` header, so repeated scans print identical terminal lines apart from the folder.
"""

from __future__ import annotations

import re
import shlex
from collections import Counter
from pathlib import PurePath
from typing import TYPE_CHECKING

from obelize import __version__
from obelize.models import (
    ATOMICITY_BAIL,
    BAIL_ACTIONS,
    REPO_ATOMICITY_BAIL,
    TIMEOUT_S,
    WARNING_MEANINGS,
    WITHHELD,
    printable,
)
from obelize.native import shell
from obelize.verify import redact
from obelize.verify import status as verdicts

if TYPE_CHECKING:
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
    from obelize.packs.schema import PackDocument
    from obelize.scan.runner import Scan
    from obelize.scan.runtime import Blocked
    from obelize.transforms.codemod import Run
    from obelize.transforms.kinds.flag_only import Guide

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

# Under the table of an inventory, where no row can be eligible and `fix` has nothing to try.
INVENTORY_LEGEND = (
    "Columns: line, kind, symbol, status, reason. Every place of the library is needs_review "
    "because no migration pack covers it: obelize lists it and rewrites nothing. not_a_usage: "
    "shown for context only."
)

# Under a scan's table; `SCAN_VOCABULARY.md`, which defines the codes, is not installed.
LEGEND = (
    "Columns: line, kind, symbol, status, reason (blank when eligible). eligible: obelize fix "
    "will try to migrate it; needs_review: left for you, for the reason shown; unsupported: the "
    "new SDK has no equivalent; not_a_usage: shown for context only. fix leaves a file as it was "
    "when any row in it is needs_review or unsupported (for openai, any row in the repository)."
)


# What turns a line of pack text into Markdown or HTML; `_` and `#` only matter at a line start.
_MARKUP = re.compile(r"[\\`*<>&\[\]!|]")

# Where `Edit.reason` is defined, at the tag of this release so the table is the one that ships.
CODES = (
    "https://github.com/hakanbogan/obelize/blob/v{version}/docs/SCAN_VOCABULARY.md"
    "#4-bail-codes-editreason"
)

# Rows `_left` names with their file and line; the rest are in REPORT.md.
ROOT_ROWS = 5


def _code(text: str) -> str:
    """A code span in `REPORT.md`; a terminal would print the backticks.

    The fence is longer than any run of backticks inside, so a command that holds one stays in it.
    """
    fence = "`" * (max(map(len, re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _bare(text: str) -> str:
    return text


def _tests() -> str:
    return f"--verify {shell.quote(TESTS)}"


def _venv_tests() -> str:
    """The interpreter the hint about obelize's own environment gives as an example."""
    return f'--verify "/path/to/your/project/{shell.VENV_PYTHON} -m pytest -q"'


def _inside(folder: str, name: str) -> str:
    """A path in the run folder, printed with this system's separator throughout.

    `folder` is spelled as the system spells it, and `name` may hold `/`.
    """
    return str(PurePath(folder, name))


def flags(repo: str, packs: Sequence[str] = ()) -> str:
    """What a suggested `fix` repeats of this command: the packs named, and `--repo` as typed."""
    where = "" if PurePath(repo) == PurePath(".") else f" --repo {shell.quote(repo)}"
    return "".join(f" --pack {shell.quote(one)}" for one in packs) + where


def terminal(
    scan: Scan,
    pack: str,
    evidence: str | None,
    guides: Sequence[Guide] = (),
    fix: str = "",
    *,
    inventory: bool = False,
) -> list[str]:
    """`obelize scan`'s non-JSON output; `fix` is `flags(...)` for the command it suggests."""
    lines = [f"obelize scan  {pack}", ""]
    for blocked in scan.blocked:
        lines.extend(
            [
                _blocked(blocked, _bare),
                "That migration's rows below show what fix would try once that is changed.",
                "",
            ]
        )
    lines.extend(_assumed(scan.assumed, _bare))
    for path, findings in _by_path(scan.findings):
        lines.append(f"  {path}")
        lines.extend(_rows(findings))
        lines.append("")
    if scan.findings:
        lines.extend([INVENTORY_LEGEND if inventory else LEGEND, ""])
    lines.append(_headline(scan.counts, SPLIT))
    lines.extend(_repository(scan.manifests))
    lines.extend(_unwritten(scan.unwritten, _bare))
    lines.extend(_guidance(guides))
    if scan.limitations or scan.skipped:
        lines.append(
            f"{len(scan.limitations) + len(scan.skipped)} path(s) were skipped or only partly "
            f"read; REPORT.md in the run folder says which and why."
        )
    if evidence is not None:
        lines.append(f"Evidence: {evidence}")
    if not scan.blocked and scan.counts.eligible:
        lines.append(f"Next: obelize fix{fix} shows what it would change.")
    return lines


# Starts the superseding note; an HTML comment so a repeat `obelize verify` can find and replace it.
SUPERSEDED = "<!-- obelize:verified-again -->"

# A repeat takes the last note that is a heading and one paragraph to the end, so text above it,
# such as a file name with line breaks, cannot forge one and cut the report.
_NOTE = f"{SUPERSEDED}\n\n## Verified again\n"
_ONE_LINE = re.compile(r"\n[^\n]*\n")

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
    assumed: Sequence[tuple[str, str]],
    patch: bytes,
    environ: Mapping[str, str],
    repo: str,
    packs: Sequence[str],
    held: ManifestPlan,
    guides: Sequence[Guide] = (),
    locks: Sequence[str] = (),
    unwritten: Sequence[tuple[str, tuple[int, ...]]] = (),
) -> list[str]:
    """`obelize fix`'s non-JSON output; a written column on an apply, the diff on a dry run.

    `repo` is `--repo` as typed and `packs` the `--pack` values, so the closing `Next:` command
    runs where the user is, on what the user chose. `held` is the pin check, which names the
    files that hold a pin without a row; `locks` are the lock files beside a manifest pin written
    or above it; `unwritten` are the files that use the legacy API and that no rule writes.
    """
    applying = record.mode == "apply"
    written = {row.path for row in record.file_edits}
    mode = _mode(record, _bare, planned=bool(plan.files))
    lines = [f"obelize fix  {pack}", "", f"Mode {mode}", ""]
    for stopped in blocked:
        lines.extend([_blocked(stopped, _bare), ""])
    lines.extend(_assumed(assumed, _bare))
    if not plan.files:
        lines.append("No change planned.")
    for row in plan.files:
        mark = "" if not applying else ("  written" if row.path in written else "  not written")
        lines.append(f"  {row.path}  ({row.hunks} hunk(s)){mark}")
    if not applying and patch:
        lines.extend(["", *diff(patch, evidence, environ)])
    lines.extend(_check(plan, written if applying else {row.path for row in plan.files}, applying))
    lines.extend(_left(record, held, evidence))
    lines.append("")
    lines.extend(_unwritten(unwritten, _bare))
    lines.append(_headline(record.counts, FIX_SPLIT))
    for refusal in record.refused:
        subject = f"{refusal.path}: " if refusal.path else ""
        lines.append(f"Not written: {subject}{refusal.detail}")
    lines.extend(_guidance(guides))
    # Type narrowing only: `RunRecord` rejects a plan or apply without a verification.
    assert record.verify is not None  # noqa: S101 - see above
    if applying:
        lines.append(_verdict(record.verify))
        lines.extend(f"Hint: {hint}" for hint in _hints(record.verify, _bare))
    if record.model is not None:
        lines.append(_consulted(record.model))
    lines.append(f"Evidence: {evidence}")
    if applying and locks:
        lines.append(
            f"Next: regenerate each lock file with the tool that made it: {', '.join(locks)}. "
            f"obelize does not edit them, so they may still pin the old release."
        )
    lines.extend(_next(record, plan, evidence, repo, packs))
    return lines


def _check(plan: PlanDocument, files: set[str], applying: bool = False) -> list[str]:
    """One line per warning on an edit that is, or would be, written: `auto` never withholds.

    An edit's line is the one before the change, which a written file no longer has.
    """
    note = " (line before the change)" if applying else ""
    return [
        f"Check {edit.path}:{edit.line}{note}: {code}: {WARNING_MEANINGS[code]}"
        for edit in plan.edits
        if edit.status == "auto" and edit.path in files
        for code in edit.warnings
    ]


def _left(record: RunRecord, held: ManifestPlan, evidence: str) -> list[str]:
    """Why findings were left for you, from the cause down.

    Counted by cause: an atomicity row counts for each reason its file was held, and is not
    counted for itself while another reason exists. The rows named are the causes, not the rows
    they held.
    """
    if not record.withheld:
        return []
    atomic = {ATOMICITY_BAIL, REPO_ATOMICITY_BAIL}
    codes = Counter(code for row in record.withheld for code in row.caused_by or (row.bail,))
    concrete = Counter({code: count for code, count in codes.items() if code not in atomic})
    top = (concrete or codes).most_common(3)
    reasons = ", ".join(f"{code} ({count})" for code, count in top)
    lines = [
        "",
        f"{len(record.withheld)} finding(s) left for you. Most common reasons: {reasons}.",
        *(f"  {code}: {BAIL_ACTIONS[code]}" for code, _ in top),
    ]
    roots = [row for row in record.withheld if row.bail not in atomic]
    lines.extend(
        f"  {row.path}:{row.line}  {row.symbol or '--'}  {row.bail}" for row in roots[:ROOT_ROWS]
    )
    if len(roots) > ROOT_ROWS:
        lines.append(f"  and {len(roots) - ROOT_ROWS} more in {_inside(evidence, 'REPORT.md')}")
    named = {row.path for row in record.withheld}
    unread = [path for path in held.blocking if path not in named | set(held.transitive)]
    if unread:
        lines.append(
            f"  Not migrated by obelize, so they hold the pin: {', '.join(unread)}. Migrate them "
            f"by hand, or list one under exclude in .obelize.yml to migrate the rest. A file over "
            f"max_file_bytes is read once you raise it."
        )
    if held.transitive:
        lines.append(
            f"  Import a module only the old distribution installed, which no manifest "
            f"declares: {', '.join(held.transitive)}."
        )
    manifests = {row.path for row in held.findings}
    if any(
        row.bail == REPO_ATOMICITY_BAIL and row.path not in manifests for row in record.withheld
    ):
        lines.append(
            "  This pack moves a whole repository or none of it: fix the rows above by hand, "
            "commit, and run obelize fix --apply again."
        )
    lines.append(f"What each code means: {CODES.format(version=__version__)}")
    return lines


def _guidance(guides: Sequence[Guide]) -> list[str]:
    lines = []
    for guide in guides:
        lines.extend(
            [
                "",
                f"{guide.rule_id}: {guide.findings} finding(s) flagged.",
                f"  {guide.message}",
                f"  Suggestion: {guide.suggestion}",
            ]
        )
    return [*lines, ""] if lines else []


def _next(
    record: RunRecord, plan: PlanDocument, evidence: str, repo: str, packs: Sequence[str]
) -> list[str]:
    """The command after a run, by exit code; a dry run with nothing planned, `3` and `4` with
    none left have none."""
    fix = flags(repo, packs)
    if record.mode != "apply":
        return [f"Next: obelize fix --apply{fix} writes it."] if plan.files else []
    here = PurePath(repo) == PurePath(".")
    flag = "" if here else f" --repo {shell.quote(repo)}"
    git = "git" if here else f"git -C {shell.quote(repo)}"
    run = f"--run {record.run_id}{flag}"
    # Type narrowing only: `RunRecord` rejects an apply without a verification.
    assert record.verify is not None  # noqa: S101 - see above
    if record.exit_code == 0 and record.file_edits:
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
            f"obelize undo {run}, then obelize fix --apply{fix}, install what it writes, and "
            f"run obelize verify --run <new id>{flag} {_tests()}."
        )
    elif record.exit_code == 6:
        step = (
            f"install what this run wrote into the manifest in your project's environment, "
            f"then obelize verify {run} {_tests()} checks the change with your tests."
        )
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
    if "tree_dirty" in codes and record.git_dirty is False:
        return (
            "your verification commands changed tracked files; stop them writing there, "
            "or run again with --allow-dirty."
        )
    if "tree_dirty" in codes:
        return "commit or stash your changes, or run again with --allow-dirty."
    if "tree_unknown" in codes:
        return f"run {git} status to see why git failed, or run again with --allow-dirty."
    if verify.reason == "policy_refused":
        return f"obelize verify {run} --trust-repo-config runs the commands in .obelize.yml."
    if record.file_edits:
        # A race stopped the write partway: some files hold the migration and some do not.
        return (
            f"obelize undo {run} puts back the file(s) that were written; fix what the Not "
            f"written line names, then run again."
        )
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
    return printable(row.removesuffix("\r"), allowed="\t")


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
        *_edited(record.verify),
        f"Evidence: {evidence}",
    ]


def _edited(verify: VerifyRecord) -> list[str]:
    """Where `--current` checked a tree that is no longer the one the run wrote."""
    if not verify.edited:
        return []
    return [f"The tree differs from what the run wrote in {len(verify.edited)} file(s):"] + [
        f"  {printable(path)}" for path in verify.edited
    ]


def reverted(record: UndoRecord, folder: str, evidence: str) -> list[str]:
    """`obelize undo`'s output; a skipped file lists both hashes and the kept original to diff.

    A snapshot is named by its sha256, so a file whose hash is that name holds the original.
    """
    done = [row for row in record.files if row.outcome == "reverted"]
    held = [row for row in record.files if row.restored and row.outcome != "reverted"]
    lines = [f"obelize undo  {record.run_id}", ""]
    for row in record.files:
        lines.append(
            f"  {row.path}  {row.outcome}"
            + (f"  {row.reason}" if row.reason else "")
            + ("  (already the original)" if row in held else "")
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
        f"{len(done)} of {len(record.files)} file(s) put back"
        + (f"; {len(held)} already held the original." if held else "."),
        f"Evidence: {evidence}",
    ]


def superseded(document_text: str, record: RunRecord, when: str) -> str:
    """The report plus one note naming the current verdict; a repeat replaces the note.

    The report cannot be rebuilt: its scan and driver run are not in the folder. It says whether
    tests ran before the change, which a re-verified record no longer does.
    """
    assert record.verify is not None  # noqa: S101 - only a re-verification supersedes
    head, found, tail = document_text.rpartition(f"\n{_NOTE}")
    body = (head if found and _ONE_LINE.fullmatch(tail) else document_text).rstrip("\n")
    verdict = f"`{record.verify.status}`" + (
        f" (`{record.verify.reason}`)" if record.verify.reason else ""
    )
    # Said in the same line: a repeat replaces the note as one heading and one paragraph.
    edited = (
        f" The tree had changed since the run in {len(record.verify.edited)} file(s) it wrote."
        if record.verify.edited
        else ""
    )
    # One line, since a repeat finds the note as a heading and one paragraph; a newline in a
    # command is spelled out.
    ran = ", ".join(_code(printable(row.command)) for row in record.verify.commands)
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
            _NOTE,
            f"`obelize verify` checked this run again at {when}: {verdict}"
            + (f", with {ran}" if ran else "")
            + f".{edited} The section above shows the first result; `run.json` and "
            f"`verify/verify.json` hold the new one. {before}",
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
    rows = () if verify.baseline is None else verify.baseline.commands
    return [
        *(
            f"{code(row.command)} {'timed out' if row.reason == 'timeout' else 'failed'}, and "
            "its program came from the environment obelize runs in, which may not be your "
            "project's. To run your project's tests, name its interpreter: "
            f"{code(_venv_tests())}."
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
        *(
            f"{code(row.command)} timed out. To allow it longer, pass "
            f"{code('--timeout <s>')}; the default is {TIMEOUT_S} seconds."
            for row in (*rows, *verify.commands)
            if row.reason == "timeout"
        ),
    ]


def document(
    record: RunRecord,
    scan: Scan,
    run: Run | None = None,
    plan: PlanDocument | None = None,
    proposals: Sequence[ProposalRecord] = (),
    guides: Sequence[Guide] = (),
    packs: Sequence[PackDocument] = (),
    fixture_dirs: Sequence[str] = (),
    locks: Sequence[str] = (),
) -> str:
    """`REPORT.md`: everything the run learned, in the order it learned it.

    `run` (driver output) and `plan` must match the mode, else ValueError. A fix keeps the findings
    table beside the edits: a file the scan refused has no edit, and that is not a hole.
    `proposals` (from `model/`) are inlined because model hunks most need a human reader. `guides`
    and `packs` are the packs' own words: what a flagged change says, what a pack does not handle.
    `fixture_dirs` are the fixtures of the loaded packs inside the repository, which no scan enters;
    `locks` are the lock files beside a manifest pin that was or would be written, or above it.
    """
    _agree(record, run, plan)
    lines = _preamble(
        record,
        scan,
        run is not None,
        planned=plan is not None and bool(plan.files),
        fixture_dirs=fixture_dirs,
    )
    if scan.blocked:
        lines.extend(["## Blocked", ""])
        for blocked in scan.blocked:
            lines.extend([_blocked(blocked, _code), ""])
    if scan.assumed:
        lines.extend(["## Assumed", "", *_assumed(scan.assumed, _code)])
    if run is not None and plan is not None:
        lines.extend(_changes_section(record, plan))
        lines.extend(_edits_section(run))
        lines.extend(_refused_section(record))
        lines.extend(_findings_section(run.findings))
    else:
        lines.extend(_findings_section(scan.findings))
    lines.extend(_withheld_section(record))
    lines.extend(_guidance_section(guides))
    lines.extend(_manifest_section(scan.manifests if run is None else run.manifest_plan))
    if locks:
        lines.extend(
            [
                f"Not edited by obelize, so they may still pin the old release: "
                f"{', '.join(map(_code, locks))}. Regenerate each with the tool that made it.",
                "",
            ]
        )
    if record.verify is not None:
        lines.extend(_verification_section(record.verify, packs))
    if record.model is not None:
        lines.extend(_model_section(record.model, proposals))
    lines.extend(_limitations_section(record, packs, scan.unwritten))
    return "\n".join(lines).rstrip("\n") + "\n"


def _agree(record: RunRecord, run: Run | None, plan: PlanDocument | None) -> None:
    if (record.mode == "scan") == (run is None and plan is None):
        return
    raise ValueError(
        f"a {record.mode!r} record was rendered with "
        f"{'a' if run is not None else 'no'} driver run and "
        f"{'a' if plan is not None else 'no'} plan; the mode says which it needs"
    )


def _preamble(
    record: RunRecord, scan: Scan, fixing: bool, *, planned: bool, fixture_dirs: Sequence[str]
) -> list[str]:
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
        *(
            f"- **Not scanned** `{path}/`, the fixtures of a pack this run loaded"
            for path in fixture_dirs
        ),
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
        return [*lines, "No rule planned an edit in this repository.", ""]
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


def _verification_section(verify: VerifyRecord, packs: Sequence[PackDocument]) -> list[str]:
    lines = [
        "## Verification",
        "",
        f"**{verify.status}**" + (f" (`{verify.reason}`)" if verify.reason else ""),
        "",
    ]
    for hint in _hints(verify, _code):
        lines.extend([f"**Hint:** {hint}", ""])
    # A dry run has no phase to show; each pack suggests the same tests, so say them once.
    if verify.reason != "dry_run":
        if verify.baseline is not None:
            lines.extend(_phase_rows(_BASELINE, verify.baseline))
        lines.extend(_phase_rows("After the patch", verify))
    suggested = list(
        dict.fromkeys(
            text for pack in packs if pack.verification for text in pack.verification.suggestions
        )
    )
    if suggested:
        lines.extend(
            [
                "Suggested by the packs, not run:",
                "",
                *(f"- {_prose(text)}" for text in suggested),
                "",
            ]
        )
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
        command = row.command.replace("|", "\\|")  # a pipe splits a cell, even in a code span
        lines.append(
            f"| `{command}` | {row.source} | {row.status} "
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
    # Every code the table shows, in the order it first appears.
    shown = dict.fromkeys(
        code for row in record.withheld for code in (row.bail, *(row.caused_by or ()))
    )
    return [
        *lines,
        "",
        "What to change, by reason:",
        "",
        *(f"- `{code}`: {BAIL_ACTIONS[code]}" for code in shown),
        "",
    ]


def _prose(text: str) -> str:
    """Pack text for Markdown: a viewer then shows it as written and runs none of it."""
    return _MARKUP.sub(r"\\\g<0>", text)


def _guidance_section(guides: Sequence[Guide]) -> list[str]:
    if not guides:
        return []
    lines = ["## Guidance", "", "What each pack says about the findings it flagged.", ""]
    for guide in guides:
        lines.extend(
            [
                f"### `{guide.rule_id}`",
                "",
                f"{guide.findings} finding(s). {_prose(guide.message)}",
                "",
                f"**Suggestion:** {_prose(guide.suggestion)}",
                "",
            ]
        )
    return lines


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
    if plan.transitive:
        lines.extend(
            ["", "Importing a module only the legacy distribution installed:", ""]
            + [f"- `{path}`" for path in plan.transitive]
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
        detail = _prose(" ".join((row.detail or "").split())) or "--"
        lines.append(
            f"| {row.index} | `{row.path}:{row.line}` | `{row.outcome}` | "
            f"{f'`{word}`' if word else '--'} | {detail} |"
        )
    return [*lines, ""]


def _limitations_section(
    record: RunRecord,
    packs: Sequence[PackDocument],
    unwritten: Sequence[tuple[str, tuple[int, ...]]] = (),
) -> list[str]:
    if not record.limitations:
        lines = ["## Limitations", "", "Every selected path was read.", ""]
    else:
        lines = ["## Limitations", "", "| Path | Code | Detail |", "|---|---|---|"]
        for row in record.limitations:
            lines.append(
                f"| {f'`{row.path}`' if row.path else '--'} | `{row.code}` | {_prose(row.detail)} |"
            )
        lines.append("")
    lines.extend(_unwritten(unwritten, _code))
    for pack in packs:
        lines.extend(
            [f"What `{pack.id}` says it does not handle (its guide: {pack.source.url}):", ""]
        )
        lines.extend([*(f"- {_prose(text)}" for text in pack.limitations), ""])
    return lines


def why_blocked(blocked: Blocked) -> str:
    """The sentence for a terminal: why a pack plans nothing, and what to change."""
    return _blocked(blocked, str)


def _blocked(blocked: Blocked, code: Callable[[str], str]) -> str:
    """Why a pack plans nothing, what to change, and that in git the change is committed first.

    A pin moves a legacy release, not the code that runs on the old one: a class the new release
    removed raises there, so the call sites are ported before the pin is.
    """
    ported = (
        " A pin moves the release, not the code: a call to a name that release removed has to be "
        "ported first."
        if blocked.reason == "legacy_version_unsupported"
        else ""
    )
    return (
        f"{_stop(blocked, code)}{ported} To apply it in a git repository, commit that change "
        f"first: {code('fix --apply')} refuses uncommitted changes unless you pass "
        f"{code('--allow-dirty')}."
    )


def _stop(blocked: Blocked, code: Callable[[str], str]) -> str:
    needed, package = code(blocked.needed), code(blocked.package)
    if blocked.reason == "runtime_unsupported":
        path = code(blocked.path)
        return (
            f"{path} declares Python {code(blocked.declared or '')}, which allows versions "
            f"{package} does not install on, so this migration reports its findings and plans "
            f"no change. To migrate, raise the minimum in {path} to {needed} and run again."
        )
    if blocked.reason == "new_version_unsupported":
        path = code(blocked.path)
        return (
            f"{path} declares {package} {code(blocked.declared or '')}, which admits no release "
            f"this migration writes ({needed}), so it reports its findings and plans no change. "
            f"To migrate, raise it to {needed} in {path} and run again."
        )
    if not blocked.path:
        return (
            f"No manifest declares {package}, so the version in use is not known and this "
            f"migration reports its findings and plans no change. To migrate, declare "
            f"{code(f'{blocked.package}{blocked.needed}')} in a manifest obelize reads, such as "
            f"{code('requirements.txt')}, and run again."
        )
    path = code(blocked.path)
    if blocked.declared is None:
        return (
            f"{path} declares {package} in a form obelize cannot read, so this migration "
            f"reports its findings and plans no change. To migrate, write it as a plain "
            f"requirement such as {code(f'{blocked.package}{blocked.needed}')} in {path} and "
            f"run again."
        )
    declared = code(blocked.declared) if blocked.declared else "with no version"
    if blocked.evidence:
        took = (
            f"a release in {code(blocked.taken)}"
            if blocked.taken
            else f"the newest release of {package}"
        )
        return (
            f"{path} declares {package} {declared}, which this migration would take as {took}, "
            f"but {code(blocked.evidence)} suggests another release is in use, so it reports its "
            f"findings and plans no change. To migrate, pin {package} to {needed} in {path} and "
            f"run again."
        )
    if blocked.unlisted:
        return (
            f"{path} declares {package} {declared}, which this migration would take as the newest "
            f"release of {package}, but obelize lists every file only at the top of a git "
            f"repository and this run was not at one, so a file that names another release may "
            f"be unseen. It reports its findings and plans no change. To migrate, run it from "
            f"the top of the git repository, or pin {package} to {needed} in {path} and run again."
        )
    return (
        f"{path} declares {package} {declared}, which allows versions this migration does not "
        f"cover, so this migration reports its findings and plans no change. To migrate, pin "
        f"{package} to {needed} in {path} and run again."
    )


def _assumed(assumed: Sequence[tuple[str, str]], code: Callable[[str], str]) -> list[str]:
    """What was taken for a version nobody wrote down, said where the plan is.

    A release is the pack's newest; a range, which starts with an operator, is what the code
    that uses a name only those releases define stands for.
    """
    lines = [
        (
            f"{code(package)} is declared with no version that rules out {code(release)}, so this "
            f"migration takes it as {code(release)}, its newest release. A repository that "
            f"installs an older one needs that pinned in a manifest obelize reads."
            if release[:1].isdigit()
            else f"{code(package)} is declared with no version that rules out a release in "
            f"{code(release)}, and the code uses a name only those releases define, so this "
            f"migration takes it as one of them. A repository that installs another needs that "
            f"pinned in a manifest obelize reads."
        )
        for package, release in assumed
    ]
    return [*lines, ""] if lines else []


def _unwritten(
    unwritten: Sequence[tuple[str, tuple[int, ...]]], code: Callable[[str], str]
) -> list[str]:
    """The files that use the legacy API and that obelize does not write, and the cells."""
    named = [
        code(path)
        + (f" (cell{'s' if len(cells) > 1 else ''} {', '.join(map(str, cells))})" if cells else "")
        for path, cells in unwritten
    ]
    if not named:
        return []
    return [
        f"These files use the legacy API and obelize does not write them: {', '.join(named)}. A "
        f"notebook's code cells are read and never rewritten, and a file that is no code it can "
        f"read is not analysed. Migrate them by hand.",
        "",
    ]


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
        f"{len({(row.path, row.line, row.column) for row in plan.findings})} dependency "
        f"declaration(s)"
        + (
            f", blocked by {len(plan.blocking)} file(s) that still import it: "
            + ", ".join(plan.blocking[:3])
            + (", ..." if len(plan.blocking) > 3 else "")
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
        # An eligible row says why only in the report: the code is no reason to wait.
        reason = finding.bail or (
            "" if finding.scan_status == "eligible" else finding.confidence_reason
        )
        rows.append(
            f"    {finding.line:>{width}}  {finding.kind:<{kind}}  "
            f"{_symbol(finding):<{symbol}}  {finding.scan_status:<12}  {reason}".rstrip()
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
    "why_blocked",
    "withheld_rows",
]
