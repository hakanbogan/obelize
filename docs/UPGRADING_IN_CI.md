# Upgrading in CI

`obelize upgrade --apply --yes --branch` tries a move in a copy of your repository, runs your tests
before and after, and commits the move to a new branch only if no test that passed now fails
([Upgrading a dependency](UPGRADING.md)). The GitHub Action does that in a job with `mode: upgrade`,
and leaves the branch as a git bundle, a patch and a report in an artifact. A second job, which may
write to the repository, checks the bundle and opens the pull request. A job that passes may have
made no branch, since a move that was not proven leaves the job green unless `fail-on-unproven` is
set, so read `changed` and `exit-code`. How often a trial proves a move is not measured: only the
dry run is, and over 80 public repositories it wrote no file for a library with no pack ([how far it
gets](UPGRADING.md#how-far-it-gets-without-a-pack)). The two jobs are separate because the first
runs your tests, and a job that runs your tests must not hold a credential that writes.

## The workflow

```yaml
# Try to upgrade a dependency every week, and open a pull request for a move your tests allowed, in
# two jobs. The first runs your tests and can only read; the second holds a token that writes and
# runs none of your code (docs/UPGRADING_IN_CI.md).
# Replace <commit> with the commit of the obelize release you pin, in both places that name it, and
# X.Y.Z with that release.
name: upgrade

on:
  schedule:
    - cron: "17 5 * * 1"
  workflow_dispatch:

permissions: {}

env:
  # The dependencies to upgrade, separated by spaces. Both jobs read this one list: the second takes
  # only these folders from the artifact, whatever the first job uploaded.
  DISTRIBUTIONS: pydantic

concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: false

jobs:
  upgrade:
    name: upgrade (runs your tests, can only read)
    runs-on: ubuntu-latest
    timeout-minutes: 60
    permissions:
      contents: read # check the repository out, and nothing else
    outputs:
      changed: ${{ steps.obelize.outputs.changed }}
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Upgrade
        id: obelize
        uses: hakanbogan/obelize@<commit> # vX.Y.Z
        with:
          version: X.Y.Z
          mode: upgrade
          distributions: ${{ env.DISTRIBUTIONS }}

  pull-request:
    name: pull request (holds a token, runs none of your code)
    needs: upgrade
    if: needs.upgrade.outputs.changed == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: write # push the branch the first job made
      pull-requests: write # open the pull request for it
    steps:
      - name: Checkout this repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          path: repo
          persist-credentials: false

      - name: Checkout the script that checks the upgrade
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          repository: hakanbogan/obelize
          ref: <commit>
          path: obelize
          persist-credentials: false

      - name: Download the upgrade
        uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with:
          name: obelize-upgrade
          path: ${{ runner.temp }}/obelize-upgrade

      - name: Let git push with the workflow's token
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh auth setup-git

      - name: Check each branch and open its pull request
        env:
          GH_TOKEN: ${{ github.token }}
          ARTIFACTS: ${{ runner.temp }}/obelize-upgrade
          BASE: ${{ github.sha }}
          BASE_BRANCH: ${{ github.ref_name }}
          NAMES: ${{ env.DISTRIBUTIONS }}
        run: >-
          python3 obelize/action/upgrade.py publish --artifacts "$ARTIFACTS" --repo repo
          --base "$BASE" --base-branch "$BASE_BRANCH" --distributions "$NAMES"
```

Replace `<commit>` with the commit of the obelize release you pin (the action and the script that
checks the upgrade must be the same commit, which is why it appears twice) and `X.Y.Z` with that
release. `DISTRIBUTIONS` is the list of dependencies to upgrade, separated by spaces, and it is set
once: the first job upgrades those, each into a branch and a folder of its own, and the second job
takes only those folders from the artifact and no more than twenty, so the artifact cannot ask for
a pull request for a dependency you did not name. The workflow needs one setting, Settings,
Actions, General, "Allow GitHub Actions to create and approve pull requests". A pull request opened
with the workflow's token does not start other workflows; to have your tests run on it, open it
with a token of a GitHub App or your own instead, knowing that token then writes on your behalf.

## Why there are two jobs

The first job installs packages, which runs their build scripts, and runs your tests, so it runs
code that obelize did not write and cannot vouch for. It has `contents: read`, so the runner still
gives it a read-only `GITHUB_TOKEN` that a step can use, and it can read what that permission
reaches; what it does not have is a credential that writes. `actions/checkout` keeps none with
`persist-credentials: false`, which the example sets, and the action stops with exit `2` if:

- the checkout kept one (an `extraheader`, an `includeIf` or a `credential` entry in the
  repository's own git configuration, found by name and never printed),
- `GH_TOKEN`, `GITHUB_TOKEN` or `ACTIONS_ID_TOKEN_REQUEST_TOKEN` is in the job's environment, or
- the event is `pull_request_target`, `workflow_run` or `issue_comment`, each of which gives a job
  that reads someone else's files a token, or runs it on their account. Never use this mode on
  them.

The runner may also set `ACTIONS_RUNTIME_TOKEN`, which the artifact and cache services are reached
with. The action does not refuse it, because the job could not upload its artifact without it; this
page claims nothing of what it can do beyond that.

The second job holds the token that writes and runs none of that code. It downloads the artifact,
which is data from the first job and is read as data from a stranger, and `action/upgrade.py
publish` pushes a branch and opens a pull request only for a folder that passes every one of these:

- The folder is for a dependency in `DISTRIBUTIONS`, and the artifact holds at most twenty folders.
- The bundle holds one branch, named as the CLI names one (`obelize/upgrade-` and the release),
  and nothing else: no second branch, no tag. Git's own check of the objects it unpacks, which
  refuses a tree entry called `.git` among other things, runs on the fetch (observed on git 2.54 in
  a checkout that lacks the objects; untested on older versions, which is why the path rule below
  does not rely on it).
- The branch is one commit whose parent is the commit the workflow ran on. Only its tree is used.
  The commit that is pushed is made by the second job on that parent, by `obelize
  <obelize@users.noreply.github.com>`, with a message made from the values below, so the bundle
  commit's message, headers and dates are never published.
- The trial says `pass`, and every value of it that the pull request shows has the shape of a name,
  a release or a count.
- Every path the commit changes is an edit of a regular file that the base commit has, which an
  upgrade does (it edits files in place; an added file, a deletion, a rename, a link, a submodule
  and a change of mode are refused, and an executable keeps its mode), and is a Python source or a
  manifest obelize reads. A path with a `.git` or `.obelize` component in any case, a control or
  format character, a line or paragraph separator, a colon, a backslash, a backtick, a name that
  NFKC changes, a byte that is not UTF-8 or a short name such as `GITHUB~1` is refused. The trial
  must name each path, which is a consistency check and not a control: the trial is as forged as
  the rest.
- No file is bigger than 8 MiB, the commit changes at most 2,000 files, and the bundle is under
  256 MiB.

The pull request's text and the commit's message are made by the script from those checked values:
nothing the artifact wrote in prose reaches either, and both say that the test counts are the first
job's claim. A folder that fails, or crashes, is named in the log without what it holds and pushes
nothing, and the others go on. The text is written before the branch is pushed. A branch of that
name that is on the remote already is left as it is. The script never pushes with force and never
runs a hook.

## What this does not protect against

- A hostile dependency or test can write code of its own into an existing Python source or
  manifest, and the checks cannot tell whether an edit is the one the tests judged. Some of those
  files run later: an edit to a `setup.py`, a `conftest.py` or a script is accepted, because a rule
  may legitimately edit one. Read the diff, and read those files with particular care; nothing
  merges the pull request but you.
- The trial, its counts and the evidence the pull request quotes are the first job's claim, and
  forged ones look the same as real ones.
- The tests ran once, in the first job, on a copy of the repository and its environments, and
  nothing runs them again before the pull request exists.

## Inputs and outputs

| Input | Description |
|---|---|
| `version` | Required. The obelize release to run. |
| `mode` | `upgrade`. The default, `scan`, is [the check](CLI.md#in-github-actions). |
| `distributions` | The dependencies to upgrade, separated by spaces. Each is upgraded on its own. |
| `from` | With one dependency: the release the code is written for, where no manifest declares it or every declaration admits it. |
| `fail-on-unproven` | `true` fails the job when the tests did not prove the move. Default `false`. |
| `artifact-name` | The artifact the folders go to. Default `obelize-upgrade`. |
| `working-directory` | The repository root. Default `.`. |

| Output | Description |
|---|---|
| `exit-code` | The code of the first dependency that failed outright, else of the first that was not proven, else `0`. |
| `changed` | `true` if at least one dependency was upgraded to a branch. |
| `bundle-file`, `report-file` | The bundle and the report of each branch made, separated by spaces. |

`obelize upgrade` exits `0` when the move was proven and a branch was made, and `0` with a line
saying so and no branch when the dependency is already on its newest release; `3` when tests that
passed before broke; and `6` when the tests could not judge the move (no tests, no file that can be
written, environments that could not be made) or the index could not be reached
([exit codes](CLI.md#exit-codes)). `fix` has a `4` too, which an upgrade that ends on a branch
never gives. With `fail-on-unproven: false` a `3` or a `6` passes the job and `changed` says
whether any branch was made; with `true` it fails the job. Any other code is a mistake or a crash,
such as a dependency the manifests do not name, and fails the job. `exit-code` is the first
dependency's code that failed outright, so a crash in a later dependency is not hidden behind an
earlier `3`; if there is none, the first that was not proven.

A move can be a part of one: where a library keeps its import name, a file that holds a place the
pack can only flag is left as it was and the others are written. With `--branch`, as the action runs
it, the exit code is `0` for it, as for a whole move, so it does not tell them apart (without
`--branch`, `upgrade` ends `4` for it). The files left are in `trial.json` (`held`), in `REPORT.md`
and in the text of the commit and the pull request, which say that the tests that passed before still
pass and that this does not show the rest has moved.

Each dependency that made a branch has a folder in the artifact: `upgrade.bundle`,
`upgrade.patch`, `trial.json`, `old.txt` and `new.txt` (what each environment held) and
`REPORT.md`. The bundle and the patch are your code with the move in it, kept for seven days in the
repository's Actions storage; nothing else leaves the runner except what `upgrade` always reads,
the package index it names before it contacts it
([what it sees](PRIVACY.md#what-the-package-index-sees)).
