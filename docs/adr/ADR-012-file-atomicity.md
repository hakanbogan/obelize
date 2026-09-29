# ADR-012: File atomicity

## Status

Accepted.

## Decision

### D1 -- F-1 wins, and the six rows are amended

The answer keys follow [ADR-010](ADR-010-fixture-oracle-and-atomicity.md) F-1: every row F-1
withholds carries `file_not_fully_migrated`, never the bail of a neighbouring group, because a
shape the oracle grades two ways becomes a contradiction in the code graded against it.

### D2 -- F-1's unit is the file, so the `configure` rows move too

Every otherwise-`auto` finding in a file where another bails is withheld by atomicity
(`file_not_fully_migrated`), not by that group's code, because F-1 leaves the whole file as it
was; a cleanly resolved `configure(...)` is no exception.

### D3 -- `caused_by`

A finding withheld by `file_not_fully_migrated`, and no other, carries `caused_by`: the sorted,
de-duplicated bails of the other findings in its file. It is drawn from findings, never from
the bindings table, because it records what the report lists; without it a reader learns that
a file was skipped and not why. `repo_not_fully_migrated` needs none: F-2 names the files.

### D4 -- atomicity is the last rung of the ladder

A finding names one bail: the most specific rule that fired for it. `file_not_fully_migrated`
says only that something else in the file bailed, so it never displaces a code that names a
concrete defect of the row itself, such as `receiver_unresolved`.

### D5 -- the bails an import finding may carry are a closed list

An `import` or `star_import` finding is the statement, so it may carry only a bail about that
statement, the whole file, or atomicity; the list is [SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md)
§6 and `models.Finding` enforces it. `input_does_not_parse`, `file_too_large` and
`runtime_unsupported` are absent: a file failing an input gate yields one `parse_error`
finding, and a blocked repository proposes no edit to withhold.

### D6 -- ADR-008's "The honest one" paragraph is corrected, not deleted

On the three development-corpus repositories the binding constraint on the automatic rate is
F-1, not ADR-008 D2, D3 or C-31: every legacy file there has at least one bailing usage, so
the automatic edit count is zero, and C-31 buys no additional edit because each of its sites
carries a second, independent bail. ADR-008 carries the correction.

## Consequences

- `caused_by` travels through `findings.json`, `run.json`'s `withheld[]` and `REPORT.md`.
- A test holds every fixture `caused_by` equal to the bails of the other findings in its file.
- §7 of the vocabulary lists the values that belong to more than one closed set, and a test
  fails on any other overlap.
- Dual imports would retire F-1 and most of D1-D5.
