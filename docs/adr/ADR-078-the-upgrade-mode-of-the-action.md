# ADR-078: The upgrade mode of the action

## Status

Accepted.

## Decision

The action upgrades a dependency in CI (`mode: upgrade`), and the pull request for it is opened by a
second job. The first job runs the repository's tests and the build scripts of what it installs, so
it must not hold a credential that writes; the second holds the token that writes and must not run
that code. A composite action cannot define two jobs, so the action ships the first and the
repository ships the second as a documented workflow and a script (`action/upgrade.py publish`).
Nothing in obelize pushes: ADR-059's rule that only a pipeline the user configures may open a pull
request holds.

### D1. `mode: scan` is what it was, and `mode: upgrade` is the job that runs the tests

`mode` is `scan` (the default) or `upgrade`, and any other value stops the action with exit `2`. Every
step of the scan keeps its command and its environment and gains the condition `inputs.mode == 'scan'`,
so a scan runs the same script (`action/scan.sh`) as before. In `upgrade` mode the action runs
`action/upgrade.py run`, uploads an artifact with `actions/upload-artifact` (held to a commit, like
the other two actions), and then `action/upgrade.py gate` gives the job its verdict.

`run` upgrades each dependency in `distributions` (space separated, up to twenty, each checked
against the shape of a distribution name and none named twice under PEP 503 folding) by
`uvx obelize==<version> upgrade <name> --apply --yes --branch`, with `--from` where the one
dependency is given a release (`from`, refused with several). It never passes `--agent`: the agent
is the person's own program, which a runner does not have. The commit is given an identity by
environment (`obelize`, `obelize@users.noreply.github.com`), because a runner has none and
`commit-tree` needs one.

The job holds no credential that writes, which is a narrower claim than holding no token: with
`contents: read` the runner still gives it a read-only `GITHUB_TOKEN`, and it sets
`ACTIONS_RUNTIME_TOKEN` for the artifact service, which `run` does not refuse, since the job could
not upload without it; GitHub documents it only as that, and nothing here claims more. `run`
refuses to start (exit `2`, before anything is installed or run) in these cases:

- The event is `pull_request_target`, `workflow_run` or `issue_comment`, each of which gives a job
  that reads someone else's files a token, or runs it on their account.
- `GH_TOKEN`, `GITHUB_TOKEN` or `ACTIONS_ID_TOKEN_REQUEST_TOKEN` is in the environment.
- The checkout kept a credential: `git config --local --get-regexp` shows an `extraheader`, an
  `includeIf` or a `credential` key. `actions/checkout` leaves one at its default of
  `persist-credentials: true`, and a repository's tests could read it. Only the key names are read
  and printed, never a value. The example sets `persist-credentials: false`.

### D2. What it leaves, and the verdict

