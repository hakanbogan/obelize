# ADR-078: The upgrade mode of the action

## Status

Accepted.

## Decision

The action upgrades a dependency in CI (`mode: upgrade`), and the pull request for it is opened by a
second job. The first job runs the repository's tests and the build scripts of what it installs, so
it must not hold a token that writes; the second holds the token and must not run that code. A
composite action cannot define two jobs, so the action ships the first and the repository ships the
second as a documented workflow and a script (`action/upgrade.py publish`). Nothing in obelize
pushes: ADR-059's rule that only a pipeline the user configures may open a pull request holds.

### D1. `mode: scan` is what it was, and `mode: upgrade` is the unprivileged half

`mode` is `scan` (the default) or `upgrade`, and any other value stops the action with exit `2`. Every
step of the scan keeps its command and its environment and gains the condition `inputs.mode == 'scan'`,
so a scan runs the same script (`action/scan.sh`) as before. In `upgrade` mode the action runs
`action/upgrade.py run`, uploads an artifact with `actions/upload-artifact` (held to a commit, like
the other two actions), and then `action/upgrade.py gate` gives the job its verdict.

`run` upgrades each dependency in `distributions` (space separated, up to twenty, each checked
against the shape of a distribution name and none named twice under PEP 503 folding) by
`uvx obelize==<version> upgrade <name> --apply --yes --branch`, with `--from` where the one
dependency is given a release (`from`, refused with several). It never passes `--agent`: the agent
is the person's own program, which a runner does not have. It refuses to start if `GH_TOKEN` or
`GITHUB_TOKEN` is in its environment or the event is `pull_request_target`, which is the event that
hands a write token to a job that reads a pull request's files. The commit is given an identity by
environment (`obelize`, `obelize@users.noreply.github.com`), because a runner has none and
`commit-tree` needs one, and because the second job looks for it.

### D2. What it leaves, and the verdict

For a dependency whose upgrade exited `0` and made exactly one new branch under `obelize/`
(the CLI's default name, which holds the install spec, so a newer release gets a branch of its own),
`run` writes a folder named for the dependency, folded (`pydantic`, `django-rest`): `upgrade.bundle`
(the branch, with the base commit as its prerequisite), `upgrade.patch`, `trial.json`, `old.txt` and
`new.txt` from the trial's evidence, and a `REPORT.md` for a person. A trial writes no `REPORT.md` of
its own, and its run folder is the copy's, so the report is made from `trial.json` and the commit
message. An upgrade that exits `0` and leaves no branch, or two, is exit `1`.

The step exits `0` whatever happened, with the outputs `exit-code` (the first code that was not
`0`), `changed`, `bundle-file`, `report-file` (one path for each branch made, separated by spaces) and
`out-dir`, so the artifact is uploaded before the job fails. `gate` then passes `0`, and passes `3`,
`4` and `6` (tests broke, nothing applied or a place for review as for `fix`, no verdict) unless
`fail-on-unproven` is `true`. Any other code is a mistake or a crash and fails the job: `2` is also
what a dependency that is already on its newest release gives, since there is nothing to move. The
default of `fail-on-unproven` is `false`: a weekly job that finds a move its tests do not prove is
information, not an alarm.

### D3. The second job reads the first's artifact as a stranger's

`publish` goes through the folders of the downloaded artifact and, for each, `verified` must hold
before anything is pushed. The first job ran the repository's code and its dependencies' build
scripts, so every byte of the artifact is taken to be forged.

- The folder's name is a folded distribution name, and `trial.json` is a small JSON object that
  says `pass`, names that distribution, and whose release, install spec, counts and paths have the
  shape of a name, a release, a count and a list of strings.
- The bundle is a file, not a link, of at most 256 MiB, that holds one `refs/heads/obelize/upgrade-...`
  and nothing else (no second branch, no tag), and `git bundle verify` finds the commit it needs.
  It is fetched into a private ref (`refs/obelize-verify/<folder>`, removed afterwards) with
  `fetch.fsckObjects` set, which passes a tree entry called `.git` when the source is a bundle, so
  that case is the path rule's.
- The branch is one commit whose only parent is the commit the workflow ran on, by the identity
  above in both roles, with a subject `Upgrade <name> <from> to <install>` that says what the trial
  says.
- Every path the commit changes comes from `git diff-tree` on the two trees without rename
  detection and is an addition or an edit of a regular file; a link, a submodule, a deletion and a
  rename are refused, an added executable is refused, and an edited file keeps the mode it had. The
  path is one the trial names; has no empty, `.` or `..` component, backslash, backtick or control
  character; has no component that begins `.git` or `.obelize` in any case; and is a Python source
  (`.py`, `.pyi`) or a manifest obelize reads (`Pipfile`, `pyproject.toml`, `setup.cfg`, `setup.py`,
  a `*requirement*.txt`, a `.txt` under `requirements/`), the set `scan/manifests.py` reads, which a
  test holds the script to. At most 2,000 files, none over 8 MiB.

The title and the body of the pull request are made by the script from those values. The body says
what the trial counted, lists the files (at most fifty), repeats the commit's "Not written, for you
to change" line only if every place in it is a `path:line`, and says what was checked. Nothing the
artifact wrote in prose reaches it. The branch is pushed as the commit that was checked, with
`--no-verify` and never with force; a branch of that name already on the remote is left as it is,
and a failed `gh pr create` leaves the branch pushed and says so. A folder that fails does not stop
the next.

The commit is not rebuilt by the second job. Rebuilding it would be one more way to differ from what
was checked; instead its parent, identity, subject and tree are checked, and its message, which
only the CLI's format shapes, reaches the pull request through the shaped line above and nowhere
else.

### D4. What it does not do

It does not stop a hostile dependency or test from writing code of its own into a Python file the
trial names: the pull request is a proposal for a person to read, and the tests ran once, in the
first job, on a copy. A pull request opened with the workflow's token starts no other workflow. The
action does not run in `scan` and `upgrade` at once, and the inputs of the other mode are ignored.
The workflow is an example under `examples/ci/` and a page, [Upgrading in CI](../UPGRADING_IN_CI.md),
not a workflow of this repository, which has no use for it; Dependabot does not cover `examples/`,
so a test holds the example's pins to the commits the repository's own workflows pin (the download
action is pinned by hand), and another runs zizmor on it where it is installed. There is no smoke
test of the action in `e2e.yml`, because the action installs a published release and cannot run the
tree; the release checklist runs the example by hand.

## Consequences

`action.yml` gains `mode`, `distributions`, `from`, `fail-on-unproven` and `artifact-name`, the
outputs `bundle-file`, `report-file` and `changed`, and four steps; `docs/CLI.md`,
`docs/UPGRADING.md`, `docs/SAFETY.md`, `docs/PRIVACY.md`, `docs/THREAT_MODEL.md` (TM-17),
`docs/KNOWN_ISSUES.md` and `docs/RELEASING.md` say what it is, and `tests/unit/test_action.py` and
`tests/unit/test_action_upgrade.py` hold it, with a real trial's branch passed through `run` and
`publish` in `tests/unit/test_upgrade.py`. Opening a pull request from the CLI itself, or a
privileged half inside the action, are decisions of their own.
