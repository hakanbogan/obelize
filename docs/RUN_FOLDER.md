# The run folder and `run.json`

`.obelize/runs/<run-id>/` is the evidence a run leaves behind; `run.json` is its
index. `tests/unit/test_run_folder_contract.py` fails when this file, the models
in `src/obelize/models.py` and `.github/workflows/e2e.yml` disagree.

## Layout

```
.obelize/
  .gitignore                    `*`, so git ignores everything in this folder
  latest                        the id of the most recently completed run
  runs/
    20260917T142530Z-3f9a1c72/
      run.json                  metadata and the index (this file's subject)
      findings.json             every finding, with verdict, bail and caused_by
      plan.json                 the planned edits, whether or not they were written
                                (`plan` and `apply` only; a scan has no plan)
      patch.diff                unified diff, git-apply compatible
      pack.yaml                 the pack, copied verbatim
      pack.sha256               its hash
      REPORT.md                 the human-readable report
      snapshots/before/…        files as they were before the patch
      snapshots/after/…         files as they were after the patch
      verify/…                  command output logs, junit XML, verify.json
      model/model.json          what a model was asked, and the rows it was not
      model/proposals-<n>.json  one per consultation: context range, prompt hash,
                                token counts, the proposal and whether it passed
      undo.json                 written if the run was reverted
      journal.json              only while an apply is writing, or after one was
                                interrupted: the rows it meant to write
```

What each file may contain is in [PRIVACY.md](PRIVACY.md). Every mode writes
`run.json`, `findings.json`, `pack.yaml`, `pack.sha256` and `REPORT.md`; the
rest only when they apply: `plan.json` and `patch.diff` on `plan` and `apply`,
`snapshots/` on `apply` for the files it wrote, `verify/` when a verification
command ran and after `obelize verify`, `model/` when a model provider is
configured, `undo.json` after `obelize undo`. An absent artefact does not make
the folder malformed.

**An apply puts its originals down first.** After the tree gate and before any
write, it creates the folder with a `snapshots/before/` copy of every file the
plan would write and `journal.json` (the run id and the plan's `file_edits`
rows); a link or a refusal there stops the run with the repository untouched. On
finishing it writes `run.json`, removes `journal.json` and the unused snapshots,
then writes `latest`. After an interruption, `obelize undo --run <id>` works from
the journal and skips a file the run never reached as `hash_mismatch`: it is
already the original.

`.obelize/` is always excluded from scanning, before any user configuration.
`scan` and `fix` write `.obelize/.gitignore` unless something is already at
that name, so a `git add -A` never picks up a run folder; obelize never edits
your own `.gitignore`.

**`obelize verify` and `obelize undo` update an existing folder**, never create
one, and never move `latest`. `verify` replaces `run.json`'s `verify` (with no
`baseline`: no pre-patch tree is left to measure), `exit_code` and
`timings.verify_ms`, `verify/after/` and `verify/verify.json`; it keeps
`verify/baseline/`, and `REPORT.md` gains a block saying the verdict was replaced. A recorded baseline
that did not pass leaves the folder untouched. `undo`
adds `undo.json` and nothing else. The folder may come from someone else's
checkout, so neither follows a link in it: both open directories from
`.obelize/` down without following links, refuse a link where a directory
belongs, and write beside a name then rename over it.

### `.obelize/latest`

One run id and a trailing newline, so `run_id=$(cat .obelize/latest)` needs no
trimming. A regular file, never a symlink
([THREAT_MODEL.md](THREAT_MODEL.md)). Written last, after `run.json`, so it
always names a complete run. The last run to finish owns it; a script that
cares passes `--run <id>`. Obelize never deletes a run folder or `latest`.

### Run id

```
20260917T142530Z-3f9a1c72
^^^^^^^^^^^^^^^^ ^^^^^^^^
UTC, ISO 8601     8 random hex characters
basic format
```

Pinned as `^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$`. Lexicographic order is
chronological. No colons, which Windows filenames forbid. The suffix is random,
not a hash or a secret: it separates runs started in the same second.

## `run.json`

### Top level

`Modes` says which of `scan`, `plan` (a `fix` without `--apply`) and `apply`
fill the field. A field that does not apply is `null`; an array with nothing to
report is empty. Neither is ever absent.

