# ADR-061: Reach

## Status

Accepted.

## Decision

obelize is offered to the places where migrations are already decided: a CI job, a code scanning
view and a coding agent. Each is a way to read or call what the commands already do, and none adds
a way to write. The decisions below are numbered as they land.

### D1. SARIF is a view of the findings

`obelize scan --sarif` prints the findings as SARIF 2.1.0 instead of the table, as `--json` prints
them as JSON, and the two cannot be combined. A result is a finding that is not `not_a_usage`. Its
rule is the code that withheld it, or `eligible`, so a viewer groups places by what to do about
them, and its level says how much a person must do: `note` where obelize can write the migration,
`warning` where it needs review, `error` where no change can express it. The document holds nothing
time-derived, so two scans of one input print the same bytes, and it names the packs in a property.
It is written from the scan in memory and not stored in the run folder, which keeps one format of
record.

### D2. A scan can fail a job

`--fail-on <status>` takes `eligible`, `needs_review` or `unsupported`, repeatable, and exits `4`
when any finding has one of them. `4` already means that manual review is required. `not_a_usage`
is context and cannot be named. The run folder records the exit code the process returns, so
`run.json` and the shell agree. A scan with no `--fail-on` exits `0` as before.

### D3. `--json` on `verify` and `undo` prints the file the command wrote

`verify --json` prints the bytes of the `run.json` it wrote and `undo --json` those of `undo.json`,
so a program reads the record that is on disk and the existing schemas describe it. The exit code
is the verdict's, and the run folder's path goes to stderr, as for `scan --json`.

## Consequences

`docs/CLI.md` documents the flags and replaces its CI recipe, which parsed the JSON with a one-line
script, with `--fail-on`.
