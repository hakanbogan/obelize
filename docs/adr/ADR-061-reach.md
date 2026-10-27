# ADR-061: Reach

## Status

Accepted; amended by ADR-078.

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
`src/obelize/packtools/check.py` so that a pack of your own is held to the same standard: fixtures on
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

### D7. A coding agent calls tools that cannot ask for more than the person gave

`obelize mcp` serves the commands over the Model Context Protocol on standard input and output,
with the protocol's `initialize`, `ping`, `tools/list` and `tools/call` written against the standard
library so that no dependency is added. A tool runs the command of its name as a child process with
no input and its output captured: the stream carries protocol and nothing else, and a tool does
what the command does, trust rules and refusals included.

The agent is an untrusted caller and the person who started the server is the owner. A tool
argument is one of a pack id, a distribution, a module, a run id, a number or a boolean, each
checked against its shape before it reaches a command line, so no flag, path or command can be
passed. No tool takes `--verify`, a model, `--accept-model`, `--allow-dirty` or
`--trust-repo-config`: verification commands come from the person's own configuration, the
repository's `.obelize.yml` runs only if the person starts the server with `--trust-repo-config`,
a model is never consulted (`--model none`; the agent is the model), and a dirty tree is refused as
ever. The two tools that write files are marked destructive, and `--read-only` leaves them out.

`obelize_residue` is what makes the agent useful: the places a scan could not migrate, each with
its reason, what to change, the pack's own guidance and the window of code a model would be shown,
redacted by the same redactor. What the tools return quotes the repository's code and is data to
the agent, which the server's instructions say.

A review of the first version found where the line between agent and owner was drawn too loosely,
and each was closed. The child runs with `-P`, because `python -m` puts the repository first on the
import path and a `typer.py` in it would have run as obelize. A pack is a known id and never a
path, because a path would be read from the repository. The trust of `--trust-repo-config` is
pinned to the hash of `.obelize.yml` at start, because the agent can edit that file. `verify` and
`undo` take only runs the session made, because a run folder the repository carries names the files
an undo writes; and `undo` refuses a row in `.git/` or `.obelize/` whoever asks. A fault of the
server ends one call and not the session. What cannot be closed is that the person's tests run
the repository's code, an agent's edits included, which the documentation says.

### D8. A pipeline step and a hook run the scan

The repository's `action.yml` is a composite action over `scan --sarif --fail-on`: it installs uv,
runs the pinned release, prints an annotation per place with the file name and message escaped so
that repository text cannot end a workflow command, appends a summary, uploads the SARIF to code
scanning if asked, and only then fails the job with the scan's exit code. Each input reaches the
script as an environment variable and is checked against the shape it may have (a release, a pack
id, a distribution, a module, a status) before it joins a command line. `.pre-commit-hooks.yaml`
offers `obelize-scan` with the same default statuses. Neither writes a file of the repository. The
action also has a second mode, which upgrades a dependency in a copy
([ADR-078](ADR-078-the-upgrade-mode-of-the-action.md)).

## Consequences

`docs/CLI.md` documents the flags and replaces its CI recipe, which parsed the JSON with a one-line
script, with `--fail-on`.