| Field | Type | Modes | Description |
|---|---|---|---|
| `run_id` | string | all | The folder name. |
| `obelize_version` | string | all | The writing obelize's `__version__`. |
| `mode` | string | all | `scan`, `plan` or `apply`. |
| `exit_code` | integer | all | The process exit code ([CLI.md](CLI.md#exit-codes)); known last, so `run.json` follows every other artefact. |
| `blocked` | string or null | all | `runtime_unsupported` when the project declares `requires-python < 3.10` (read from `pyproject.toml`, `setup.cfg` or Poetry's key): the run reports its findings and proposes no migration. An unparsable declaration leaves it unblocked. |
| `argv` | array of strings | all | The arguments as received, excluding `argv[0]`, unredacted: `--verify` values and `--trust-repo-config` included. |
| `python` | object | all | `{version, implementation}`, for example `{"version": "3.12.9", "implementation": "CPython"}`. No interpreter path: it names the machine and often the person. |
| `platform` | object | all | `{system, release, machine}` from `platform`. |
| `git_sha` | string or null | all | `HEAD` at the start of the run; `null` when the target is not the top of a git repository. |
| `git_branch` | string or null | all | The current branch; `null` when detached or when the target is not the top of a git repository. |
| `git_dirty` | boolean or null | all | Whether a tracked file anywhere in the repository had uncommitted changes at the start. **`false` outside git**, where the dirty-tree refusal (TM-8) cannot protect you; **`null` when git could not say**, which refuses an apply as `tree_unknown`. |
| `pack` | object | all | See [`pack`](#pack). |
| `config` | object | all | See [`config`](#config). |
| `counts` | object | all | See [`counts`](#counts). |
| `file_edits` | array | all | Files **written**, empty on `scan` and `plan`. See [`file_edits[]`](#file_edits). |
| `refused` | array | all | Planned writes that did not happen; empty on `scan` and `plan`. See [`refused[]`](#refused). |
| `idempotent` | boolean or null | `apply` | See [`idempotent`](#idempotent). |
| `withheld` | array | all | One row per withheld finding. See [`withheld[]`](#withheld). |
| `verify` | object or null | `plan`, `apply` | See [`verify`](#verify). |
| `model` | object or null | `plan`, `apply` | `null` unless a model provider was configured. A scan never carries one. See [`model`](#model). |
| `limitations` | array | all | What the run could not look at. See [`limitations[]`](#limitations). |
| `timings` | object | all | The **only** place a wall clock appears. See [`timings`](#timings). |

### `pack`

| Field | Type | Description |
|---|---|---|
| `id` | string | `<provider>/<from>-to-<to>` ([PACK_SPEC.md](PACK_SPEC.md)). |
| `pack_version` | string | The pack content's own semver. |
| `sha256` | string | 64 lowercase hex characters, matching `pack.sha256` and the copy in `pack.yaml`. |
| `source` | string | `bundled` or `file`. No path: it could be absolute and outside the repository. |

### `config`

| Field | Type | Description |
|---|---|---|
| `source` | string | `file` when `.obelize.yml` was read, `defaults` when it was absent. |
| `include` | string | The effective pattern, command line merged over file. |
| `exclude` | array of strings | The effective user exclusions; the always-excluded set is in [CLI.md](CLI.md#configuration-file-obelizeyml). |
| `max_file_bytes` | integer | The effective limit; a larger file appears in `limitations`. |

### `counts`

Integers summarising `findings.json`, never a substitute for it.

| Field | Description |
|---|---|
| `files_selected` | Files the walker chose. |
| `files_parsed` | Of those, the ones both parse gates accepted. |
| `findings` | Total findings, all kinds. |
| `eligible`, `auto`, `needs_review`, `unsupported`, `not_a_usage` | The status split, summing to `findings`. |
| `warnings` | Edits carrying a warning code; outside the split, since a warning withholds nothing. `0` on a scan. |

A `scan` reports the [§10 scan-status](SCAN_VOCABULARY.md) split (`eligible`:
nothing withheld it); `plan` and `apply` report the
[§3 verdict](SCAN_VOCABULARY.md) split (`auto`: rewritten). The unused name is
`0`.

### `file_edits[]`

What was **written**; the plan is `plan.json`. Empty means nothing in the
repository changed.

| Field | Type | Description |
|---|---|---|
| `path` | string | Repository-relative, forward slashes on every platform. |
| `before_sha256` | string | The file as read; its name under `snapshots/before/`. |
| `after_sha256` | string | The file as written. `obelize undo` reverts a file only while its hash still equals this; `obelize verify` reports `tree_changed` otherwise. |
| `hunks` | integer | Hunks this file contributes to `patch.diff`. |
| `rules` | array of strings | The pack rule ids behind the edit, sorted. Empty exactly when `proposals` is not. |
| `proposals` | array of integers | The `model/proposals-<n>.json` behind the edit; at most one. Never beside `rules`: a model is asked only about a file the rules left alone. |

### `idempotent`

`true` when an `apply` wrote no file (`file_edits` empty); `null` on `scan` and
`plan`. It describes bytes, not success: an apply where everything bailed is
`true` too. `e2e.yml` pairs it with `git diff` to check that a second apply
changes nothing.

### `refused[]`

Planned writes that did not happen; a reviewer reads this first.
[`limitations[]`](#limitations) is what the run could not look at. Without this
array a refused apply would read as a repository that needed no work.

| Field | Type | Description |
|---|---|---|
| `code` | string | A [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §13 value. |
| `path` | string or null | Repository-relative. `null` exactly for `tree_dirty` and `tree_unknown`. |
| `detail` | string | One sentence a person can act on. |

### `withheld[]`

| Field | Type | Description |
|---|---|---|
| `path` | string | Repository-relative. |
| `line` | integer | 1-based. |
| `symbol` | string or null | The resolved legacy qualified name; `null` on a `parse_error` row. |
| `bail` | string | A [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §4 code. |
| `caused_by` | array of strings or null | Set exactly when `bail` is `file_not_fully_migrated` (§6). |

It repeats part of `findings.json` so that `run.json` alone, which the
bug-report template asks for, says what was withheld and why.

### `verify`

`null` on a scan; on `plan` and `apply` always set, even when nothing ran (a dry
run records `not_run` / `dry_run`). `commands` is empty whenever `status` is
`not_run`.

| Field | Type | Description |
|---|---|---|
| `status` | string | `pass`, `fail`, `inconclusive` or `not_run`: the worst of the commands', `fail` > `inconclusive` > `not_run` > `pass`. |
| `reason` | string or null | From the vocabulary in [CLI.md](CLI.md#verification-status-and-exit-code), which maps both to the exit code. `null` only on `pass`. |
| `commands` | array | One entry per command, in the order they ran. See [`verify.commands[]`](#verifycommands). |
| `baseline` | object or null | `status`, `reason` and `commands` before the patch, one level deep. A failed baseline makes the run `inconclusive` / `baseline_failed`, never `fail`. A write refused after the baseline ran keeps it under `not_run` / `no_changes_to_verify`. |

### `verify.commands[]`

One row per command that ran, under `verify` and under `verify.baseline`.

| Field | Type | Description |
|---|---|---|
| `command` | string | The command as given. |
| `source` | string | `cli`, `user_allowlist` or `repo_config`: its trust rung. A pack's `verification.suggestions` are never executed. |
| `status` | string | This command's verdict; only exit code `0` passes. |
| `reason` | string or null | Set exactly when it did not pass: `command_failed`, `command_not_executable` or `timeout`. |
| `exit_code` | integer or null | `null` when no process started; negative when a signal killed it on POSIX, and 3221225786 when the deadline ended its job on Windows. A command stopped at its deadline keeps its code, even `0`, and reads `timeout`. |
| `duration_ms` | integer | |
| `truncated` | boolean | Whether the output was capped. |
| `log` | string or null | Path under `verify/`, relative to the run folder, capped and redacted per [PRIVACY.md](PRIVACY.md); `null` when nothing was printed. |
| `junit` | string or null | Path under `verify/`, when a junit XML was produced. |
| `in_obelize_environment` | boolean | Whether `PATH` found the program in obelize's own environment, which usually lacks the project's test dependencies; `false` for a program named by its path. A baseline command with this `true` that failed or timed out adds a hint, saying which, to the summary and `REPORT.md`. |

Output is a file, never a field: a log can be a megabyte and `run.json` goes
into bug reports. `verify/baseline/` and `verify/after/` each number their
commands from `1` (`1.log`, any junit report beside it). `verify/verify.json` is
the `verify` object alone.

### `model`

`null` whenever `model.provider` is `none`, the default. The detail is in
[the `model/` directory](#the-model-directory).

| Field | Type | Description |
|---|---|---|
| `provider` | string | `openai_compat`, the only v0 value. |
| `host` | string | The host of `base_url`, never the full URL, whose query can carry a credential. |
| `model` | string | The model name sent. |
| `proposals` | integer | Edits proposed, not questions asked. |
| `accepted` | integer | Proposals that passed every guard check **and** were written, which needs `--apply` with `--accept-model`. |
| `tokens_in`, `tokens_out` | integer | As reported by the endpoint. |

No API key appears anywhere in the run folder, and no raw prompt unless
`model.log_prompts` is set. A written proposal stays a review item: its row stays
in `withheld[]`, `counts` do not move, and it earns no exit `0`, because the
guard proves an edit *safe to apply*, not *correct*.

### `limitations[]`

What the run could not look at, so a small finding count never reads as a clean
repository.

| Field | Type | Description |
|---|---|---|
| `code` | string | `models.LimitationCode`, nine values: [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §11's seven plus `file_too_large` and `input_does_not_parse` (§4). |
| `path` | string or null | Repository-relative, when one file is meant. `null` for `unusable_name`, whose `detail` quotes the name. |
| `detail` | string | One sentence a person can act on. |

For a refused parse, `detail` names the gate and quotes the parser's message,
never a line of the file (`cst.ParserSyntaxError.context` and `SyntaxError.text`
stay out of the run folder). An unreadable manifest gets a fixed sentence,
because `configparser` quotes the line.

### `timings`

The only wall-clock values, so everything else compares byte for byte between
two runs over one input.

| Field | Type | Description |
|---|---|---|
| `started_at`, `finished_at` | string | ISO 8601, UTC, to the second, with a `Z` suffix. |
| `total_ms` | integer | Measured on a monotonic clock, not subtracted from the timestamps. |
| `scan_ms`, `plan_ms`, `apply_ms`, `verify_ms`, `model_ms` | integer or null | `null` for a phase that did not run; `model_ms` is set exactly when `model` is. |

## `findings.json`

Byte for byte what `obelize scan --json` prints. Nothing time-derived (no run
id, timings or absolute path), so two scans of one input are identical.

| Field | Type | Description |
|---|---|---|
| `obelize_version` | string | The version that produced it. |
| `pack` | object | `id`, `version` and `sha256`; `version` is `run.json`'s `pack_version`. |
| `counts` | object | `files_selected`, `files_parsed`, `findings` and the scan's status split, as in [`counts`](#counts). |
| `findings` | array | Every finding, in document order. |

### A finding

| Field | Type | Description |
|---|---|---|
| `path` | string | Repository-relative, forward slashes on every platform. |
| `line` | integer | 1-based. |
| `column` | integer | 0-based, as libcst reports it. |
| `kind` | string | [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §1. |
| `confidence_reason` | string | §2. |
| `symbol` | string or null | The resolved legacy qualified name; the distribution on a `manifest` finding; `null` on a `parse_error`. A `mock.patch` target is recorded unquoted. |
| `evidence` | string or null | Always `null`: source excerpts are kept out of evidence. |
| `scan_status` | string | §10. |
| `bail` | string or null | §4. Set exactly when `scan_status` is `needs_review` or `unsupported`. |
| `caused_by` | array of strings or null | §6. Set exactly when `bail` is `file_not_fully_migrated`; sorted, de-duplicated. |

Document order is `(path, line, column, kind, symbol)`, and
`src/obelize/models.py` refuses any other: libcst yields references in an order
that varies between processes. A finding has no verdict or warning; those
belong to an edit, in `plan.json` and `REPORT.md`.

## `plan.json`

What the run **would** write, whether or not it did. Written by `plan` and
`apply`; with `file_edits[]` it defines a dry run:

| Run | `plan.json`'s `files[]` | `run.json`'s `file_edits[]` |
|---|---|---|
| a dry run | everything it would write | empty |
| an apply that wrote it all | everything | the same list |
| an apply that wrote some of it | everything | the subset that landed, with [`refused[]`](#refused) naming why the rest did not |

No time-derived value and no `counts`: it lives only beside `run.json`.

| Field | Type | Description |
|---|---|---|
| `obelize_version` | string | The version that produced it. |
| `pack` | object | As in `findings.json`. |
| `files` | array | One row per file whose bytes would change, in path order, shaped like [`file_edits[]`](#file_edits). |
| `edits` | array | Every edit row, written or withheld, sorted by `(path, line)`. |

### A planned edit

| Field | Type | Description |
|---|---|---|
| `path`, `line` | string, integer | Repository-relative, 1-based. |
| `status` | string | [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §8. |
| `rule_id` | string or null | The pack rule behind it; `null` where no rule claimed the row, and on `model_proposed`. |
| `reason` | string or null | §4. Set on `needs_review` and `unsupported`, and kept on `model_proposed` as what the rules refused. |
| `caused_by` | array of strings or null | Set exactly when `reason` is `file_not_fully_migrated`. |
| `warnings` | array of strings | §5, sorted. |

A file the scan already refused has no row here, since no rule claimed it; so
`REPORT.md` prints the findings beside the edits.

## `patch.diff`

A unified diff of every file `plan.json` names, in path order; empty when
nothing would change.

- Split on `\n` only, as git does, so `git apply` restores exact bytes: a CRLF
  line keeps its `\r`, a bare-CR file is one line.
- Paths quoted as git quotes them, with the `a/` and `b/` prefixes `-p1`
  expects. A name with a space is *not* quoted; its `---` and `+++` lines end in
  a tab.
- No `index` line: `git apply` and `patch -p1` accept its absence, and a wrong
  one would fail `git apply --3way`.
- Never used to write or revert. A write puts down whole content through
  `fsutil.write`; a revert restores `snapshots/before/<sha256>` while the file
  still hashes to `after_sha256`. A reverse-applied diff can fail halfway or hit
  a drifted file.

## `snapshots/`

`snapshots/before/<before_sha256>` and `snapshots/after/<after_sha256>`, no
extension, written by `apply` for the files it wrote. Content-addressed, so no
bytes are stored twice; [`file_edits[]`](#file_edits) maps each hash to its
path.

## The `model/` directory

Written only when `model.provider` is not `none`: `model.json` is the index,
each `proposals-<n>.json` the detail.

### `model/model.json`

| Field | Type | Description |
|---|---|---|
| `obelize_version` | string | |
| `summary` | object | The [`model`](#model) object. |
| `consulted` | integer | Questions asked: the number of `proposals-<n>.json` files. |
| `skipped[]` | array of objects | Withheld rows not put to a model: `path`, `line` and a [`skip reason`](#a-model-was-not-asked-consultskip), so the selection can be audited by what it left out. |

### `model/proposals-<n>.json`

One per **consultation**, numbered from `1` in asking order, whether or not
anything was proposed.

| Field | Type | Description |
|---|---|---|
| `index` | integer | The `<n>` in the file name. |
| `path`, `line` | string, integer | The row asked about. A proposal may edit no other file. |
| `symbol` | string or null | The legacy symbol at that line. |
| `bail` | string | What the rules refused with: a [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §4 code. |
| `context_start_line`, `context_end_line` | integer | The range sent, 1-based, inclusive. |
| `prompt_sha256` | string | Of the exact request body, so a re-asked question shows without either prompt. |
| `prompt` | string or null | Those bytes; `null` unless `model.log_prompts` is true. A prompt is source code. |
| `provider`, `model` | string | Who was asked. |
| `tokens_in`, `tokens_out` | integer | As reported; `0` when nothing was reported. |
| `outcome` | string | A [`proposal outcome`](#what-became-of-a-proposal-proposaloutcome). |
| `failure` | string or null | A [`provider failure`](#an-adapter-could-not-answer-providerfailure), set exactly when `outcome` is `unanswered`. |
| `refusal` | string or null | A [`guard refusal`](#the-guard-refused-a-proposal-guardrefusal), set exactly when `outcome` is `guard_refused`. |
| `detail` | string or null | One line from whichever decided; the endpoint's words are redacted, then cut. |
| `proposal` | object or null | What came back, unvalidated (`path`, `start_line`, `end_line`, `symbol`, `replacement`, `rationale`), so a proposal naming `~/.bashrc` is refused **by name**, not lost in a parse error. |

### The four Phase 3 vocabularies

Closed sets in `src/obelize/models.py`, published here where a reader meets
them.

#### A model was not asked (`ConsultSkip`)

`skipped[].reason`, in the order the checks run.

| Value | Meaning |
|---|---|
| `not_needs_review` | The row is `unsupported`: the new SDK has no equivalent to propose. |
| `not_a_source_file` | A dependency manifest, or a file this run could not write. |
| `atomicity_only` | The bail is `file_not_fully_migrated`; the rows in its `caused_by` are asked about instead. |
| `pack_refused` | A `flag_only` rule refused the surface; a model overriding it would move behaviour out of the pack's data. |
| `consumed_elsewhere` | The bail is `configure_consumed_elsewhere`: the defect is in the other module. |
| `context_too_large` | No range holding the whole binding group fits the budget. Nothing is truncated: the "inside what was sent" check would pass a proposal written against something else. |

#### An adapter could not answer (`ProviderFailure`)

`failure`: pipeline stages in the order the bytes reach them, not a ranking.

| Value | Meaning |
|---|---|
| `endpoint_unreachable` | Nothing answered: no route, no listener, a dropped connection, or the deadline passed. |
| `endpoint_redirected` | A 3xx, refused rather than followed, so the payload and `Authorization` header never reach a host the run did not print. |
| `endpoint_refused` | Any other status outside 200–299; its message travels with it, redacted and capped. |
| `response_too_large` | The body passed the 1 MiB cap. |
| `response_not_json` | The body is not JSON, typically a wrong `base_url`. |
| `response_not_a_completion` | JSON with no `choices[0].message.content` string. |
| `answer_not_json` | The content holds no JSON object under any of the three readings. |
| `answer_not_a_proposal` | An object without the key it was asked for. A bare proposal at the top level is this too: the envelope separates "an edit" from "none". |
| `proposal_does_not_hold` | `EditProposal` refuses it. Unanswered, not refused. |

#### The guard refused a proposal (`GuardRefusal`)

`refusal`. Fifteen words in three groups; the **first** refusal in this order is
recorded, because a hostile proposal trips several and a reviewer needs the
first.

May we touch this file at all:

| Value | Meaning |
|---|---|
| `path_outside_root` | Absolute, holding a `..` component, or not a relative POSIX path. |
| `path_not_python` | Not a `.py` file. Manifests are obelize's to write, never a model's. |
| `path_not_the_consulted_file` | A repository `.py` path other than the one asked about. |
| `file_changed_since_read` | The file changed since the plan read it, so the line numbers point elsewhere. |

Is this an answer to the question:

| Value | Meaning |
|---|---|
| `outside_the_context` | The replaced range is not inside the range sent. |
| `site_not_replaced` | The range does not contain the line asked about. |
| `symbol_mismatch` | It names another symbol, or the consultation named none to check. |

Is what it produces Python, and does it bring anything in:

| Value | Meaning |
|---|---|
| `replacement_too_large` | Over ADR-003's diff size limit, in lines or bytes. |
| `replacement_not_displayable` | A control, format or surrogate character other than tab or line break: the line a reviewer reads is not the line that runs. |
| `replacement_not_encodable` | Not writable in the file's own encoding. |
| `output_does_not_parse` | libcst refuses the result. |
| `output_does_not_compile` | `compile()` refuses it: `await` outside `async` passes libcst and fails here. |
| `replacement_runs_past_its_range` | It changes how the following lines read (a trailing backslash or open bracket, or an opened block or string), though it parses and compiles. |
| `import_outside_the_target` | It imports a module the pack does not target, `__import__` and `importlib.import_module` included. |
| `name_outside_the_question` | It uses a name nothing licenses: not in the replaced lines, not bound by a target-module import or by itself, not an allowed builtin; never a double-underscore name. Catches `imp = __import__`, `exec("import os")`, `open(...)`, a module the file already imported. |

#### What became of a proposal (`ProposalOutcome`)

`outcome`, first match in this order: three about the answer, five about what
the run did with it.

| Value | Meaning |
|---|---|
| `unanswered` | The adapter raised; `failure` says why. The row stays `needs_review`; the next row is still asked. |
| `nothing_proposed` | The endpoint answered `{"proposal": null}`, a normal answer. |
| `guard_refused` | `refusal` says which guard refused it. |
| `not_applied` | Accepted; the run had no `--apply`. |
| `not_accepted` | Accepted; `--accept-model` was not given. |
| `file_already_proposed` | Accepted, and an earlier proposal holds this file. The guard checks a whole file, so a file takes one model edit per run; the next run asks about the rest. |
| `write_refused` | Accepted, and the apply was refused: a file can change between the tree gate and the write. |
| `written` | On disk; its `Edit` row reads `model_proposed`. |

## `undo.json`

Written into an existing run folder by `obelize undo` only. Not a run; no id of
its own.

| Field | Type | Description |
|---|---|---|
| `run_id` | string | The run whose `file_edits[]` and snapshots it used. |
| `obelize_version` | string | The `__version__` that performed the undo. |
| `exit_code` | integer | `0` when every file was reverted, `4` otherwise; derived from `files[]`. |
| `argv` | array of strings | The arguments the undo was invoked with. |
| `undone_at` | string | UTC, to the second, with the `Z`. |
| `files` | array | One row per file the run recorded writing, in path order. No count beside it, which could disagree. |

### `undo.json` `files[]`

| Field | Type | Description |
|---|---|---|
| `path` | string | Repository-relative, forward slashes on every platform. |
| `outcome` | string | `reverted` or `skipped`. |
| `reason` | string or null | Set exactly when `skipped`: one of [CLI.md](CLI.md#why-a-file-was-not-put-back). |
| `recorded_sha256` | string | The run's `after_sha256`, which the file must still have. |
| `current_sha256` | string or null | What is there now; `null` when unreadable. |
| `snapshot` | string | The pre-migration copy under `snapshots/before/`, recorded even on a skip. |

`hash_mismatch` is exactly `current_sha256` set and unequal to
`recorded_sha256`. There is no `undo --force`: the refusal names
both hashes and where the original is.

## Stability

Every format here is unstable through 0.x
([CHANGELOG.md](../CHANGELOG.md#stability)) and carries no version number; a
change lands with this file, the model and the schema together. `verify` and
`undo` validate `run.json` against the closed model that wrote it, so a folder
from a different obelize may be refused rather than half-read.

`run.schema.json`, `findings.schema.json`, `plan.schema.json`,
`undo.schema.json`, `model.schema.json` and `proposal.schema.json` in
`src/obelize/schemas/` are generated from the models and committed;
`ci / schema-drift` fails when one is stale. Every object is closed and every
field required, because every writer writes every field.

## What `e2e` asserts today

`.github/workflows/e2e.yml` runs the flow against `examples/gemini-legacy-app`
and checks:

| Assertion | Step |
|---|---|
| `.obelize/latest` names a run folder containing `run.json` | after `fix --apply` |
| `run_id` and `obelize_version` are non-empty strings | after `fix --apply` |
| `mode` is `apply` | after `fix --apply` |
| `pack.id` is the requested pack and `pack.sha256` is 64 hex characters | after `fix --apply` |
| `git_dirty` is `false` | after `fix --apply` |
| `exit_code` is `4` | after `fix --apply` |
| `file_edits` is empty and `idempotent` is `true` | after `fix --apply` |
| `counts.auto` is `0`, `withheld` has fourteen rows, and exactly one of them is `configure_consumed_elsewhere` | after `fix --apply` |
| `verify.status` is `not_run` and `verify.reason` is `no_changes_to_verify` | after `fix --apply` |
| `findings.json`, `plan.json`, `patch.diff`, `pack.yaml`, `pack.sha256` and `REPORT.md` all exist | after `fix --apply` |
| `idempotent` is `true` and `file_edits` is empty | after the second `fix --apply` |

`tests/unit/test_run_folder_contract.py` checks that the workflow reads only
fields specified here and reads every one this table claims.

The example gets no edit: `summarize.py` and `conversation.py` run on
`summarizer/config.py`'s `configure`, so that file is withheld as
`configure_consumed_elsewhere`. A
more automatic result is a rules change to argue, not a number to update.
`tests/e2e/` asserts the same in-process; the workflow runs a built wheel in a
clean interpreter.
