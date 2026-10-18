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

### D4. A library with no pack is listed, never rewritten

`obelize scan --library <distribution>` runs the scanner over a spec made on the spot, with the
modules the distribution installed as its legacy modules and no symbol list, so every import, call
and attribute of the library is a finding. Each is `needs_review` with the new reason
`no_pack_for_usage`, graded at the first rung beside a pack's refusals, and an import may carry it.
The library's lines in a manifest are context (`not_a_usage`), because nothing migrates and no pin
moves. The modules come from `--module`, else from the distribution's `RECORD` in an environment
kept in the repository (a namespace package gives the package under it, not every library that
shares the namespace), else from the distribution's name. Nothing is imported, so reading an
environment runs no code.

The run folder records `source: inventory` and the hash of the spec, and holds no copy of a pack.
`--library` cannot be combined with `--pack`. When no pack applies, the table names the modules the
repository imports most and the command that lists one. `fix` has nothing to do for an inventory
and is not offered.

### D5. A pack is made and tested with the tool

`obelize pack new` writes a pack that loads: one `rename_import` change and one
`manifest_dependency` change for the two distributions the author names, a positive and a negative
fixture for each, and a `SOURCES.md` with a section per change. The `.after` answer keys are what
the rules write into the fixtures at that moment, so the skeleton passes at once; the pack and its
sources say to read them. It refuses a folder that exists and removes the one it made if the pack
would not load.

`obelize pack test` runs the checks the bundled packs already pass in `tests/packs/`, moved into
`src/obelize/packs/check.py` so that a pack of your own is held to the same standard: fixtures on
disk and named, both kinds per change, parsing and prefilter, answer keys equal to what the rules
write, a second run that changes nothing, equal bytes on two runs, and sources that match the
changes. `pack validate` stays a reading of the pack alone, as before.

### D6. A verification can be run on the tree as it stands

`obelize verify` answers `inconclusive` / `tree_changed` when a file the run wrote is no longer
the run's bytes, which is right when the question is whether obelize's change works. It is the
wrong answer when someone finished the migration, a person or a coding agent editing the files
obelize left, and wants the tests to say whether the result holds. `--current` runs the
verification commands on the tree as it stands, through the same trust rules, and records in
`verify.edited` the files whose bytes differ from the run's, so the record still says that the
verdict is not about obelize's own bytes. It works for an apply that wrote nothing, because the
agent may have written everything, and not for a dry run, which has no verification to replace.

## Consequences

`docs/CLI.md` documents the flags and replaces its CI recipe, which parsed the JSON with a one-line
script, with `--fail-on`.
