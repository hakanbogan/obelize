# Command-line interface

Every command, flag and exit code of obelize. `obelize <command> --help` prints the same text in
your terminal, and a release is checked against this page ([RELEASING.md](RELEASING.md)). The
decisions behind it are indexed in [DECISIONS.md](DECISIONS.md).

## Surface

```
obelize scan   [--repo .] [--pack <id|path>]... [--library <distribution> [--module <module>]...]
            [--json | --sarif] [--fail-on <status>]... [--jobs N] [--list-files]
obelize fix    [--pack <id|path>]... [--repo .] [--apply] [--allow-dirty] [--verify "<cmd>"]... [--timeout <s>]
            [--non-interactive] [--trust-repo-config] [--model <provider>] [--accept-model]
            [--show-context] [--json]
obelize verify --run <id> [--repo .] [--verify "<cmd>"]... [--timeout <s>]
            [--non-interactive] [--trust-repo-config] [--current] [--json]
obelize undo   --run <id> [--repo .] [--json]
obelize mcp    [--repo .] [--trust-repo-config] [--read-only]
obelize outdated [--repo .] [--all] [--json] [--offline]
obelize upgrade <distribution> [--from <version>] [--to <version>] [--module <module>] [--repo .]
            [--offline]
obelize pack validate <id|path>
obelize pack test     <id|path>
obelize pack new      <id> --from "<requirement>" --to "<requirement>" --guide <url>
            [--module <module>] [--to-module <module>] [--requires-python <range>] [--dir <path>]
obelize pack synth    <distribution> --from <version> [--to <version>] [--module <module>]
            [--dir <path>] [--offline]
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
| `--pack <id\|path>` | A pack id or a pack file path; repeat it to run several, and only those run. Without it every known pack is tried over one read of the repository, and each one with a finding that is not `not_a_usage` runs ([several packs](#several-packs-in-one-run)). |
| `--library <distribution>` | List every place the repository uses a library, with no pack ([an inventory](#listing-a-library-with-no-pack)). It cannot be combined with `--pack`. |
| `--module <module>` | A module of `--library` to list, as it is imported. Repeat it to name several. |
| `--json` | Findings as JSON on stdout; the run folder's path on **stderr**. |
| `--sarif` | Findings as [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html), the format GitHub code scanning reads, on stdout instead of the table; the run folder's path on **stderr**. It cannot be combined with `--json`. One result per finding except `not_a_usage`; its rule is the finding's reason, or `eligible`, and its level is `note` for `eligible`, `warning` for `needs_review` and `error` for `unsupported`. Two runs over the same input print the same bytes. |
| `--fail-on <status>` | Exit `4` when any finding has this status: `eligible`, `needs_review` or `unsupported`. Repeat it to name several. The output is the one you asked for, and the run folder records the exit code. |
| `--jobs N` | Worker processes; `1` is in-process. Default `min(8, cpu_count - 1)`, in-process below 32 prefilter survivors; an explicit `N` is always used, up to the 61 a Windows process pool takes. Never changes the output. |
| `--list-files` | Print the selected files in order and stop, reading no file. The pack is still loaded (an invalid one exits `7`). |

Writes a run folder and updates `.obelize/latest`
([RUN_FOLDER.md](RUN_FOLDER.md)). `--json` output equals the folder's
`findings.json` byte for byte and holds nothing time-derived (run id, timings
and paths are in `run.json`), so runs over the same input compare equal.
Evidence is written before anything is printed; failing to write it exits `1`.

Exit codes: `0` done, findings or not, and also when no pack applies; `4` a finding has a status
`--fail-on` names; `7` invalid pack; `2` usage
error, including a `--pack` named twice, a `--fail-on` that names another status, `--json` with `--sarif`, two packs that cannot run together, a `pack_dirs` entry
that is not an existing directory, a `--repo` that is not a directory, `--jobs` below 1 or above 61 on Windows, and an unusable
`.obelize.yml`; `1` unexpected error, including an unwritable run folder.

### Listing a library with no pack

When no pack applies, `scan` prints the libraries the repository imports most. To see every place
the code uses one, name it:

```sh
uvx obelize scan --library requests
```

An inventory lists each import, call and attribute of the library's modules and writes nothing.
Every place is `needs_review` with the reason `no_pack_for_usage`, since no migration pack says how
to move it, and the library's lines in a dependency manifest are context. The modules are, in this
order: the ones `--module` names; the ones the library installed in a `.venv`, `venv` or `env`
directory in the repository, read from its `RECORD` without importing anything; the library's name.
A library imported under another name (`PyYAML` is `yaml`) needs `--module` when it is not
installed in the repository. The run folder records the pack as `inventory/<distribution>`, with a
hash of the modules it listed and no copy of a pack.

### A CI check

To fail a CI job while the repository still has something left to migrate, name the statuses that
count:

```sh
uvx obelize@X.Y.Z scan --fail-on eligible --fail-on needs_review --fail-on unsupported
```

It exits `4` if any finding has one of those statuses and `0` otherwise. `not_a_usage` is context
only (a mention in a comment or string, or a legacy pin something else may still need), so no
status you can name matches it. A legacy pin that nothing imports is a finding,
`manifest_code_mismatch`: remove it. The scan still writes its run folder under `.obelize/` in the
checkout, and the `.gitignore` inside keeps it out of `git status`. Replace `X.Y.Z` with the version
you tested, since any 0.x release can change the JSON ([CHANGELOG.md](../CHANGELOG.md#stability)).

#### In GitHub Actions

The repository's action runs that scan, prints one annotation per place on its file and line, adds a
summary, uploads the findings to code scanning if you ask, and then fails the job:

```yaml
permissions:
  contents: read
  security-events: write # only for sarif: true

