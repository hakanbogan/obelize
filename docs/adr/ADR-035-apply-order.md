# ADR-035: Apply order

## Status

Accepted.

## Decision

### D1 -- the tree and path gates are asked before the baseline, and again at the write

`obelize fix --apply` asks `fsutil.gate` (the tree and path gates, writing
nothing) and starts the baseline only when it answers `None`; `fsutil.apply`
asks both again at the write and is the authority. An apply the gate refuses
records `verify: not_run`, reason `no_changes_to_verify`, no commands and no
baseline. Because a refused apply must not have run somebody's test suite. An
apply `fsutil.apply` refuses after the baseline ran keeps that baseline under
the same verdict, so the record and the summary count the commands that ran.

### D2 -- a refused verification does not stop the write

When ADR-007 declines a command, the patch is written and the run exits `5`
with `verify` `not_run` / `policy_refused`. Because a run that wrote nothing
would read like a repository needing no work, and `refused[]` (ADR-034 D6) is
about files and has no word for a command.

### D3 -- a baseline that did not pass does not stop the write either

A failing baseline stops the after-phase (ADR-033 D7), not the patch: the run
is `inconclusive`, reason `baseline_failed`, exits `6`, and `file_edits` is
full. Because the suite was red before obelize touched anything, and the user
asked for a migration.

### D4 -- "review items outstanding" is anything withheld

Exit `4` means an apply wrote nothing or `report.withheld_rows(run.findings)` is
non-empty, which is `run.json`'s `withheld[]` (`needs_review` and `unsupported`).
It is the ordinary outcome of an apply on a real repository; `0` means the whole
repository migrated, and a dry run exits `0` whatever it withheld (ADR-011 D3).

### D5 -- `obelize verify` replaces what it re-measured and keeps what it did not

It rewrites `run.json`'s `verify`, `exit_code` and `timings.verify_ms`, replaces
`verify/after/` and `verify/verify.json`, and touches nothing else: not
`verify/baseline/`, not `.obelize/latest`. The new record carries no baseline.
`REPORT.md` is not rebuilt; one block after a marker says the verdict was
replaced and where the current one is, and a later re-verification replaces that
block. When the run's own failed baseline gated it, nothing is re-run or rewritten.

### D5.1 -- a run that writes nothing never consults the trust ladder

An apply with nothing to write records `no_changes_to_verify` without resolving
a verification command (ADR-011 D1.3). Because an interactive run must not
prompt about a command it will never run.

### D6 -- `obelize verify` reads its commands from the configuration, never from the folder

The trust ladder is asked again over its usual three sources, never
`run.json`'s recorded commands, so `obelize verify` takes `--verify`,
`--timeout`, `--non-interactive` and `--trust-repo-config`. Because a forged
run folder would otherwise choose what obelize executes (TM-9).

### D7 -- `undo.json`, and a row for every file

`obelize undo` writes one `UndoFile` per `file_edits[]` row, skipped ones
included, and no summary count. `UndoSkip` has seven words: the path guard's
five, `hash_mismatch` (edited after the run; ADR-011 D4) and `snapshot_unusable`
(copy absent or not hashing to its name). The snapshot is checked against its
name before it is written back. Because a list of successes would make a
partial undo read as complete.

### D8 -- three corrections to `docs/CLI.md`

- `--no-snippets` is not a flag: `Finding.evidence`, the field it would switch
  off, is never written. It arrives with what it disables.
- The model flags (`--model`, `--accept-model`, `--show-context`) are ADR-039 D1's.
- `fix --json` writes `plan.json`'s exact bytes to stdout and the evidence path
  to stderr, `obelize scan --json`'s rule (ADR-023 D2).

## Consequences

- ADR-039 D3 puts the model pass after the tree gate, so an apply the tree refused sends nothing.
- `.github/workflows/e2e.yml` accepts `0` or `4` from each `fix --apply`.
- `undo` has no `--force` (ADR-011 D4); a formatter that touches every written file is what would reopen it.
