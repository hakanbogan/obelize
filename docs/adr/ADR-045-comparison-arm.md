# ADR-045: The comparison arm

## Status

Accepted.

## Decision

### D1. The arm is one agent, one prompt, and the prompt is in the repository

`bench/COMPARISON_PROMPT.md` is all the arm is told: one text for every case,
three substituted paths, and its leading comment stripped.
`bench/comparison_collect.py` renders it when the arm is prepared and again when
it is read back, and refuses a case whose copy differs: a drifted prompt is two
experiments. The arm is a general-purpose coding agent with filesystem and shell
tools, no context from this project, one case per run, thirteen runs. It gets
the repository at the pinned commit and a snapshot of the official migration
guide; never the pack, the vocabularies, the coverage register, the keys, or word
that a benchmark exists.

### D2. What blind means here, and the half of it that is a declaration

Blindness is structural in three ways: the agent starts with no context, the
committed prompt is case-independent, and its working directory is a digest of
the case id. It is not sandboxed from this repository: nothing points it there,
but that is an absence of motive, not of access. What a reader can check is the
result: an arm that had read the keys would not leave rows they name.

### D3. One instrument for both arms, calibrated against the one that exists

A key row is **cleared** when the shipped scanner, run on the tree afterwards,
no longer reports it, matched on `(path, kind, symbol)` because an edit moves
lines. Rows the scan misses on the untouched tree are credited to neither arm
but stay in *corrections left*. `tests/unit/test_bench_comparison.py` asserts
that obelize's cleared count equals the one from its plan and withheld list,
case by case, which licenses scoring an arm with no plan. Blind spots:
correctness (D4), and legacy usage rewritten into a shape the scanner misses.

### D4. A correction is a row, and the review is a file of its own

> corrections = key rows still legacy + edits the review rejected

A row, not BENCHMARK.md's hunk, because a hunk needs a gap parameter nobody can
justify. The review is `bench/comparison.yaml`, per arm per case: a `reviewed`
note and a `wrong` list naming each rejected edit and why. `patch_correct` is
derived from it, and `null` for an arm that changed no file. Nothing goes into
`bench/cases.yaml`, whose round is frozen: a judgement made after a round stays
out of the oracle written before it.

### D5. Where the protocol had a choice, it was made in the other arm's favour

For the arm: one guide snapshot for all cases, converted to text by a committed
function; no time or step limit; off-key edits go to the review instead of
failing mechanically. Symmetric, not handicaps: one pass over source only, with
no install and no test run, since obelize's round runs no `--verify`; and no
network beyond the guide, because live search is unreproducible.

### D6. Reproducibility is measured, not asserted

Three cases run a second time from the same bytes in a fresh tree, and the
table reports whether the files, the line counts and the rows cleared match.
Obelize's answer is settled: two runs on one input are byte-identical
([ADR-008](ADR-008-scanner-and-codemod-corrections.md)). Three suffice, because
divergence is a property of the arm, not of the case.

### D7. The ceiling caps a rule, and the arm found the difference

Eleven of thirteen ceilings are `no test command`, which caps any arm. The other
two are a `manual` key row, which caps what a **rule** may be trusted to write
([ADR-041](ADR-041-case-definitions-split.md)
D4), not a tool using judgement: on `LucasHJin/vit` the arm migrated all eight
`manual` rows and the suite passes (`verified_success`); on
`humanbound/humanbound-firewall` it broke a passing suite. So the section
reports rows cleared, corrections left, rejected edits, runtime and
reproducibility, with `verified_success` beside the ceiling, not instead of it.

## Consequences

* `docs/BENCHMARK_RESULTS.md` renders `bench/results/comparison/round-1.json`;
  round one's results do not change, and CI recomputes the scoring, not the arm.
* Every number is one agent, one day, one guide snapshot; another agent is
  another column.
* Open: `ceiling()` says "no rule can reach this" and "nothing can" in one string.
