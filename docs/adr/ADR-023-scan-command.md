# ADR-023: Scan command

## Status

Accepted.

## Decision

### D1. `obelize scan` is registered, and nothing else is

A subcommand is registered only once it works, never as a stub, because
`.github/workflows/e2e.yml` runs the whole flow as soon as `scan`, `fix` and
`verify` answer `--help`, and a stub would turn that job red.

### D2. Two documents come out of one run, and only one of them may carry a clock

`findings.json`, byte for byte what `--json` prints, carries no run id,
timestamp, timing or absolute path; `run.json` carries all four. The command
serialises the findings **once** and hands the same string to stdout and to
the file, so the two cannot drift. Under `--json` the run folder's path goes to
stderr, so stdout stays the document and the run id is still reported.

### D3. A scan writes its run folder, and T19 keeps the modes a scan has no answer for

`obelize scan` writes a scan-only run folder (`run.json`, `findings.json`,
`pack.yaml`, `pack.sha256`, `REPORT.md`), because CLI.md says it records
evidence and a command that promises evidence it does not write is the failure
this project forbids. The plan, the diff, the snapshots and the verification
artefacts belong to the modes that plan or apply.

### D4. The record declares every field the document names, and four of them are typed as what a scan writes

`models.RunRecord` carries every top-level field of RUN_FOLDER.md's table, in
its order, and a test asserts the two lists equal in both directions. A field
is typed as narrowly as the implemented modes write it (a type, not a default),
so a record claiming work no mode performed cannot be constructed; it widens in
the task that fills it. `run.schema.json` is generated from the model and
committed, and `ci / schema-drift` guards it.

### D5. The evidence is written before the answer is printed, and a folder that cannot be written is `1`

Inside the folder: every artefact, then `run.json` (which carries `exit_code`),
then `.obelize/latest`, so a `latest` that exists names a complete run. The
folder is written before stdout, because an answer without its audit trail is
the wrong half to keep: a folder that cannot be written exits `1`, says the scan
completed, and prints nothing. So in `scan` mode every record carries
`exit_code` `0`.

### D6. `blocked: runtime_unsupported` is read from a manifest, and a blocked run still reports

The floor comes from a manifest, never the parser, since libcst's native parser
ignores `PartialParserConfig(python_version=...)` (C-37): `scan/runtime.py`
reads PEP 621's `requires-python`, `setup.cfg`'s `python_requires` and
`tool.poetry.dependencies.python` (translating `^` and `~`), and not
`setup.py`, which is code. A run is blocked when the declaration admits any
Python below 3.10, `>=3.9` included, because pip then installs an older,
different API surface (C-15); a declaration that cannot be parsed blocks
nothing. A blocked run still grades and reports every finding, but plans no
change and asks a configured model nothing, so `fix --apply` over it writes
nothing and exits `4`.

### D7. `--list-files` loads the pack and reads no file

`--list-files` prints the selection and stops without reading any file's bytes,
so a repository of unparsable files still lists. It still loads the pack, so a
broken `--pack` is an error here as everywhere else.

### D8. `--pack` has a named default, and not "the only bundled pack"

`scan`'s `--pack` defaults to the constant `cli.DEFAULT_PACK`, never to "the
only bundled pack", which would change meaning when a second one ships. A test
asserts the constant names a pack that ships. `fix` takes the same default,
because `--apply`, not the pack, is what makes a run write.

### D9. `--jobs` is the runner's to validate, and every argument refusal is `2`

`runner.worker_count` refuses `--jobs` below one, and the command maps its
`ConfigError` to exit `2`, like every argument it cannot use: an unparsable
`.obelize.yml`, a `--repo` that is not a directory, an unknown flag. The command
refuses `--repo` itself, because it can name the flag where the walker can only
name the path.

### D10. git state is read here, and untracked files are not uncommitted changes

`git_sha` and `git_branch` are recorded only when git describes this root, the
walker's rule (ADR-016). `git_dirty` is the whole repository's, read from a
directory inside it, and `null` when git cannot answer
([ADR-032](ADR-032-writing-a-file.md) D11). It
ignores untracked files (`--untracked-files=no`), because obelize writes
`.obelize/runs/<id>/` itself and would otherwise make every later run dirty.
The dirty-tree gate does not read it: it asks `gitutil.tree` with the plan, so
it also refuses a planned file git does not track (ADR-032 D2), which
`git_dirty` never counts. Every git call goes through `gitutil.run`, with one
timeout.

### D11. `argv` is what the *process* received

`argv` records the arguments as received, excluding `argv[0]`, absolute paths
included, because it is the audit record of what somebody typed (including
`--trust-repo-config`). An embedder calling `app()` in process therefore
records its host's `sys.argv`.

### D12. The exit codes are a closed set in code

`models.ExitCode` is `Literal[0, 1, 2, 3, 4, 5, 6, 7]`, `RunRecord.exit_code`
takes it, and a test asserts it equals CLI.md's exit-code table: changing a
code is a breaking change, so the two may not disagree.

## Consequences

- A scan writes only under `.obelize/`, which every scan excludes before any
  user configuration, so a second scan never reports the first one's evidence.
- A read-only checkout cannot be scanned: it exits `1` (D5). No flag turns the
  run folder off; one could be added later without breaking anything.
- Importing `obelize.cli` pulls in none of libcst, pydantic, pyyaml or
  pathspec; a subprocess test asserts it.
- Open under D6: a floor declared only in `setup.py` (`python_requires=">=3.8"`
  in one of eighty repositories measured, ADR-024) reads as no floor. Reading a
  literal there is the narrowest fix and is a decision about reading code.
- Open under D6: a project declaring `>=3.9` that no longer tests on 3.9 is
  blocked; if that is disputed, the answer is a flag, not a quieter rule.