steps:
  - uses: actions/checkout@<commit>
    with:
      persist-credentials: false
  - uses: hakanbogan/obelize@<commit> # vX.Y.Z
    with:
      version: X.Y.Z
      sarif: true
```

| Input | Description |
|---|---|
| `version` | Required. The obelize release to run. Pin it: any 0.x release can change what a scan reports. |
| `packs` | Pack ids, separated by spaces. Default: every pack the repository uses. |
| `library`, `modules` | A distribution that has no pack and the modules it is imported as: [an inventory](#listing-a-library-with-no-pack). Not with `packs`. |
| `fail-on` | The statuses that fail the job, separated by spaces. Default `eligible needs_review unsupported`; empty fails on none. |
| `sarif` | `true` uploads the findings to code scanning. Default `false`. |
| `working-directory` | The repository root to scan. Default `.`. |

The outputs are `exit-code` and `sarif-file`. GitHub shows the first ten annotations of each level;
code scanning shows all of them. The action checks each input against the shape it may have before
it reaches a command line. Hold the action to a commit like any other, and never run it on
`pull_request_target`: that event gives the job a token that can write, and a scan reads the pull
request's files.

#### With pre-commit

```yaml
repos:
  - repo: https://github.com/hakanbogan/obelize
    rev: vX.Y.Z
    hooks:
      - id: obelize-scan
