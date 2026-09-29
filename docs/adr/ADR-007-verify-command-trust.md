# ADR-007: Verify command trust

## Status

Accepted; amended by ADR-011 (D1) and ADR-033.

## Decision

**Verification commands may come only from the user.** The precedence is:

1. **CLI `--verify "<cmd>"`**: always allowed; the user typed it.
2. **The user allowlist**, `verify.allow` in `~/.config/obelize/config.yml`
   (schema in [CLI.md](../CLI.md)), outside any repository.
3. **The repository `.obelize.yml`**: allowed interactively, after a one-time
   approval.
4. **A pack's `verification.suggestions`**: **displayed and never executed**,
   listed as "suggested, not run".

A repository or a pack is remote text, and a checkout must not gain command
execution by being read (threat TM-5). Trust is evaluated only when verification
is going to run (ADR-011 D1.3).

### Repository-sourced commands, interactively

Interactive means a TTY is present, `CI` is not set, and `--non-interactive` was
not passed. Approval is per command, never blanket: each command from
`.obelize.yml` is printed verbatim and approved once with a `y`, recorded in
**`~/.config/obelize/approved.json`, keyed by repository path plus the command's
sha256**, so changed text asks again.

### Repository-sourced commands, non-interactively or in CI

A repository-sourced command runs **only** if it matches the user allowlist or
**`--trust-repo-config`** was passed on that invocation. Otherwise no command of
the phase runs, so a run never reports a `pass` over a subset: the result is
`not_run` with reason `policy_refused`, the refused command is printed and
recorded in the evidence, and the process exits **5**.

### Execution mechanics

- **`shlex.split`** and **`shell=False`**: no pipes, redirection, substitution
  or chaining. A compound command such as `pytest -q && mypy` is refused when
  the configuration is read; it is written as two entries.
- The working directory is the **repository root**; `start_new_session=True`,
  `stdin=DEVNULL`, stdout and stderr captured together.
- On timeout (default 600 s) the process group gets `SIGTERM`, then `SIGKILL`
  after 5 s, and the result is `inconclusive` with reason `timeout`.
- The environment is inherited, plus `OBELIZE_RUN=1`, so the command sees the
  user's credentials as it would if they ran it themselves.
- Output is capped at 1 MiB (first 256 KiB plus last 768 KiB, flagged
  `output_truncated`) and redacted before it reaches the logs or the report.

### What is not covered by this decision

Two cheap checks always run and are not user-configurable, because they are ours,
not the project's: `cst.parse_module` before a file is written, and `compile()`
on every changed `.py` file after `--apply`. A failure there is a `fail` with
reason `changed_file_does_not_compile`, independent of any verification command.

## Consequences

- A hostile repository cannot obtain execution by being scanned or fixed; in CI
  the refusal is visible in the output and in `run.json`.
- `--trust-repo-config` appears in `run.json` under `argv`, so its use is
  auditable.
- Local execution is not isolated (v0 has no sandbox), and `docs/CLI.md` says so.
