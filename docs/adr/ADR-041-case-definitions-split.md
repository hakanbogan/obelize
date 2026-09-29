# ADR-041: Case definitions and split

## Status

Accepted.

## Decision

### D1 -- A case is a candidate somebody has read

A case adds to a candidate the two SDK pins, the interpreter key, install and test commands, the
split, the `pattern_key`, a ground truth, a reviewer and a date. The ground truth is written by
hand from the source before its scan is read, and every disagreement with the scan is published
(D10), since a copied key would agree everywhere. Repository facts are copied into
`bench/cases.yaml`, and a test asserts they equal the corpus. The pins are frozen for the round at
`0.8.6` and `2.24.0`, the versions `pack.yaml` was measured against.

### D2 -- A `google-genai` row is not a declaration (correction to ADR-040 D11)

`manifest-dependency` reports the pin it removes and the pin it adds at one position, so only a
`google-genai` row where no legacy pin sits is a declaration (`declares_the_new_sdk`, not
`proposes_the_new_sdk`). The already-migrated control is therefore drawn for (D9).

### D3 -- Which candidates become cases was decided before the first checkout

Twenty, in this order: candidates with a Python test file, those drawn for a pack surface, each
change's only witness, one per unseen scanner `pattern_key`, then a systematic sample
(`bench/cases.py::chosen`). Fixed before any clone, so no case is picked by content.

### D4 -- `auto` and `manual` are judgements about the code, not predictions about the tool

`auto` means a correct edit follows from the code alone, whatever the scanner does, so an `auto`
row the scanner bails on is a pre-registered miss. `manual` rows, whose edit needs more than the
call site, always give a reason.

### D5 -- The split is hashed, and stratified on whether there is a test file

Whole owners go to the holdout. Per stratum (with and without a Python test file), repositories
sort by `sha256(full_name)` and their owners are taken in that order until the holdout holds at
least a third of the stratum (`bench/cases.py::split`), so nobody picks a side and both sides keep
verifiable cases.

### D6 -- `pattern_key` comes from the ground truth, and both keys are published

A case's `pattern_key` is the sorted legacy symbols of its ground-truth call sites of actionable
kinds, because a scanner key would shrink with each miss and flatter the rate. The scanner's key
is published beside it.

### D7 -- A case with no test command is kept, not retired

Only a candidate that cannot be a case (gone, unresolvable SHA, changed licence) is retired.
`test_cmd` exercises the changed code with no credentials or network, or is `null` with a reason.
A case without one stays, capped at `patched_unverified`, and the headline is also reported over
the verifiable subset with its own `n`.

### D8 -- `install` exists to make `test_cmd` runnable

A case with no test command installs nothing but the pins. Otherwise install lines are read from
the repository's own manifest and reviewed; one that fails in a run errors its case rather than
being quietly repaired.

### D9 -- What T27 draws for itself, and why it is not appended to the corpus

Dated draws under ADR-040's rules, each with verbatim query, hit count, number examined and skip
reasons: repositories whose tests name the SDK, and one query per control shape (already on
`google.genai`, the two Vertex origins drawn apart per C-24, prose only). A control is confirmed by
a scan with no actionable finding or pin, plus a witness line. The draws live in
`bench/cases_draws.yaml`, not in `bench/candidates.yaml`, whose dated draw is never edited.

### D10 -- Generated, checked, and recomputed by a test that does not read the document

`bench/cases.py` renders the `bench/CASES.md` block and `--check` fails when it is stale;
`tests/unit/test_cases.py` recomputes selection, split and the key-against-scanner table.

### D11 -- The labelling grep, and what widening it cost

A reviewer opens every file matching, case-insensitively, the SDK spellings and the legacy method,
function and type names, plus every manifest, and lists them in `files_read`, because code can
reach the SDK through a wrapper with none of the SDK's tokens.

## Consequences

- Few cases can reach `verified_success`, and that ceiling is published beside the headline.
- Open: `bench/summarize.py` groups the second denominator by a wider key than D6's (every
  call-site kind plus manifests).