```

The hook runs `obelize scan` on the whole repository whenever a Python file is staged, and fails
while a finding has the status `eligible`, `needs_review` or `unsupported`. Set `args` to change
that, for example `args: [--pack, py-pdf/pypdf2-to-pypdf, --fail-on, needs_review]`. obelize needs
Python 3.12 or newer, so the hook's environment must be built on one.

**Monorepos.** The root is `--repo` (default: the current directory). The configuration,
`.obelize/` and every `include` and `exclude` pattern are relative to it, and every dependency
manifest below it is read. Run once at the top to migrate everything in one run, or once per package
with `--repo` to keep one package's run folder and one `undo` apart. A pack that moves a whole
repository (`openai`) moves the whole root or none of it. A module only the legacy distribution
installed counts as declared for a file where a manifest in its directory or above it declares it, so
one app's declaration does not cover another app.

## `obelize fix`

Plan a migration and, with `--apply`, write it. Without `--apply` nothing is
modified.

| Flag | Description |
|---|---|
| `--pack <id\|path>` | As for `scan`. |
| `--repo <path>` | Repository root. Default: the current directory. |
| `--apply` | Write the planned edits. Without it no source file is written: the terminal lists each file's hunks, then prints up to 200 lines of the unified diff, with secrets redacted and control characters escaped, and the path of `.obelize/runs/<id>/patch.diff`, which holds all of it as it is. |
| `--allow-dirty` | Permit `--apply` with uncommitted changes. Without it, **any** modified or staged tracked file in the whole repository, or an untracked file on the plan, refuses the apply (other untracked files do not count, and the report counts the paths and never names them), so the `git diff` is the migration alone; so does `tree_unknown` (git failed, timed out or refused the directory). A run with no file to write and no model configured does not look at the tree. A dirty tree is recorded in the report. |
| `--verify "<cmd>"` | A verification command. Runs only with `--apply`, which refuses a program that cannot start (not on `PATH`, or not an executable file) with exit `2` before anything is read. Repeatable. Replaces the repository's, and runs without asking. |
| `--timeout <s>` | Override `verify.timeout_s` (at least 1). Neither set, it is 600. |
| `--non-interactive` | Never prompt; refuse a repository command not on the user allowlist unless `--trust-repo-config` is passed. |
| `--trust-repo-config` | Trust the repository's `verify.commands` in a non-interactive or CI run. |
| `--model <provider>` | `none` or `openai_compat`, replacing `model.provider` from [your own file](#the-user-files-configobelize) for this run. With more than one pack, or a pack that [moves a whole repository](#several-packs-in-one-run), a model is not asked: `--model openai_compat`, or `--accept-model` while a model is configured, exits `2`, and a model only your own file configures is skipped with one line on stderr. `--model none`, and `--accept-model` with no model configured, change nothing. |
| `--accept-model` | Also write the model's edits that passed validation. Requires `--apply` (exit `2` otherwise). Without this flag a proposal is only in `plan.json`, `patch.diff` and `model/`. |
| `--show-context` | Print what would be sent to a model and stop: no request, no run folder. Works with `provider: none`; not with `--apply`; needs exactly one pack, and not one that [moves a whole repository](#several-packs-in-one-run). |
| `--json` | `plan.json`'s bytes on stdout; the run folder's path on **stderr**. |

**Phase order:** check the working tree and every planned path; consult a
configured model; run the baseline verification; write the patch; compile every
`.py` file written; verify again. The last two belong to the verification: with
no command to run, or after a failing baseline, they do not run, and the only
compile check of the written bytes is the one the rules already made in memory
(`output_does_not_parse`). Consequences, each a case in
`tests/fixtures/commands/` or `tests/fixtures/providers/runs.yaml`:

- The gate refuses an apply before any command runs, and before anything is sent to a model
  unless the file is one a model proposed. A refusal no gate can see in advance comes later, with
  the baseline already run: a tracked file a baseline command changed, or a race.
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
should accept `0` and `4`. `--json` prints `plan.json`, which holds the edits the
rules made or refused; the findings left for review, one row each with the code
that held it, are in `run.json`'s `withheld[]`, so read that file to list them.

**The summary ends with the next step**: a `Next:` line holding the command to run after a dry run
that planned a file (`obelize fix --apply`), after an apply that exits `0`, `4` with review items,
`5` or `6`, and after a `scan` with an `eligible` row and no blocked pack (`obelize fix`). A command
repeats the `--pack` and `--repo` you gave. After an apply that wrote a manifest pin with a lock file
(`uv.lock`, `poetry.lock`, `Pipfile.lock` and the like) in the manifest's directory or above it, one
more `Next:` line comes before it, naming those files, which obelize does not edit, and saying to
regenerate each with the tool that made it; it holds no command, since a command would have to come
from the repository. A lock in a sibling or a subdirectory belongs to another project and is not
named. `REPORT.md` says the same under Dependency manifests, for a dry run too.

**Findings left for you** are summarised whenever there are any, with a file written or not: how
many, the most common reasons with a sentence on what to change for each (the last column of
[SCAN_VOCABULARY.md](SCAN_VOCABULARY.md#4-bail-codes-editreason)), up to five of the rows that cause them (`path:line symbol code`,
with `and N more in REPORT.md` after them), the files that hold the pin without a row (a notebook
that calls the legacy API, which obelize reads and never writes, a file it does not analyse, or, for
a pack with one distribution for both APIs, a `.py` file it could not read; migrate them by hand,
raise `max_file_bytes`, or list one under `exclude` to migrate the rest), and a link to what
each code means. A pack whose one distribution holds both APIs adds a line saying the whole
repository moves or none of it.

**A warning on an edit that is written** (or would be, in a dry run) is printed as
`Check <file>:<line>: <code>: <what to look at>`. After `--apply` the line is the one before the
change, and the line says so.

**What a pack says about the findings it flagged** follows the counts, in `scan` and in `fix`: for
each of its flagged changes that claimed a finding, its id, how many findings, its message and its
suggestion. `REPORT.md` has the same under Guidance, and lists every limitation of the packs that
ran under Limitations and their verification suggestions under Verification. `--json` prints none
of it.

**With a model configured**, one stderr line first names the provider, the host
of `base_url` (never the URL, which can carry a credential) and the model. The
run adds `run.json`'s `model` object and a `model/` directory with one file per
consultation ([RUN_FOLDER.md](RUN_FOLDER.md)). A written model proposal stays
in `withheld[]`: validation shows that an edit is safe to apply, not that it is correct.

**With verification commands**, one stderr line comes before each phase of tests, before the write
and after it (`verify` prints it for its one phase): how many commands are about to run and after
how many seconds each is stopped. It never names a command, which can carry a credential.

### Several packs in one run

`scan` and `fix` read the repository once and scan it with every pack they try. A pack runs when
`--pack` names it, or, without `--pack`, when it has a finding that is not `not_a_usage` or a file
that uses its legacy API and that no rule writes (a notebook, a stub); a run
that chooses none prints `No pack applies. Checked: <ids>.`, writes a run folder with `packs: []`
and exits `0`.

Two packs that cannot run together are refused (exit `2`): their legacy modules overlap, one writes
a module the other migrates, or they name one distribution. Otherwise the packs run in id order,
each over what the ones before it wrote, in memory, and the run has one gate, one write, one
verification and one `undo`. Each pack keeps the file and manifest rules of a single run, so one can
leave a file untouched while another writes it, and a pack the repository rules out (a declared
Python it cannot install on, a legacy pin it was not measured on, a pin of the new library below
the releases it writes) is withheld alone, for that reason. An edit's `rule_id` is
`<pack id>:<rule id>`, and its `line` is in the file as its pack saw it.

A pack whose new library is the same distribution as the old one (`openai/openai-0-to-1`: `openai`
0.x and 1.x are one install) is all or nothing inside its own turn, and its tests can run against
only one release at a time. To check it: pass your tests on 0.x, run `obelize fix --apply`, install
the release the pin names (`uv pip install --python .venv/bin/python "openai>=1.109.1"`), then
`obelize verify --run <id>` with the `<id>` the `Next:` line or `.obelize/latest` gives. `--verify` on
the `fix` itself cannot work once 1.x is installed, because the baseline then fails. One pin serves both APIs, so
while any row of the pack is withheld, whatever the reason, it writes no file and leaves the pin,
each row of another file it would have written reads `repo_not_fully_migrated`, and an apply exits `4`. `scan` still
grades each file on its own, so it can show `eligible` rows that `fix` then withholds. A declaration
of `openai` that already admits only 1.109.1 or later is left as written. One that cannot be rewritten
in place, with extras, a URL, a hash or an editable requirement, holds every file too: `scan` marks it `manifest_pin_shape_unsupported`.

A model is never asked about such a pack: a proposal is one row, and the pack writes a whole
repository or none. `--model openai_compat`, `--accept-model` while a model is configured, and `--show-context` exit `2`
with it, as with several packs, and a model
only your own file configures is skipped with one line on stderr:
`The configured model was not asked: <pack> moves a whole repository.` For several packs the line
ends `this run uses more than one pack.` `fix` prints it, and `No pack applies`, on stderr, so
`--json` keeps stdout to one document.

## `obelize verify`

Re-run an existing run's verification and update its evidence.

| Flag | Description |
|---|---|
| `--run <id>` | Required. The run id under `.obelize/runs/`. |
| `--repo <path>` | Repository root. Default: the current directory. |
| `--verify "<cmd>"` | A verification command. Repeatable. Replaces the repository's. |
| `--timeout <s>` | Override `verify.timeout_s` (at least 1). Neither set, it is 600. |
| `--non-interactive` | Never prompt; refuse a repository command instead. |
| `--trust-repo-config` | Trust the repository's `verify.commands` for this run. |
| `--current` | Check the tree as it stands, even where it differs from what the run wrote, and record which files differ in `verify.edited` instead of answering `tree_changed`. A run that wrote no file can be checked this way. |
| `--json` | The run's record as JSON on stdout instead of the summary: the bytes of the `run.json` it wrote. The run folder's path goes to **stderr**, and the exit code is the verdict's. |

If the files still match the run's `after_sha256`, the after-phase runs again;
otherwise the result is `inconclusive` / `tree_changed` and nothing runs, unless you pass
`--current`, which runs it on the tree as it stands (a person or an agent finished the migration by
hand) and lists the files that differ. If
the run's baseline did not pass, nothing runs and the recorded verdict stands.
Commands come from your configuration and trust is decided again, never from
the run folder, which a repository could forge (a forged record). Only the
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
| `--json` | What became of each file as JSON on stdout instead of the summary: the bytes of the `undo.json` it wrote. The run folder's path goes to **stderr**, and the exit code is `0` or `4` as before. |

A file is reverted only if its current hash equals the run's after-hash, and
only from a snapshot whose bytes match its content-addressed name. Otherwise it
is skipped and reported with both hashes and its snapshot path under
`.obelize/runs/<id>/snapshots/before/`. No `--force`: obelize never overwrites
content it did not write. `undo.json` gets a row for **every** file the run
wrote, so a partial undo cannot read as complete
([RUN_FOLDER.md](RUN_FOLDER.md#undojson)). A file that already holds its original counts as put
back, so a second `undo` of the same run exits `0`, and it leaves the first `undo.json` as it was.
`undo` reads no `.obelize.yml`, so a mistake in it never stands between you and putting files back.

The record formats change between 0.x releases. A run another release wrote, whose `run.json` this
one cannot read, exits `2` and names that release with the command that undoes the run:
`uvx obelize@<version> undo --run <id>`. `verify` says the same.

### Why a file was not put back

A closed set (`models.UndoSkip`).

| Value | Means |
|---|---|
| `hash_mismatch` | Edited after the run. Both hashes and the snapshot path are printed, and "(already the original)" when the file holds its original again, after an earlier undo for example. |
| `missing` | Nothing is at that path. |
| `not_a_file` | Not a regular file. |
| `outside_root` | The recorded path leaves the repository, or is in `.git/` or `.obelize/`, which a run never writes: the run folder was edited by hand. |
| `snapshot_unusable` | The snapshot is absent or does not match its name; `patch.diff` still describes the change. |
| `symlink` | Now a symbolic link, which obelize never follows. |
| `unreadable` | Could not be read, or the replacement could not be written. |

Exit codes: `0` all reverted; `4` nothing reverted or files skipped, including
an apply that wrote no file; `2` usage error, including a malformed run id, a
missing run folder, and a plan or scan run; `1` unexpected error, including
files restored but `undo.json` unwritten (the message says which).

## `obelize mcp`

Serve obelize to a coding agent over the [Model Context Protocol](https://modelcontextprotocol.io),
on standard input and output. Start it from the agent's own configuration, not in a terminal:

```json
{ "mcpServers": { "obelize": { "command": "uvx", "args": ["obelize", "mcp"] } } }
```

| Flag | Description |
|---|---|
| `--repo <path>` | The repository to serve. Default: the current directory. The tools take no path. |
| `--trust-repo-config` | Let the verification tools run the commands in this repository's `.obelize.yml` without asking, as for `verify`. Only you can set it: no tool can. |
| `--read-only` | Leave out `obelize_apply` and `obelize_undo`, the two tools that write source files. The others still write the run folder under `.obelize/`, and `obelize_verify` runs your tests. |

Each tool runs the command of the same name as a child process and returns what it printed, so a
tool does what the command does: a dirty tree is refused, a verification command that is not trusted
does not run, and no model is consulted. The result is JSON text holding the exit code and what it
means, the run id and the path of its folder, and the document the command printed.

| Tool | Runs | Arguments |
|---|---|---|
| `obelize_scan` | `scan --json` | `packs`, or `library` with `modules` |
| `obelize_plan` | `fix --json` | `packs` |
| `obelize_apply` | `fix --apply --json --non-interactive` | `packs` |
| `obelize_residue` | `scan --json`, then the code around each place left | `packs`, `limit` |
| `obelize_verify` | `verify --json --non-interactive` | `run`, `current` |
| `obelize_report` | reads `REPORT.md` | `run`, default the latest |
| `obelize_undo` | `undo --json` | `run` |

An argument is a pack id, a distribution name, a module name, a run id, a number or a boolean, each
checked against its shape before it reaches a command line, and a list holds at most 32 names. A pack
must be one obelize knows, from the wheel or a directory your own configuration lists; a file in the
repository cannot be named. `obelize_verify` and `obelize_undo` take only a run this session made,
so a run folder the repository carries is not one. No tool takes a command to run, a path, a model or
a consent. `obelize_residue` gives each place a scan could not migrate with its reason,
what to change and the code around it (the window a model would be shown, redacted by the same
redactor), and the pack's guidance; an agent edits those places and calls `obelize_verify` with
`current` set. What a tool returns quotes the repository's code and is data, not instructions.

`--trust-repo-config` trusts the `.obelize.yml` the repository had when the server started: an edit
of that file, or one created later, ends the trust until you restart the server. Whichever commands
you allow, they run your tests, and your tests run the code the repository holds, an agent's edits
included; the tools cannot tell a test from an edit, so give the server to an agent you would let
run the tests yourself. A result is cut to about 200 KB, saying so; the child process starts with `-P`,
so a file of the repository cannot stand in for one of obelize's imports.

Exit codes of the command: `0` the client closed the stream; `2` `--repo` is not a directory.

## `obelize outdated`

List the dependencies a repository declares that the package index says have moved on. It reads the
manifests, asks the index about each distribution, and installs nothing and writes nothing. Every
host is printed on standard error before it is contacted.

| Flag | Description |
|---|---|
| `--repo <path>` | Repository root. Default: the current directory. |
| `--all` | Also list the dependencies that are current. |
| `--json` | The rows as JSON on stdout, a document described by `outdated.schema.json`. |
| `--offline` | Reach no host: use only what an earlier run kept in the cache. |

A row has the distribution, the declaration as written, the release it starts at (the one it pins,
else its lower bound), the newest release that is neither withdrawn nor a pre-release, and the gap
between them: `major`, `minor`, `patch`, `none`, or `unknown` where the declaration names no
release. It carries the flags `inactive` (the library marks itself `Development Status :: 7 -
Inactive`), `yanked` (the release in use was withdrawn) and `advisory` (the index lists a
vulnerability for that release; the ids are in `advisories`), and what obelize can migrate it with:
`bundled` (a pack that migrates that release; the id is in `pack`), `synthesizable` (two releases to
compare with `pack synth`) or `none`. A distribution the index does not have is a row whose `error`
says so, as a private one would be. By default only rows with a flag, a major gap or an error are
listed, worst first: an advisory, then the size of the gap.

Exit codes: `0` listed; `2` the request is wrong (a `--repo` that is not a directory, an invalid
configuration file); `6` the index answered no question for any distribution.

## `obelize upgrade`

Show what moving one dependency to a newer release would change, and write nothing in the
repository. It plans the migration as [`fix`](#obelize-fix) does without `--apply`, with the pack
that suits the move.

| Flag | Description |
|---|---|
| `<distribution>` | Required. The dependency to move, as the manifests name it. |
| `--from <version>` | The release the code is written for. Default: the one the manifests pin, else their lower bound; required when they name none. |
| `--to <version>` | The release to move to. Default: the newest that is neither withdrawn nor a pre-release. |
| `--module <module>` | The module to compare, as for [`pack synth`](#obelize-pack-synth). |
| `--repo <path>` | Repository root. Default: the current directory. |
| `--offline` | Reach no host: use only what an earlier run kept in the cache. |
| `--apply` | Try the move in a copy of the repository, and write it only if the tests agree ([a trial](#a-trial)). |
| `--yes` | With `--apply`, agree to the trial without being asked. |
| `--python <version>` | The Python the trial's environments use. Default: the repository's `.python-version`, else uv's own. |
| `--test-command "<cmd>"` | The tests to run in the trial. Default: pytest, if the repository is set up for it. |
| `--branch` | With `--apply`, commit the move to a new branch and leave the working tree as it is. Nothing is pushed. |
| `--branch-name <name>` | The branch `--branch` makes. Default: `obelize/upgrade-<the release moved to>`, such as `obelize/upgrade-pydantic-2.5.0`. Giving a name implies `--branch`. |
| `--agent <backend>` | With `--apply` and `--branch`, put the places the pack only flags to your own coding agent, in the trial's copy (`claude_code`). Overrides `agent.backend`. |
| `--max-asks <n>` | The most places `--agent` is asked about in one round (at least 1). Default `50`. |
| `--max-rounds <n>` | The most rounds `--agent` is put the tests that broke after the move (at least 0). Default `3`; `0` asks none. |

The pack is, in this order: a known one (a bundled pack, or one in a directory of your own) that
migrates the dependency from that release and, if you named `--to`, to that one; else the pack
made from the public API of the two releases, kept in the cache under the name of both, so the same
move reads the index once. The first line says which, and the rest is what `fix` prints, with its
run folder under `.obelize/`. Exit codes are `fix`'s, plus `2` for a dependency the manifests do not
name when `--from` is missing, a version or a library the index does not have, and nothing that
changed between the releases, `6` for an index that could not be reached, and `1` for a pack
obelize made that fails its own checks.

### A trial

`upgrade --apply` writes nothing until the move has been tried. It asks first, because a trial
installs packages, which runs their build scripts, and runs the repository's tests: `--yes`, or an
answer at a terminal when `CI` is not set; otherwise it exits `2`. A tree with uncommitted changes
is refused (exit `5`) before anything starts. Then, in a copy of the repository made from the files
git lists and in two environments made with [uv](https://docs.astral.sh/uv/), outside the
repository:

1. the dependencies are installed (from `uv.lock`, else `pyproject.toml`, else the
   `requirements*.txt` at the top of the repository), plus pytest, once with the release in use and
   once with the release moved to installed over it;
2. the tests run on the unchanged copy with the first environment;
3. the move is written to the copy;
4. the tests run on the changed copy with the second environment, and the tests that failed are run
   once more.

The tests are `python -m pytest --tb=native -q --continue-on-collection-errors`: a module that does
not import is an error in both runs and does not hide the tests of the others. A module that
imports before the move and not after it is a break.

A test is its junit `classname::name`. The move is **written to your repository** only if no test
that passed in step 2 now fails, errors or is missing, not counting one that passed on the second
try; the real write is `fix --apply` and ends `0` then. Otherwise nothing is written: exit `3` names
the tests that broke, and exit `6` says the trial could not judge (no tests, no result obelize can
read, no test that passed before, or a move that changed no file). Exit `6` also ends a trial whose
environments could not be made.

With `--branch`, a passed trial is committed instead of written: one commit on a new branch of the
name you gave (or the default), on top of `HEAD`, holding the files the move wrote, with the trial's
id as a trailer (`Obelize-Trial:`). It is built with git's plumbing from the bytes the trial wrote
into its copy, so your working tree, your index and your uncommitted work are untouched, no hook runs and the
commit is not signed. A branch that exists is never moved (exit `2`), and the command never pushes.
Review it with `git log -p -1 <branch>`.

#### The places a pack only flags

A library that keeps its import name across the move is one distribution for both APIs, so the
rules write nothing while one flagged place is left, and a pack made from two releases flags most
of what changed. `--agent claude_code` (with `--apply` and `--branch`) puts each flagged place to
your own coding agent, in the trial's copy and before the rules run again: the agent is the
`claude` program on your `PATH`, started in an empty directory with every tool off, no session, no
MCP server, no skill and none of your settings (so no hook of yours runs), and with a fixed list of
environment variables; a program that does not offer those restrictions is not used. It is sent the
pack's own words about the place and the lines around it, redacted, as a text question, and asked
for one edit of those lines or none. The guard that checks every model proposal checks it: it must
stay inside what was sent, parse, and name or import nothing beyond the question. An accepted edit
goes into the copy, the rules then write the rest, and your tests judge the whole. What the agent
changed is named in the commit message and in `trial.json`, because it is the part to read first.
Nothing it writes reaches your working tree: that is why `--agent` needs `--branch`.

If tests that passed before the move now fail, the agent is put them too, up to `--max-rounds`
times (3). A failing test points, in its Python traceback, at the lines where it broke; where such a
line is in a file the move wrote and is not a test, that place goes to the agent with the error, and
the tests run again. A test file is never edited: it is the evidence. The rounds stop when the agent
offers nothing or no fewer tests break, and a move whose tests still fail is not written.

Your own login decides where the excerpts go, as it does for anything you ask `claude`; see
[the privacy notes](PRIVACY.md#what-obelize-upgrade---agent-sends). The evidence is `.obelize/trials/<id>/`: `trial.json`, the junit
file and output of each run, and what each environment held (`old.txt`, `new.txt`).

## `obelize pack validate`

Validate a pack against [PACK_SPEC.md](PACK_SPEC.md): every field, vocabulary
and [cross-field rule](PACK_SPEC.md#validation-errors), each error naming the
key's path. Declared fixture paths are checked as paths, not for existence,
since a local pack need not ship fixtures (the last output line says so).
`source.url` is never requested.

| Argument | Description |
|---|---|
| `<id\|path>` | A bundled pack id (`gemini/google-generativeai-to-google-genai`, `openai/openai-0-to-1`, `py-pdf/pypdf2-to-pypdf`) or a pack file path (`./pack.yaml`). An id wins over a path spelled the same; anything not shaped like an id is a path. |

Exit codes: `0` valid; `7` invalid YAML or schema; `2` nothing to read there;
`1` a **bundled** pack is invalid (an obelize defect; the message links the
issue tracker).

## `obelize pack test`

Run a pack over its own fixtures and sources. `pack validate` reads the pack alone; this
command checks it against the files beside it, with the checks the three bundled packs pass in
the test suite:

- every fixture the pack names is on disk, every file under `fixtures/` is named, and every
  answer key (`<name>.after.<ext>`) sits beside its input;
- every change has a positive and a negative fixture;
- every Python fixture parses, reads back byte for byte and compiles;
- a positive fixture holds a prefilter token and a negative one does not, so the scan skips it
  (a shared module's negatives are scanned instead and must find nothing to migrate);
- an answer key exists for exactly the fixtures a run migrates whole, and each is what the rules
  write into its fixture, the dependency fixture included;
- applying the pack twice writes what applying it once did, and two runs write the same bytes;
- `SOURCES.md` has a section for every change, none for a change that does not exist, and names the
  source url and, if the pack records one, the hash of the page.

| Argument | Description |
|---|---|
| `<id\|path>` | A pack id, a path to a pack file, or the folder that holds `pack.yaml`. |

The output is one line per check, `ok` or `FAIL`, and under each failure the file and the reason.
Exit codes: `0` every check passed; `7` a check failed, or the pack is invalid; `2` nothing to read
there; `1` a **bundled** pack failed (an obelize defect).

## `obelize pack new`

Make a pack that loads, with fixtures and sources to edit. The skeleton renames one module and moves
the dependency line, and its fixtures pass `pack test` as made. The `.after` files are what the
rules wrote into the fixtures, so read them before you trust them.

| Flag | Description |
|---|---|
| `<id>` | Required. The pack's id, `<provider>/<name>`, in lowercase letters, digits and hyphens. |
| `--from "<requirement>"` | Required. The distribution to migrate from and the releases, with a lower bound: `"PyPDF2>=3,<4"`. |
| `--to "<requirement>"` | Required. The distribution to migrate to and the releases: `"pypdf>=6.19"`. |
| `--guide <url>` | Required. The https address of the official guide the migration follows. It is cited and never requested. |
| `--module <module>` | The module code imports from the old distribution. Default: its name, with hyphens and dots as underscores. |
| `--to-module <module>` | The module code imports from the new distribution. Default: its name, the same way. |
| `--requires-python <range>` | The Pythons the new distribution installs on. Default `>=3.9`. |
| `--dir <path>` | Where to make the pack's folder, `<provider>/<name>`. Default: the current directory. |

It never writes into a folder that exists, and removes the one it made if the pack would not load.
Exit codes: `0` made; `2` the request is wrong or the folder exists. To use the pack from any
repository, put its directory in `pack_dirs` in your own `~/.config/obelize/config.yml`, or pass
`--pack <folder>/pack.yaml`.

## `obelize pack synth`

Make a pack from what two releases of a library offer, for a library that has none. The command
asks the package index for the project, downloads the two releases and the newest final release
between them, opens each for its Python source and nothing else, reads what each exports without
importing or building anything, and compares them. Every host is printed on standard error before
it is contacted.

The pack renames a name the library's own deprecation message says to use another for (`old_greet
is deprecated, use greet instead`), moves up a name that left a submodule for its package, flags the
rest for a person (removed, moved elsewhere, a signature that changed, deprecated) with the
library's words where it gave any, and moves the dependency line. Its fixtures are written from the
comparison and its `.after` files from the rules, as `pack new` does, and the pack is held to
`pack test` before it is kept. A change the rules cannot make as the comparison says is not made.

| Flag | Description |
|---|---|
| `<distribution>` | Required. The library on the index, such as `acme-kit`. |
| `--from <version>` | Required. The release the code is written for. |
| `--to <version>` | The release to move to. Default: the newest that is neither withdrawn nor a pre-release. |
| `--module <module>` | The module to compare, when the library has more than one. Default: the one both releases have, or the one named like the library. |
| `--dir <path>` | Where to make the pack's folder, `<provider>/<from>-to-<to>`. Default: the current directory. |
| `--offline` | Reach no host: read only what an earlier run kept in the cache. |

A name is renamed or moved only on evidence the two surfaces carry: it kept its name and signature
and has a body, or the library's message names one name beside it. Everything else that left the API
is flagged, never rewritten, and a pack made from two releases says in its limitations that a change
in what a function does is not in it. The tests of the repository show that.

It never writes into a folder that exists, and removes the one it made if the pack fails its own
checks. Which index it asks, and whether it may ask at all, are in
[your own configuration file](#the-user-files-configobelize), never in a repository's. Exit codes:
`0` made; `2` the request is wrong (a version or a library the index does not have, a module to
choose, nothing that changed, a folder that exists, a release that cannot be read); `6` the index
could not be reached or answered, or `--offline` found nothing kept; `1` a pack obelize made fails
its own checks.

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
| `6` | Verification produced no verdict (`inconclusive`, or `not_run` for any reason other than `policy_refused`); for `pack synth`, the index could not be reached |
| `7` | The pack is not valid |

`2` (argument parsing) and `1` (the top-level handler) take precedence; among
the rest the first match wins, in detection order: `7`, `5`, `3`, `6`, `4`,
`0`.

### Verification status and exit code

| `verify.status` | `verify.reason` | Exit | When |
|---|---|---|---|
| `pass` | none | `0` | Every command succeeded after the patch |
| `fail` | `command_failed`, `changed_file_does_not_compile` | `3` | A command failed after the patch, or a changed file does not compile |
| `inconclusive` | `timeout`, `tree_changed`, `baseline_failed`, `command_not_executable` | `6` | A verdict was expected and none was obtained |
| `not_run` | `no_verify_commands` | `6` | The patch was applied and no command was configured |
| `not_run` | `policy_refused` | `5` | A repository-sourced command refused in CI without trust |
| `not_run` | `dry_run`, `no_changes_to_verify` | n/a | No verdict was expected; the exit code comes from the plan |

Several commands give the worst status: `fail` > `inconclusive` > `not_run` >
`pass`. Trust is evaluated only when verification will run, so a run that wrote
nothing never refuses a command.

### The verification vocabulary

Closed sets, declared as `Literal`s in `src/obelize/models/vocabulary.py` and held equal
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
| `changed_file_does_not_compile` | `fail` | A `.py` file obelize wrote does not compile. Checked before the commands of the phase after the write, and so only where there are commands to run. |
| `command_failed` | `fail` | A command exited non-zero, any non-zero exit: pytest's `5`, which means no test was collected, is a failure here. |
| `command_not_executable` | `inconclusive` | A command never started: no such program, or no permission. |
| `dry_run` | `not_run` | No `--apply`. No exit code of its own. |
| `no_changes_to_verify` | `not_run` | An apply that wrote no file. No exit code of its own. |
| `no_verify_commands` | `not_run` | Files written, no command configured. Pass `--verify` or set `verify.commands`. |
| `policy_refused` | `not_run` | A repository command was not trusted in this mode; one refusal refuses the whole phase. |
| `timeout` | `inconclusive` | A command outlasted `verify.timeout_s`; its process group was killed, or its job object on Windows. |
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

At the repository root; flags take precedence. A file that does not parse, is larger than
1 MiB, or has an unknown, duplicate or wrongly typed key, exits `2` before anything is
read; it is never partially applied. A number or a flag is not read from text: `allow_dirty: "yes"`
and `verify.timeout_s: "60"` are errors, and so is a YAML set, which has no order.

| Key | Type | Default | Description |
|---|---|---|---|
| `include` | string | `**/*.py` | Files the scan considers, after all exclusions. Same semantics as `exclude`. |
| `exclude` | list of strings | empty | Patterns to skip, with git's `.gitignore` semantics (`pathspec.GitIgnoreSpec`): `legacy/*` excludes everything under `legacy/`, at any depth. Added to [the always-excluded set](#the-always-excluded-set); a `!` pattern re-includes only what this list excluded. |
| `verify.commands` | list of strings | empty | Verification commands, under the [trust rules](#trust-rules-for-verification-commands). Split with `shlex` and run without a shell, so a bare `\|`, `&&` or `>` is refused on load; use `sh -c "<command>"`, or `cmd /c "<command>"` on Windows. |
| `verify.timeout_s` | integer | `600` | Per-command timeout in seconds; on expiry the process group (the job object on Windows) is killed and the status is `inconclusive` / `timeout`. |
| `verify.junit` | boolean | `true` | Add `--junitxml` into the run folder to a `pytest` or `python -m pytest` command that has none, to compare per-test results with the baseline. |
| `allow_dirty` | boolean | `false` | Same as `--allow-dirty`. |
| `max_file_bytes` | integer | `2000000` | Larger files are recorded as a limitation, not parsed. |

**A `model:` block, `pack_dirs`, `network` and `agent` are refused** (exit `2`): where your code and
credentials go, which packs may rewrite your files, which index obelize reads code from and which
program your code is put to are not a repository's choice. Configure them in
[your own file](#the-user-files-configobelize), or name a pack with `--pack`.

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

Only these, and the `fixtures/` directory of a pack (below), skip a directory whole. **Your own
`exclude` never does**: an excluded file that still imports the legacy distribution is still named,
because the dependency pin it breaks is not excluded. Excluding means *do not
migrate*, not *do not look*.

**The `fixtures/` directory beside a pack file inside the repository is skipped the same way**, for
every pack of your own the run loaded (`--pack <path>`, or a directory of your own packs; the packs
the wheel carries add none): its fixtures are legacy code by design, and scanned they would be
rewritten. Only that directory goes. A file the pack sits beside is your own, is read, and still
holds the dependency pin when it imports the legacy distribution. A `pack.yaml` at the repository
root takes nothing, since a `fixtures/` there is as likely your own. `REPORT.md` says `Not scanned`
and names the directory, and `--list-files` leaves it out. `run.json` records no change: this is not
an `exclude`.

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
3. `compile()`, a depth check, then libcst: a refusal by any is one
   `parse_error` and no edit. `compile()` also catches what libcst accepts,
   such as `return` outside a function or a late `__future__` import, and an
   expression nested so deeply that libcst's parser would crash the process.
   Some versions of `compile()` accept a longer one, so the depth check
   refuses a file nested more than 300 levels deep (a chain of that many
   operands, attributes or calls, a dotted name, an `elif` ladder; brackets
   inside brackets count for more, so about a hundred of them are the limit).
4. Byte round-trip: if libcst does not reproduce the file exactly (bare-CR
   line endings, for example), every finding in it is withheld.

An unexpected error while obelize reads or rewrites one file does not end the
run: a scan reports the file as one `parse_error`, and `fix` leaves it as it was
and withholds its rows as `internal_error`. `run.json`'s `limitations` names
the exception's class, never its message. That is a defect in obelize, so
please report it.

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
4. A pack's `verification.suggestions`: **never**, under any flag; listed in `REPORT.md` as
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
shell can. On timeout the whole process group is terminated, then killed. On
Windows a command runs in a job object of its own, which the deadline terminates
at once, and only an `.exe` or `.com` program runs: a batch file is refused.

#### The user files (`~/.config/obelize/`)

Outside every repository, so no checkout can write them (`$XDG_CONFIG_HOME` is
honoured). On Windows the folder is `%USERPROFILE%\.config\obelize` unless `HOME`
is set. `config.yml` holds the four settings a repository may not make: the
allowlist, the model, the directories of your own packs and the index a command that reads
releases asks. Unknown keys are an error, and so is
a file larger than 1 MiB.

```yaml
# ~/.config/obelize/config.yml
verify:
  allow:
    - "pytest -q"
    - "python -m mypy src"
pack_dirs:
  - /home/me/obelize-packs  # absolute; each holds <provider>/<slug>/pack.yaml
network:
  index: https://pypi.org   # https, or http to this machine; no credential or query
  offline: false            # true: a command that reads releases uses only its cache
model:
  provider: none            # the default; no network call is made while it is `none`
  # base_url: "http://localhost:11434/v1"
  # allow_insecure_http: false
  # model: "qwen2.5-coder"
  # api_key_env: OBELIZE_MODEL_API_KEY
  # log_prompts: false
```

`pack_dirs` adds to the packs the wheel carries: a pack there is chosen by id like a bundled one,
and an id the wheel or another directory already holds is refused. Each entry must be an
absolute path to an existing directory (`~` is expanded), and a pack in one is validated like
any other file (exit `7`), never trusted more. A repository's `.obelize.yml` may not set it. A
directory inside a repository you scan is scanned too, so list it in `exclude`.

The `model` keys are acted on by `obelize fix`. A value of another type is refused, not converted
(`log_prompts: 'yes'`, a number for `model`).

| Key | Type | Default | Description |
|---|---|---|---|
| `model.provider` | `none` \| `openai_compat` | `none` | Model adapter for ambiguous cases; `none` makes no network call. |
| `model.base_url` | string | unset | An OpenAI-compatible endpoint, such as a local Ollama. `http` or `https`, with no credential, query string or fragment (the key goes in `api_key_env`): the host goes into the evidence. |
| `model.allow_insecure_http` | boolean | `false` | Permit a plain `http://` `base_url` that is not `localhost`, `127.0.0.0/8` or `::1`, which sends the key and your source across the network in the clear. Unset, such a URL is refused. |
| `model.model` | string | unset | Model name sent to the endpoint. |
| `model.api_key_env` | string | `OBELIZE_MODEL_API_KEY` | Environment variable holding the key; the key never reaches configuration, logs or evidence. |
| `model.log_prompts` | boolean | `false` | Keep raw prompts, which contain source, in the run folder. |

The `agent` keys are acted on by `obelize upgrade --apply --branch`; `network` by `pack synth`,
`outdated` and `upgrade`.

| Key | Type | Default | Description |
|---|---|---|---|
| `network.index` | string | `https://pypi.org` | The package index `pack synth` asks, as a Simple API address (`/simple` is added if it is missing). `OBELIZE_INDEX_URL` replaces it for one run; `OBELIZE_INDEX_AUTHORIZATION` is the value of an `Authorization` header, sent to this host and to none other. |
| `network.offline` | boolean | `false` | Read releases only from the cache, as `--offline` does; `OBELIZE_OFFLINE` set to anything does too. |
| `agent.backend` | `none` \| `claude_code` | `none` | The coding agent `upgrade --apply --branch` puts flagged places to, as `--agent` does. `none` asks no one. |
| `agent.model` | string | unset | Passed to the program as its own model name or alias. |

An allowlist entry matches a command that splits into the same arguments. An
unreadable or invalid file is an error, never an empty allowlist.
`approved.json` only caches your answers: if it is missing or unreadable you
are asked again.
