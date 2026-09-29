# ADR-040: Candidate corpus

## Status

Accepted; amended by ADR-041 (D7, D11).

## Decision

### D1 -- A candidate is what the scanner reported on, not what a search matched

A repository joins only when the shipped `obelize scan` reports a legacy usage in it at the pinned
SHA, not when code search matches it: the scanner is what the benchmark measures. Candidates come
from the gate-1 sample and D5's draws.

### D2 -- No SPDX identifier, no candidate

`none` and `NOASSERTION` are rejected, because unlicensed code cannot be quoted in an error
analysis ([BENCHMARK.md](../BENCHMARK.md#licensing-and-publication-rules)). The licensed share of
the frame is published beside the corpus.

### D3 -- `archived` is recorded and never disqualifies

A frozen repository reproduces; the flag only tells a reader of a `wrong` tier the code is frozen.

### D4 -- A pack surface is a change id together with the legacy symbols its parameters name

A repository exercises a change when a finding at its SHA carries a symbol the change's `pack.yaml`
parameters name (or, for `flag-legacy-module-reached-indirectly`, a pattern). Not grep, which says
whether a token appears, not whether the scanner resolved a usage.

### D5 -- An unexercised surface is resolved three ways, in order, and never by silence

Each change no candidate exercises gets a dated, verbatim code-search query with its hit count and
one outcome: `drawn` (an eligible, scan-confirmed result becomes a candidate), `no_eligible_result`
(with the number examined and why each was passed over) or `absent` (zero hits).

### D6 -- The anti-inflation rules are enforced here, one step before the case

Rejected: forks, a third repository of one owner, development-corpus owners, repositories over
150,000 KB or gone at their SHA, and any that **vendors the legacy SDK's own source** (a finding
under `google/generativeai/`), since its case would migrate the library. Every rejection is
published with its reason.

### D7 -- A candidate is not a case

A candidate is a repository, SHA, licence, owner and scan; pins, install, tests, split and ground
truth belong to the case (ADR-041). A candidate is retired, with a reason and never deleted, only
when it cannot be a case: gone, unresolvable SHA or changed licence. One with no runnable suite
stays, capped at `patched_unverified`.

### D8 -- Whether a repository has a test suite at all is measured now

A repository with no tests cannot reach `verified_success`, and the file list shows it. It is
recorded as path evidence (`test_files`, `test_config`, `ci_workflow`, `manifest`), never as a
judgement of the tests.

### D9 -- `pattern_key` is computed now

The scanner's `pattern_key` (sorted legacy symbols of the call sites) is computed per candidate, so
the second headline denominator is visible before any case runs.

### D10 -- The table is generated, checked, and recomputed by a test that does not read it

`bench/candidates.py` renders the `bench/CANDIDATES.md` block and `--check` fails when it is stale.
`tests/unit/test_candidates.py` recomputes the selection from the frame, the scans and `pack.yaml`.

### D11 -- The negative controls are T27's, and what the scans already know about them is written down here

A repository declares `google-genai` only with a row at a position no legacy pin holds; a row at a
legacy pin's position is `manifest-dependency`'s proposed add. The list is computed from the scans.
Declaring with legacy call sites makes a manifest/code-mismatch candidate; without, control
material. The controls are drawn by ADR-041 D9.

## Consequences

- Every candidate's findings, `pattern_key` and surfaces recompute offline from its scan record.
- The licence rule removes over half the frame and biases the corpus toward licensed repositories.
- Every `pack.yaml` change appears once in the surface table; a pack change that moves its
  symbols needs D5 again.