For a dependency whose upgrade exited `0` and made exactly one new branch under `obelize/`
(the CLI's default name, which holds the install spec, so a newer release gets a branch of its own),
`run` writes a folder named for the dependency, folded (`pydantic`, `django-rest`): `upgrade.bundle`
(the branch, with the base commit as its prerequisite), `upgrade.patch`, `trial.json`, `old.txt` and
`new.txt` from the trial's evidence, and a `REPORT.md` for a person. A trial writes no `REPORT.md` of
its own, and its run folder is the copy's, so the report is made from `trial.json` and the commit
message. An upgrade that exits `0` and makes no branch had nothing to move: `obelize upgrade` says
so and exits `0` for a dependency already on its newest release, and the action records `0` and no
folder for it. One that makes two branches, or one the script cannot publish, is exit `1`.

The step exits `0` whatever happened, with the outputs `exit-code`, `changed`, `bundle-file`,
`report-file` (one path for each branch made, separated by spaces) and `out-dir`, so the artifact is
uploaded before the job fails. `exit-code` is the code of the first dependency whose upgrade failed
outright (a code that is neither `0`, `3` nor `6`), else of the first that was not proven, else `0`,
so a crash in a later dependency is never hidden behind an earlier `3`. `gate` passes `0`, and
passes `3` (tests that passed before broke) and `6` (no verdict: no tests, a place left for a
person, environments that could not be made, an index that could not be reached) unless
`fail-on-unproven` is `true`. Any other code is a mistake or a crash and fails the job. The set is
`{3, 6}` and not `{3, 4, 6}` because `upgrade --apply --branch` ends in `_trial` and `_commit_branch`,
whose exits are `2`, `3`, `5` and `6` (a pass returns, and the command then exits `0`); the `4` of
`fix` (nothing applied, a place to review) is reached only without a branch. A test reads the exit
codes from the CLI's source. The default of
`fail-on-unproven` is `false`: a weekly job that finds a move its tests do not prove is information,
not an alarm.

### D3. The second job reads the first's artifact as a stranger's

`publish` takes the dependencies the workflow asked for (`--distributions`, fed from the same
workflow-level `DISTRIBUTIONS` the first job's `distributions` reads, never from the artifact) and
goes through the folders of the downloaded artifact. A folder for another dependency is refused,
and an artifact with more than twenty folders is refused whole, so a forged artifact cannot make it
push more branches than were asked for. For each folder `verified` must hold before anything is
pushed. The first job ran the repository's code and its dependencies' build scripts, so every byte
of the artifact is taken to be forged.

- The folder's name is a folded distribution name, and `trial.json` is a small JSON object that
  says `pass`, names that distribution, and whose release, install spec, counts and paths have the
  shape of a name, a release, a count and a list of strings.
- The bundle is a file, not a link, of at most 256 MiB, that holds one `refs/heads/obelize/upgrade-...`
  and nothing else (no second branch, no tag), and `git bundle verify` finds the commit it needs.
  It is fetched into a private ref (`refs/obelize-verify/<folder>`, removed afterwards) with
  `transfer.fsckObjects` and `fetch.fsckObjects` set. In a checkout that lacks the objects, git
  2.54 (Apple Git-157) refuses a tree entry called `.git` there (`hasDotgit`), and on the same
  version the reviewer's cases for `.GIT`, `.git `, `.git.`, `git~1`, a zero-width character in the
  name, `sub/.git/x.py`, duplicate or unsorted entries, a `/` in a name and `.` or `..` were
  refused too. Where the objects already exist, as in the repository that made them, the fetch does
  nothing and checks nothing, which is how a test that forges and checks in one repository hides
  this: the tests check in a depth-1 clone. Older git versions, and what they accept, were not
  tested, and the path rule below does not rely on this check.
- The branch is one commit whose only parent is the commit the workflow ran on. Only its tree is
  used.
- Every path the tree changes comes from `git diff-tree` on the two trees without rename detection
  and is an edit (`M`) of a regular file that the base tree has, with the mode it had and not a
  link, a submodule or a changed mode. Everything else is refused: an added file, a deletion, a
  rename, a type change. An upgrade edits files in place (every change it writes carries the bytes
  the file had when it was scanned, and no rule, the agent's proposals and the external fixers
  included, creates a file), so a file that is new is a forgery or a bug, and this refusal is what
  keeps `conftest.py`, `sitecustomize.py`, `noxfile.py` and `requirements/evil.txt` out when they
  are new.
- The path is a Python source (`.py`, `.pyi`) or a manifest obelize reads (`Pipfile`,
  `pyproject.toml`, `setup.cfg`, `setup.py`, a `*requirement*.txt`, a `.txt` under `requirements/`),
  the set `scan/manifests.py` reads, which a test holds the script to; has no empty, `.` or `..`
  component and no component that begins `.git` or `.obelize` in any case; and holds only UTF-8
  and none of a backslash, a backtick, a colon (an NTFS stream), a character of the Unicode
  categories Cc, Cf, Zl or Zp, a character NFKC changes (`.git` written with a fullwidth full stop)
  or a short name such as `GITHUB~1`. At most 2,000 files, none over 8 MiB.
- The trial must name each path. That is a consistency check between two things the same job wrote,
  not a control: `trial.json` is as forged as the bundle.
- The files the trial lists as left as they were (`held`) are named in the text of the commit and the
  pull request and written nowhere, so they are judged as text and not as paths: UTF-8 of at most
  512 characters, with no backslash, no backtick (which would end the code span they are shown in)
  and no character of the categories Cc, Cf, Zl or Zp. A name the path rule above refuses (a colon,
  a short name, a name NFKC changes, a `..`, a file of no kind obelize writes) does not stop the pull
  request, since nothing is written to it.

The second job makes the commit it pushes: `git commit-tree` of the bundle's tree on the base
commit, by the action's identity, with a message made from the checked values. The forged commit's
message, headers (`gpgsig`, `encoding`, extra authors) and dates are never published, and it can
not carry another person's `Co-authored-by` line or an `@mention`. This reverses an earlier
decision to push the bundle's commit as it was and to check its identity and subject, which proved
nothing about its message. The title and the body are made by the script from the same values: the
body says what the trial counted and that the counts are that job's claim, lists the files (at most
fifty), repeats the commit's "Not written, for you to change" line only if every place in it is a
`path:line`, and says what was checked. The body is written before anything is pushed. The branch
is pushed with `--no-verify` and never with force; a branch of that name already on the remote is
left as it is, and a failed `gh pr create` leaves the branch pushed and says so. A folder that
fails, for any reason including one nobody foresaw, is named in the log by its folder and the kind
of failure and does not stop the next. Everything that came from the artifact or from git about it
is escaped before it reaches the log, so it cannot start a workflow command.

### D4. What it does not do

It does not stop a hostile dependency or test from writing code of its own into an existing Python
source or manifest, including one that runs later (`setup.py`, `conftest.py`, a script), which a
rule may legitimately edit and so cannot be refused; the pull request is a proposal for a person to
read, and the tests ran once, in the first job, on a copy. The test counts and the evidence the pull
request quotes are that job's claim, and forged ones look like real ones. A pull request opened
with the workflow's token starts no other workflow. The action does not run in `scan` and `upgrade`
at once, and the inputs of the other mode are ignored. The workflow is an example under
`examples/ci/` and a page, [Upgrading in CI](../UPGRADING_IN_CI.md), not a workflow of this
repository, which has no use for it; Dependabot does not cover `examples/`, so a test holds the
example's pins to the commits the repository's own workflows pin (the download action is pinned by
hand), and another runs zizmor on it where it is installed. There is no smoke test of the action
in `e2e.yml`, because the action installs a published release and cannot run the tree; the release
checklist runs the example by hand. A pack whose `to.version` has a space in it (`>=2, <3`) gives
an install spec the second job refuses; it fails closed, and is in KNOWN_ISSUES.

## Consequences

`action.yml` gains `mode`, `distributions`, `from`, `fail-on-unproven` and `artifact-name`, the
outputs `bundle-file`, `report-file` and `changed`, and four steps; `docs/CLI.md`,
`docs/UPGRADING.md`, `docs/SAFETY.md`, `docs/PRIVACY.md`, `docs/THREAT_MODEL.md` (TM-17),
`docs/KNOWN_ISSUES.md` and `docs/RELEASING.md` say what it is, and `tests/unit/test_action.py` and
`tests/unit/test_action_upgrade.py` hold it, with a real trial's branch passed through `run` and
`publish` from a depth-1 checkout in `tests/unit/test_upgrade.py`. `obelize upgrade` for a
dependency already on its newest release exits `0` and says so instead of `2`
([CLI](../CLI.md#obelize-upgrade)). Opening a pull request from the CLI itself, or a privileged half
inside the action, are decisions of their own.
