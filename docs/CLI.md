# Command-line interface

A release requires real `--help` output and exit codes to match this page
([RELEASING.md](RELEASING.md)). The decisions behind it are indexed in
[DECISIONS.md](DECISIONS.md).

## Surface

```
obelize scan   [--repo .] [--pack gemini/google-generativeai-to-google-genai | ./pack.yaml] [--json] [--jobs N] [--list-files]
obelize fix    [--pack <id|path>] [--repo .] [--apply] [--allow-dirty] [--verify "<cmd>"]... [--timeout <s>]
            [--non-interactive] [--trust-repo-config] [--model <provider>] [--accept-model]
            [--show-context] [--json]
obelize verify --run <id> [--repo .] [--verify "<cmd>"]... [--timeout <s>]
            [--non-interactive] [--trust-repo-config]
obelize undo   --run <id> [--repo .]
obelize pack validate <id|path>
```

`python -m obelize` runs the same commands where the `obelize` script is not
on `PATH`. Every command prints its run folder's path under `--repo` as you
typed it, so the path opens from where you ran it.

## Global options

| Flag | Description |
|---|---|
| `--version` | Print the version and exit. |
| `--no-color` | No colour, in `--help` and usage errors too. `NO_COLOR` does the same, following [no-color.org](https://no-color.org): any non-empty value, `0` included. |
| `-h`, `--help` | Show help and exit, in under 300 ms. |

## `obelize scan`

Find the imports, call sites and manifest entries a pack affects. Never edits
the repository.

| Flag | Description |
|---|---|
| `--repo <path>` | Repository root. Default: the current directory. |
| `--pack <id\|path>` | Bundled pack id or pack file path. Default: `gemini/google-generativeai-to-google-genai`, named so it cannot change meaning when another pack ships. |
| `--json` | Findings as JSON on stdout; the run folder's path on **stderr**. |
| `--jobs N` | Worker processes; `1` is in-process. Default `min(8, cpu_count - 1)`, in-process below 32 prefilter survivors; an explicit `N` is always used, up to the 61 a Windows process pool takes. Never changes the output. |
| `--list-files` | Print the selected files in order and stop, reading no file. The pack is still loaded (an invalid one exits `7`). |

Writes a run folder and updates `.obelize/latest`
([RUN_FOLDER.md](RUN_FOLDER.md)). `--json` output equals the folder's
`findings.json` byte for byte and holds nothing time-derived (run id, timings
and paths are in `run.json`), so runs over the same input compare equal.
Evidence is written before anything is printed; failing to write it exits `1`.

Exit codes: `0` done, findings or not; `7` invalid pack; `2` usage error,
including a `--repo` that is not a directory, `--jobs` below 1 or above 61 on Windows, and an unusable
`.obelize.yml`; `1` unexpected error, including an unwritable run folder.

### A CI check

To fail a CI job while the repository still uses the legacy SDK, read the
counts `--json` prints:

```sh
uvx obelize scan --json | python3 -c "import json, sys; c = json.load(sys.stdin)['counts']; sys.exit(1 if c['findings'] - c['not_a_usage'] else 0)"
```

It exits `1` on any finding except `not_a_usage`, which is context only: a
mention in a comment or string, or a legacy pin nothing imports. Test
`c['findings']` alone to fail on those too. A scan that fails prints no JSON,
so the check exits `1` then as well. The run folder's path goes to stderr and
stdout holds the JSON alone. The scan still writes its run folder under
`.obelize/` in the checkout, and the `.gitignore` inside keeps it out of
`git status`. Pin a version, as in `uvx obelize==0.1.0`, since any 0.x release
can change the JSON ([CHANGELOG.md](../CHANGELOG.md#stability)).

## `obelize fix`

Plan a migration and, with `--apply`, write it. Without `--apply` nothing is
modified.

| Flag | Description |
|---|---|
| `--pack <id\|path>` | Bundled pack id or pack file path. Default: `gemini/google-generativeai-to-google-genai`, as for `scan`. |
| `--repo <path>` | Repository root. Default: the current directory. |
| `--apply` | Write the planned edits. Without it no source file is written: the terminal lists each file's hunks, then prints up to 200 lines of the unified diff, with secrets redacted and control characters escaped, and the path of `.obelize/runs/<id>/patch.diff`, which holds all of it as it is. |
| `--allow-dirty` | Permit `--apply` with uncommitted changes. Without it, **any** modified or staged tracked file in the whole repository, or an untracked file on the plan, refuses the apply (other untracked files do not count, and the report counts the paths and never names them), so the `git diff` is the migration alone; so does `tree_unknown` (git failed, timed out or refused the directory). A dirty tree is recorded in the report. |
| `--verify "<cmd>"` | A verification command. Repeatable. Replaces the repository's, and runs without asking. |
| `--timeout <s>` | Override `verify.timeout_s` (at least 1). |
| `--non-interactive` | Never prompt; refuse a repository command not on the user allowlist unless `--trust-repo-config` is passed. |
| `--trust-repo-config` | Trust the repository's `verify.commands` in a non-interactive or CI run. |
| `--model <provider>` | `none` or `openai_compat`, replacing `model.provider` from [your own file](#the-user-files-configobelize) for this run. |
| `--accept-model` | Also write the model's edits that passed validation. Requires `--apply` (exit `2` otherwise). Without this flag a proposal is only in `plan.json`, `patch.diff` and `model/`. |
| `--show-context` | Print what would be sent to a model and stop: no request, no run folder. Works with `provider: none`; not with `--apply`. |
| `--json` | `plan.json`'s bytes on stdout; the run folder's path on **stderr**. |

**Phase order:** check the working tree and every planned path; consult a
configured model; run the baseline verification; write the patch; compile every
`.py` file written; verify again. Consequences, each a case in
`tests/fixtures/commands/` or `tests/fixtures/providers/runs.yaml`:

- A refused apply runs no command and sends nothing to a model.
- A verification refused by [the trust rule](THREAT_MODEL.md#verification-command-trust-rule)
  does not stop the write: the run exits `5` with `not_run` / `policy_refused`
  rather than looking like a repository that needed no work.
- A failing baseline does not stop the write; the after-phase is skipped and
  the run is `inconclusive` / `baseline_failed`.

Exit codes: `0` an apply with nothing outstanding, and every dry run, review
items or not; `3` verification failed after the patch; `6` patch applied, no
verdict; `4` an apply wrote nothing or left review items; `5` policy refusal
(dirty tree, untrusted command, path escape); `7` invalid pack; `2` usage error,
including a pack path with nothing there, a `--verify` that needs a shell or
does not split into arguments, an unusable `.obelize.yml` and an invalid
`~/.config/obelize/config.yml`; `1` unexpected error, including an unwritable
run folder.

**Review items** are `run.json`'s `withheld[]` rows, so `4` is the usual result
on a real repository and `0` claims the whole repository migrated. A pipeline
should accept `0` and `4`.

**The summary ends with the next step** after an apply that exits `0`, `4`
with review items, `5` or `6`: a `Next:` line holding the command to run. A
run with nothing to write names the reason that held back the most findings.

**With a model configured**, one stderr line first names the provider, the host
of `base_url` (never the URL, which can carry a credential) and the model. The
run adds `run.json`'s `model` object and a `model/` directory with one file per
consultation ([RUN_FOLDER.md](RUN_FOLDER.md)). A written model proposal stays
in `withheld[]`: validation shows that an edit is safe to apply, not that it is correct.

## `obelize verify`

Re-run an existing run's verification and update its evidence.

| Flag | Description |
|---|---|
| `--run <id>` | Required. The run id under `.obelize/runs/`. |
| `--repo <path>` | Repository root. Default: the current directory. |
| `--verify "<cmd>"` | A verification command. Repeatable. Replaces the repository's. |
| `--timeout <s>` | Override `verify.timeout_s` (at least 1). |
| `--non-interactive` | Never prompt; refuse a repository command instead. |
| `--trust-repo-config` | Trust the repository's `verify.commands` for this run. |

If the files still match the run's `after_sha256`, the after-phase runs again;
otherwise the result is `inconclusive` / `tree_changed` and nothing runs. If
the run's baseline did not pass, nothing runs and the recorded verdict stands.
Commands come from your configuration and trust is decided again, never from
the run folder, which a repository could forge (threat TM-9). Only the
verification parts of the folder are replaced
([RUN_FOLDER.md](RUN_FOLDER.md#layout)); the original baseline is kept but not
carried into the new record.

Exit codes: `0` `pass`; `3` `fail`; `6` `inconclusive`, or `not_run` other than
`policy_refused`; `5` `policy_refused`; `2` usage error, including a malformed
run id, a missing or unreadable run folder, a run that wrote no file, a
`--verify` that needs a shell or does not split into arguments, and an invalid
`~/.config/obelize/config.yml`; `1` unexpected error, including a result that
could not be recorded.

## `obelize undo`

Revert the files an applied run wrote.

| Flag | Description |
|---|---|
| `--run <id>` | Required. The run id under `.obelize/runs/`. |
| `--repo <path>` | Repository root. Default: the current directory. |

A file is reverted only if its current hash equals the run's after-hash, and
only from a snapshot whose bytes match its content-addressed name. Otherwise it
is skipped and reported with both hashes and its snapshot path under
`.obelize/runs/<id>/snapshots/before/`. No `--force`: obelize never overwrites
content it did not write. `undo.json` gets a row for **every** file the run
wrote, so a partial undo cannot read as complete
([RUN_FOLDER.md](RUN_FOLDER.md#undojson)).

### Why a file was not put back

A closed set (`models.UndoSkip`).

| Value | Means |
|---|---|
| `hash_mismatch` | Edited after the run. Both hashes and the snapshot path are printed, and "(already the original)" when the file holds its original again, after an earlier undo for example. |
| `missing` | Nothing is at that path. |
| `not_a_file` | Not a regular file. |
| `outside_root` | The recorded path leaves the repository: the run folder was edited by hand. |
| `snapshot_unusable` | The snapshot is absent or does not match its name; `patch.diff` still describes the change. |
| `symlink` | Now a symbolic link, which obelize never follows. |
| `unreadable` | Could not be read, or the replacement could not be written. |

Exit codes: `0` all reverted; `4` nothing reverted or files skipped, including
an apply that wrote no file; `2` usage error, including a malformed run id, a
missing run folder, and a plan or scan run; `1` unexpected error, including
files restored but `undo.json` unwritten (the message says which).

## `obelize pack validate`

Validate a pack against [PACK_SPEC.md](PACK_SPEC.md): every field, vocabulary
and [cross-field rule](PACK_SPEC.md#validation-errors), each error naming the
key's path. Declared fixture paths are checked as paths, not for existence,
since a local pack need not ship fixtures (the last output line says so).
`source.url` is never requested.

| Argument | Description |
|---|---|
| `<id\|path>` | A bundled pack id (`gemini/google-generativeai-to-google-genai`) or a pack file path (`./pack.yaml`). An id wins over a path spelled the same; anything not shaped like an id is a path. |

Exit codes: `0` valid; `7` invalid YAML or schema; `2` nothing to read there;
`1` a **bundled** pack is invalid (an obelize defect; the message links the
issue tracker).

## Exit codes

Shared by every command; unstable through 0.x
([CHANGELOG.md](../CHANGELOG.md#stability)).

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Usage error |
| `3` | Verification failed after patch |
| `4` | Nothing applied / manual review required |
| `5` | Policy refusal (dirty tree or one git cannot describe, untrusted verification command, path escape) |
| `6` | Verification produced no verdict (`inconclusive`, or `not_run` for any reason other than `policy_refused`) |
| `7` | The pack is not valid |

`2` (argument parsing) and `1` (the top-level handler) take precedence; among
the rest the first match wins, in detection order: `7`, `5`, `3`, `6`, `4`,
`0`.

### Verification status and exit code

| `verify.status` | `verify.reason` | Exit | When |
|---|---|---|---|
| `pass` | -- | `0` | Every command succeeded after the patch |
| `fail` | `command_failed`, `changed_file_does_not_compile` | `3` | A command failed after the patch, or a changed file does not compile |
| `inconclusive` | `timeout`, `tree_changed`, `baseline_failed`, `command_not_executable` | `6` | A verdict was expected and none was obtained |
| `not_run` | `no_verify_commands` | `6` | The patch was applied and no command was configured |
| `not_run` | `policy_refused` | `5` | A repository-sourced command refused in CI without trust |
| `not_run` | `dry_run`, `no_changes_to_verify` | n/a | No verdict was expected; the exit code comes from the plan |

Several commands give the worst status: `fail` > `inconclusive` > `not_run` >
`pass`. Trust is evaluated only when verification will run, so a run that wrote
nothing never refuses a command.

### The verification vocabulary

Closed sets, declared as `Literal`s in `src/obelize/models.py` and held equal
to these tables by `tests/unit/test_verify_vocabulary.py`.

#### `verify.status` (4 values)

| Value | Means |
|---|---|
| `pass` | Every command that ran succeeded; never over an empty list. |
| `fail` | A command, or the compile check of changed files, said no. |
| `inconclusive` | A command gave no answer that is evidence about the patch. |
| `not_run` | No command ran; the reason says why. |

#### `verify.reason` (10 values)

`null` only under `pass`.

| Value | Under | Means |
|---|---|---|
| `baseline_failed` | `inconclusive` | The commands failed **before** the patch, so the after-run is skipped. Fix your tests. |
| `changed_file_does_not_compile` | `fail` | A `.py` file obelize wrote does not compile. Always checked first. |
| `command_failed` | `fail` | A command exited non-zero. |
| `command_not_executable` | `inconclusive` | A command never started: no such program, or no permission. |
| `dry_run` | `not_run` | No `--apply`. No exit code of its own. |
| `no_changes_to_verify` | `not_run` | An apply that wrote no file. No exit code of its own. |
| `no_verify_commands` | `not_run` | Files written, no command configured. Pass `--verify` or set `verify.commands`. |
| `policy_refused` | `not_run` | A repository command was not trusted in this mode; one refusal refuses the whole phase. |
| `timeout` | `inconclusive` | A command outlasted `verify.timeout_s`; its process group was killed. |
| `tree_changed` | `inconclusive` | `obelize verify` found hashes other than the run recorded. |

#### `verify.commands[].source` (3 values)

Why a command could run, not where it was read: a repository command also on
your allowlist is `user_allowlist`.

| Value | Means |
|---|---|
| `cli` | `--verify` on this invocation. Level 1. |
| `user_allowlist` | Matches `~/.config/obelize/config.yml`. Level 2. |
| `repo_config` | `.obelize.yml`, allowed by an approval or `--trust-repo-config`. Level 3. |

## Configuration file (`.obelize.yml`)

At the repository root; flags take precedence. A file that does not parse, or
has an unknown, duplicate or wrongly typed key, exits `2` before anything is
read; it is never partially applied.

| Key | Type | Default | Description |
|---|---|---|---|
| `include` | string | `**/*.py` | Files the scan considers, after all exclusions. Same semantics as `exclude`. |
| `exclude` | list of strings | empty | Patterns to skip, with git's `.gitignore` semantics (`pathspec.GitIgnoreSpec`): `legacy/*` excludes everything under `legacy/`, at any depth. Added to [the always-excluded set](#the-always-excluded-set); a `!` pattern re-includes only what this list excluded. |
| `verify.commands` | list of strings | empty | Verification commands, under the [trust rules](#trust-rules-for-verification-commands). Split with `shlex` and run without a shell, so a bare `\|`, `&&` or `>` is refused on load; use `sh -c "<command>"`. |
| `verify.timeout_s` | integer | `600` | Per-command timeout in seconds; on expiry the process group is killed and the status is `inconclusive` / `timeout`. |
| `verify.junit` | boolean | `true` | Add `--junitxml` into the run folder to a `pytest` or `python -m pytest` command that has none, to compare per-test results with the baseline. |
| `allow_dirty` | boolean | `false` | Same as `--allow-dirty`. |
| `max_file_bytes` | integer | `2000000` | Larger files are recorded as a limitation, not parsed. |

**A `model:` block is refused** (exit `2`): where your code and credentials go
is not a repository's choice. Configure the model in
[your own file](#the-user-files-configobelize) or with `--model`.

### The always-excluded set

Applied first on every run; no `!` pattern brings these back.

| Pattern | Why |
|---|---|
| `.obelize/` | Run folders; otherwise a scan reports the previous report. |
| `.*/` | Every dot-directory: `.git`, `.venv`, `.tox`, caches, editor state. |
| `__pycache__/` | Bytecode. |
| `site-packages/` | Installed packages, in a virtual environment of any name. |
| `venv/` | The usual undotted virtual environment. |
| `node_modules/` | Not Python. |
| `vendor/`, `_vendor/` | Vendored source. |
| `build/`, `dist/`, `*.egg-info/` | Build output, a second copy of your source. |

Only these skip a directory whole. **Your own `exclude` never does**: an
excluded file that still imports the legacy distribution is still named,
because the dependency pin it breaks is not excluded. Excluding means *do not
migrate*, not *do not look*.

In a git repository, files come from
`git ls-files --cached --others --exclude-standard`, so `.gitignore` applies.
Elsewhere a fallback walk ignores nothing but skips directories holding a
`pyvenv.cfg`. Symbolic links are never followed and submodules never entered;
each is reported, so a low finding count is not mistaken for a clean
repository.

### Merging the command line with the file

Other flags have no file equivalent.

| Flag | Key | Rule |
|---|---|---|
| `--verify "<cmd>"` | `verify.commands` | **Replaces** the list, so every command is one you typed. |
| `--timeout <s>` | `verify.timeout_s` | Replaces. |
| `--allow-dirty` | `allow_dirty` | Adds permission; it cannot turn off `allow_dirty: true`. |
| `--model <provider>` | `model.provider` in `~/.config/obelize/config.yml` | Replaces; the result is re-validated, so `openai_compat` without a `base_url` fails here. |

### What a selected file still has to survive

1. Size: over `max_file_bytes`, not read; a limitation names both numbers.
2. Byte prefilter: without any of the pack's tokens, reported as nothing.
3. libcst, then `compile()`: a refusal by either is one `parse_error` and
   no edit. `compile()` also catches what libcst accepts, such as `return`
   outside a function or a late `__future__` import.
4. Byte round-trip: if libcst does not reproduce the file exactly (bare-CR
   line endings, for example), every finding in it is withheld.

`compile()` is the running interpreter's: under 3.12, syntax from a later
Python (3.14's unparenthesised `except A, B:`) is refused as unparsable, while
3.14 accepts Python 2's `except E, e:` (PEP 758). Run obelize under a Python at
least as new as your code.

### Worked example

```yaml
# .obelize.yml: repository-level configuration for obelize.
# Every key is optional; the defaults are documented in docs/CLI.md.

include: "**/*.py"

exclude:
  - "migrations/**"
  - "docs/examples/**"

verify:
  commands:
    - "pytest -q tests/unit"
    - "python -m mypy src"
  timeout_s: 900
  junit: true

allow_dirty: false
max_file_bytes: 2000000
```

### Trust rules for verification commands

A command's source decides whether it may run, following
[the trust rule in THREAT_MODEL.md](THREAT_MODEL.md#verification-command-trust-rule).
Highest first:

1. `--verify "<cmd>"`: always.
2. The allowlist in `~/.config/obelize/config.yml`.
3. `verify.commands` in `.obelize.yml`.
4. A pack's `verification.suggestions`: **never**, under any flag; printed as
   "suggested, not run".

Level 3 depends on the mode:

- Local interactive (a TTY, `CI` unset, no `--non-interactive`): each
  command is printed and confirmed once with `y`; the approval, keyed by
  repository path and command sha256, is kept in
  `~/.config/obelize/approved.json`, and changed text asks again.
- Non-interactive or CI: runs only if allowlisted or with
  `--trust-repo-config`; otherwise `not_run` / `policy_refused`, exit `5`.

Commands run in the repository root, without a shell (`shlex.split`,
`shell=False`), stdin closed, in their own session, with your environment plus
`OBELIZE_RUN=1`. They are **not isolated**: a command can do anything your
shell can. On timeout the whole process group is terminated, then killed.

#### The user files (`~/.config/obelize/`)

Outside every repository, so no checkout can write them (`$XDG_CONFIG_HOME` is
honoured). `config.yml` holds the two settings a repository may not make: the
allowlist and the model. Unknown keys are an error.

```yaml
# ~/.config/obelize/config.yml
verify:
  allow:
    - "pytest -q"
    - "python -m mypy src"
model:
  provider: none            # the default; no network call is made while it is `none`
  # base_url: "http://localhost:11434/v1"
  # model: "qwen2.5-coder"
  # api_key_env: OBELIZE_MODEL_API_KEY
  # log_prompts: false
```

The `model` keys are acted on by `obelize fix`.

| Key | Type | Default | Description |
|---|---|---|---|
| `model.provider` | `none` \| `openai_compat` | `none` | Model adapter for ambiguous cases; `none` makes no network call. |
| `model.base_url` | string | unset | An OpenAI-compatible endpoint, such as a local Ollama. `http` or `https`, no credential: the host goes into the evidence. |
| `model.model` | string | unset | Model name sent to the endpoint. |
| `model.api_key_env` | string | `OBELIZE_MODEL_API_KEY` | Environment variable holding the key; the key never reaches configuration, logs or evidence. |
| `model.log_prompts` | boolean | `false` | Keep raw prompts, which contain source, in the run folder. |

An allowlist entry matches a command that splits into the same arguments. An
unreadable or invalid file is an error, never an empty allowlist.
`approved.json` only caches your answers: if it is missing or unreadable you
are asked again.
