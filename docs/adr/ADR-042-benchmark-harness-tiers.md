# ADR-042: Benchmark harness and tiers

## Status

Accepted; amended by ADR-043 (D3, D8, D10, D11).

## Decision

### D1 -- The harness owns both test runs, and `obelize fix` is given no `--verify`

Step 6 runs `obelize fix --apply --non-interactive --model none --json` with no `--verify`, because
the SDK swap comes after it and obelize's own after-phase would fail every case. The harness runs
the baseline and the after-run either side of the swap. Exits `0`, `4` and `6` are all accepted;
the grade is read from the run folder.

### D2 -- The compile gate obelize skips is run by the harness, on the case's interpreter

`obelize fix` compiles written files only when a verification command is set, so the harness
compiles them with the case's interpreter and records `patch_compiles`: `false` is `wrong`, `null`
when nothing was written. The gate belongs in `obelize fix` (`tests/fixtures/scan/COVERAGE.md` gap 26).

### D3 -- A tier is computed from the record, and a reviewer's answer is a field of it

`human_edits` and `patch_correct` come from the case's `review` and stay `null` until read; a null
is never a zero or a true. Tiers, in order: `error`; `wrong` (patch judged incorrect, uncompilable,
a false-positive edit, or a passing suite failing after a written patch; without a patch a failure
measured the swap); `unsupported` (nothing written); `partial` (a key row unmigrated);
`verified_success` (no false positive or miss, `human_edits` 0, covering tests, both runs `pass`, a
test executed); else `patched_unverified`.

### D4 -- A key row is matched on its symbol, not on its position

A key row is migrated when the run refused nothing at `(path, line, symbol)` and an edit landed on
`(path, line)`, because one manifest line can hold an applied and a withheld row (ADR-010 F-2).

### D5 -- The comparison is the one `bench/CASES.md` already publishes

`detected`, `false_positive` and `missed_call_site` use `gate1_score.rows` and `compare` over
`ACTIONABLE_KINDS`, so a round and the agreement table are one measurement.

### D6 -- `--fixtures-only` runs the offline half, and its executor refuses the network

In fixtures-only mode the one executor refuses any program but the running interpreter before it
starts, so `bench-smoke` cannot reach the network. Each fixture's `expected.json` predates the
harness; where it was wrong, the key says so (a method call on a call result is reported, withheld
`receiver_unresolved`).

### D7 -- A fixture ships doubles of both SDKs under `_vendor/`

Two fixtures carry minimal doubles of both SDKs in `_vendor/`, always excluded from scans, so the
offline pass reaches `verified_success`. `wrong` and `error` are covered by the tier tests.

### D8 -- Nothing a repository's test suite printed is committed

Step output goes to `<round>/<id>.logs/` in the work root (ADR-043 D1); a result keeps argv, exit
codes, durations and counts, because a suite's output is nothing
[BENCHMARK.md](../BENCHMARK.md#licensing-and-publication-rules) lets it store.

### D9 -- The round is read from `bench/cases.yaml` and is not a flag

`bench/results/round-<n>/` takes `<n>` from the case file, so two corpora never share a directory;
`--case <id>` re-runs one case.

### D10 -- A reviewed `python` means the case's own interpreter

A leading `python` becomes the case's resolved interpreter (C-15), and the provenance records its
`python_build` (ADR-043 D4).

### D11 -- `passed` and `failed` come from a junit report, or they are `null`

The harness adds `--junitxml` to a pytest command lacking one and reads `passed`, `failed` and
`skipped`; any other command reports `null`, never `0`. Pytest's own exit `2` together with a
nonzero `failed` count also reads as a failed phase, so a migration that breaks the import of the
module under test grades `wrong` instead of the inconclusive result a plain exit-code table would
give it.

### D12 -- The ceiling is published before the round, not explained after it

`bench/summarize.py` renders from the keys alone which cases can reach `verified_success` and what
caps the rest.

## Consequences

- `bench-smoke` runs the fixtures pass and the staleness check.
- `docs/BENCHMARK_RESULTS.md` carries a block `bench/summarize.py` generates and a test recomputes.
- If `obelize fix` learns to verify across an SDK swap, D1 is the decision to undo.
