# ADR-044: Error analysis

## Status

Accepted.

## Decision

### D1. The row-level record is collected once and committed, and the analysis
is a join that reads it

`bench/errors_collect.py` writes `bench/results/errors/round-<n>.json` from the
round's run folders: every finding, every withheld row with its bail and
`caused_by`, and every position an edit landed on. `bench/errors.py` joins it
with `bench/cases.yaml` and `bench/errors.yaml` offline, and
`tests/unit/test_bench_errors.py` recomputes it in CI, because a number nobody
can recompute cannot be checked.

The collector refuses a checkout without exactly one run folder, and a run whose
`git_sha`, pack sha256 or obelize version differs from the published result; the
model with nothing lifted must reproduce the published 25 migrated rows. A
finding's `evidence` is never collected: it can quote a stranger's source.

### D2. Three dispositions, a closed set, and a test that closes it

Every cause gets exactly one of `rule_change`, `scan_change` or `limitation`,
by hand in `bench/errors.yaml`, and the test checks both directions: every cause
the round holds has an entry, and every entry names a cause the round holds. A
fourth option would make the promise unfalsifiable, and a dead entry outlives
the failure it was written for.

### D3. A limitation names an ADR; a change names an open COVERAGE gap

`recorded` is one token the test resolves. A `limitation` names an existing ADR,
where the refusal is argued. A `rule_change` or `scan_change` names a numbered,
unstruck gap in `tests/fixtures/scan/COVERAGE.md`, the register for decisions
not yet taken, with a `*Closes:*` clause saying what would settle it.

### D4. The lever, and the two properties that make it evidence

A cause's **lever** is the round recomputed with that cause alone fixed: its
rows become eligible, F-1 and F-2 apply again, and the gain in migrated rows is
reported. Asserted: nothing lifted reproduces the published count, and
everything lifted stops at 252 of 277, short by exactly the 25 rows no pass
reported. Levers do not add up (`local_import` +26 and
`multiple_configure_calls` +0 alone, +54 together), so no total or share of a
row is printed: fixing half a file's causes unblocks none of it.
A lever is also an upper bound. A rule refuses at its first failed check, and a scan-time
refusal hides every fix-time one, so a refusal behind the recorded cause is not in the record:
simulating `local_import` alone released none of its published +26.

### D5. What the round found, and what it changes

Four causes are rule changes and four are scan changes (two on existing gaps 22
and 25); the rest are limitations, and gaps 28 to 33 carry the other six. A
disposition sits beside each lever instead of a ranking:
* `generation_config_not_static` (C-31) is one of the two largest levers, each
  row a name assigned once, where ADR-012 D6 predicted zero (gap 29).
* `multiple_configure_calls` is worth nothing alone: each of its files also
  carries `local_import`.
* `alias_collision` is worth nothing alone either: its file also carries three
  `client_placement_ambiguous` rows (gap 31).
* `history_parts_shape_incompatible` must not be taken: its rows pass
  `str(time.time())`, which is not a history in either SDK.

The counts and levers are in the generated table of `BENCHMARK_RESULTS.md` and
nowhere else, since `tests/unit/test_bench_errors.py` recomputes that table and
cannot recompute a number written into prose.

### D6. A key that turns out to be wrong is corrected in place and said out loud

A wrong answer key is none of D2's three: it is corrected in `bench/cases.yaml`,
in the row's own `why`, naming what it used to say. The round is republished
only when a published number moves.

### D7. The three dispositions are about causes, and the ceiling is about cases

Lifting every bail migrates 252 of 277 rows and completes 12 of 20
repositories, each still capped below `verified_success` (ten by no test
command, one by a `manual` row, one by a flagged line). The analysis does not
move gate 4, and is not offered as if it might.

## Consequences

* `docs/BENCHMARK_RESULTS.md` carries the analysis as a generated block.
* An analysis changes nothing in `src/obelize/`, or it invalidates its round.
* Dispositions are per round (`round: 1`); a case that errored needs a fifth
  row state, which nothing handles.
* Open: gaps 28 to 33 and round 2, not planned.
