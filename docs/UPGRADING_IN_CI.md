# Upgrading in CI

`obelize upgrade --apply --yes --branch` tries a move in a copy of your repository, runs your tests
before and after, and commits the move to a new branch only if no test that passed now fails
([Upgrading a dependency](UPGRADING.md)). The GitHub Action does that in a job with `mode: upgrade`,
and leaves the branch as a git bundle, a patch and a report in an artifact. A second job, which may
write to the repository, checks the bundle and opens the pull request. The two are separate because
the first runs your tests, and a job that runs your tests must not hold a token that writes.

## The workflow

```yaml
# Upgrade a dependency every week and open a pull request for it, in two jobs. The first runs your
# tests and holds no token; the second holds one and runs none of your code (docs/UPGRADING_IN_CI.md).
# Replace <commit> with the commit of the obelize release you pin, in both places that name it, and
# X.Y.Z with that release.
name: upgrade

on:
  schedule:
    - cron: "17 5 * * 1"
  workflow_dispatch:

permissions: {}

concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: false

jobs:
  upgrade:
    name: upgrade (runs your tests, holds no token)
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
          distributions: pydantic

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
        run: >-
          python3 obelize/action/upgrade.py publish --artifacts "$ARTIFACTS" --repo repo
          --base "$BASE" --base-branch "$BASE_BRANCH"
```

Replace `<commit>` with the commit of the obelize release you pin (the action and the script that
checks the upgrade must be the same commit, which is why it appears twice) and `X.Y.Z` with that
release. `distributions` takes the dependencies to upgrade, separated by spaces, and each gets a
branch and a pull request of its own. The workflow needs one setting, Settings, Actions, General,
"Allow GitHub Actions to create and approve pull requests". A pull request opened with the
workflow's token does not start other workflows; to have your tests run on it, open it with a
token of a GitHub App or your own instead, knowing that token then writes on your behalf.

## Why there are two jobs

The first job installs packages, which runs their build scripts, and runs your tests, so it runs
code that obelize did not write and cannot vouch for. It holds `contents: read` and nothing else.
`actions/checkout` keeps no credential, and the action stops with exit `2` if `GH_TOKEN` or
`GITHUB_TOKEN` is in the job's environment or the event is `pull_request_target`, which hands a
write token to a job that reads a pull request's files. Never use this mode on that event.

The second job holds the token and runs none of that code. It downloads the artifact, which is data
from the first job and is read as data from a stranger, and `action/upgrade.py publish` pushes a
branch and opens a pull request only for a folder that passes every one of these:

- The bundle holds one branch, named as the CLI names one (`obelize/upgrade-` and the release),
  and nothing else: no second branch, no tag.
- The branch is one commit on the commit the workflow ran on, by the identity the action gives it
  (`obelize`, `obelize@users.noreply.github.com`), and its subject names the upgrade the trial
  reports.
- The trial says `pass`, and every value of it the pull request shows has the shape of a name, a
  release or a count.
- Every path the commit changes is one the trial names, an added or edited regular file that is not
  a link, a submodule or an executable (an executable the move edits keeps its mode), and a Python
  source or a manifest obelize reads. A path inside `.github`, any `.git*` name, `.obelize` or a
  `..` is refused, whatever case it is in, and so is a deletion or a rename.
- No file is bigger than 8 MiB, the commit changes at most 2,000 files, and the bundle is under
  256 MiB.

The pull request's text is made by the script from those checked values: nothing the artifact wrote
in prose reaches it. A folder that fails is named in the log and pushes nothing, and the others go
on. A branch of that name that is on the remote already is left as it is. The script never pushes
with force and never runs a hook.

## What this does not protect against

The checks keep the push to the files an upgrade may change; they cannot tell whether a change to
one of those files is the one the tests judged. A dependency or a test that is hostile could write
code of its own into a Python file the trial names, so the pull request is a proposal for a person
to read, and nothing merges it. The tests ran once, in the first job, on a copy of the repository
and its environments, and nothing runs them again before the pull request exists.

## Inputs and outputs

| Input | Description |
|---|---|
| `version` | Required. The obelize release to run. |
| `mode` | `upgrade`. The default, `scan`, is [the check](CLI.md#in-github-actions). |
| `distributions` | The dependencies to upgrade, separated by spaces. Each is upgraded on its own. |
| `from` | With one dependency: the release the code is written for, where no manifest declares it. |
| `fail-on-unproven` | `true` fails the job when the tests did not prove the move. Default `false`. |
| `artifact-name` | The artifact the folders go to. Default `obelize-upgrade`. |
| `working-directory` | The repository root. Default `.`. |

| Output | Description |
|---|---|
| `exit-code` | `0`, or the exit code of the first upgrade that was not proven. |
| `changed` | `true` if at least one dependency was upgraded to a branch. |
| `bundle-file`, `report-file` | The bundle and the report of each branch made, separated by spaces. |

`obelize upgrade` exits `0` when the move was proven and a branch was made, `3` when tests that
passed before broke, and `6` when the tests could not judge the move (no tests, a place left for a
person, environments that could not be made) or the index could not be reached; `4` is as for `fix`
([exit codes](CLI.md#exit-codes)). With `fail-on-unproven: false` those pass the job and `changed`
stays `false`; with `true` they fail it. Any other code is a mistake, such as a dependency the
manifests do not name, and fails the job. A dependency that is already on the newest release is one
of those, exit `2`: there is nothing to move.

Each dependency has a folder in the artifact: `upgrade.bundle`, `upgrade.patch`, `trial.json`,
`old.txt` and `new.txt` (what each environment held) and `REPORT.md`. The bundle and the patch are
your code with the move in it, kept for seven days in the repository's Actions storage; nothing else
leaves the runner except what `upgrade` always reads, the package index it names before it contacts
it ([what it sees](PRIVACY.md#what-the-package-index-sees)).
