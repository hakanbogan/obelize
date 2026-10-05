# ADR-033: Running somebody else's command

## Status

Accepted; amended by ADR-049.

## Decision

### D1 -- one refused command refuses the whole phase

If ADR-007's ladder refuses any command a run would execute, none runs: the phase is `not_run` with
`policy_refused`, `commands` is empty, and the refusal names the command. Running the permitted
subset would give a `pass` over half a verification that reads as a whole one.

### D2 -- interactive is three conditions, and `CI` is presence

A repository-sourced command may be approved at a prompt only when a terminal is attached, `CI` is
not in the environment (set to the empty string counts as set), and `--non-interactive` was not
passed; each alone refuses. A caller interactive by those tests that supplies no prompt function is
refused too, because nobody answering is not a yes. `Mode` takes `tty` as a value: only
`obelize.cli` asks the terminal.

### D3 -- the allowlist matches argv, the store keys on text

The user allowlist is `verify.allow` in `~/.config/obelize/config.yml` (`$XDG_CONFIG_HOME` honoured,
unknown keys refused); the key is not `.obelize.yml`'s `commands`, so a repository's configuration
never reads as an allowlist. An entry matches when `shlex.split` gives the same argv, because what is
compared is what would run. The approval store keys on the sha256 of the text plus the repository
path, because it records what a person was shown and changed text is unseen.

### D4 -- a broken allowlist is an error; a broken store is not

An unreadable or invalid `config.yml` stops the run, as an invalid `.obelize.yml` does (ADR-015 D1):
ignoring it would silently run fewer of the user's own commands. An unreadable or unparseable
`approved.json` is read as no approvals: it caches answers already given, and losing it costs a
prompt.

### D5 -- a tenth reason: `command_not_executable`

A command that never became a process (no such program, no permission) is `inconclusive` with
`command_not_executable`, not `fail` with `command_failed`, whose exit `3` would tell the reader the
migration broke a suite that never started. One reason per required action.

### D6 -- "a verdict was expected" needs no parameter

Exit `6` applies only where a verdict was expected (ADR-011 D1). A dry run and an apply that wrote
nothing are `not_run` with `dry_run` and `no_changes_to_verify`, which `obelize verify` never
produces, so `exit_code` is total over status and reason and no caller can forget to say what kind
of run it was.

### D7 -- the baseline is a gate, asked before the after-phase runs

`status.gate(baseline)` is asked first, and a baseline that did not pass means the after-phase does
not run, since ADR-011 D1.2 makes its result mean nothing about the patch. The run is `inconclusive`
with `baseline_failed` when the baseline failed, or with the baseline's own reason (`timeout`,
`command_not_executable`) when it reached no verdict, because each asks for a different fix.
`VerifyResult` refuses every other shape, and neither it nor `VerifyPhase` accepts a `pass` over no
command, so no such result reaches evidence.

### D8 -- every command runs, and the phase takes the first of the worst

A failing command does not stop the ones after it: the list is a script, the worst-of rule (ADR-011
D1.1) needs several verdicts, and a report naming one failure costs a second run. The phase takes
the worst status (`fail`, `inconclusive`, `not_run`, `pass`, in that order) and the reason of the
first command, in run order, that has it.

### D9 -- the kill is a group kill, and the read has three stopping conditions

Each command runs in a session of its own and its deadline is enforced on its process group:
`SIGTERM`, then `SIGKILL` if the leader outlives `GRACE_S` (5 s), because a server the suite
started holds the pipe and keeps running. The read stops on end-of-file, on the deadline, and
`DRAIN_S` (5 s) after the kill: a command can close its output and keep running, and a child in a
session of its own escapes the group kill and keeps the pipe open. When the command exits first,
the read goes on at most `DRAIN_S` and then kills what is left of its group.

### D10 -- the output is capped by retention, and the limit is written down

Output streams into two buffers, the first 256 KiB and the last 768 KiB, the elided middle replaced
by an `output_truncated` marker, so a command printing gigabytes costs a mebibyte of memory and the
reader keeps the first failure and the summary. Redaction runs over what was retained: above the
cap a secret straddling the elision is cut rather than removed, since redacting first means holding
unbounded output. Secret values go longest first, ties broken by value then variable name, so one
input always names the same variable. `docs/PRIVACY.md` says redaction is not a guarantee.

### D11 -- the compile gate reads the disk, runs first, and is a `fail`

`verify/cheap.py` compiles every changed `.py` file after the apply, reading it back through
`fsutil.read`, so unlike ADR-031's in-memory output gate it sees the file the user now has (a write
cut short, a rename that landed elsewhere, an editor's save). It runs before the after-phase's
commands, since a suite over a tree that does not compile is noise, and a failure is `fail` with
`changed_file_does_not_compile`: the tree does not compile and obelize changed it.

### D12 -- the runner adds `--junitxml`; comparing the reports is not this task

With `verify.junit` on (the default), the runner adds `--junitxml`, pointing into its caller's
directory, to a pytest command that carries none, and records the report only when the command
really wrote one: a row pointing at a missing file is worse than none. Comparing the two phases'
reports per test is not built.

## Consequences

- `docs/CLI.md` publishes the statuses, reasons and sources as closed vocabularies, which change
  only together with `models.py`.
- Execution is not isolated: a command runs with the user's environment and credentials, and the
  documents say so.
- Redaction over-redacts on purpose (`GIT_AUTHOR_NAME` matches `AUTH`) until a log it made
  unreadable argues for a deny-list or an entropy test.
- `os.killpg`, `start_new_session` and `select` on a pipe are POSIX; on Windows a job object does
  the stopping, as [ADR-049](ADR-049-platform-seam.md) describes.
- Open: the compile gate is reached only where the after-phase's commands run, so an uncompilable
  write with no command configured is `not_run`, exit `6`, not `fail`
  (`tests/fixtures/scan/COVERAGE.md` gap 26).
