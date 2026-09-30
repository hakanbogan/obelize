# ADR-004: Repo visibility and CI

## Status

Accepted.

## Decision

The repository `hakanbogan/obelize` is public, and its history starts with the 0.1.0 release. CI
runs from the first commit, and Trusted Publishing on PyPI is a pending publisher against
`hakanbogan/obelize` and `release.yml` with environment `pypi`.

Every push and pull request runs `ci.yml`: lint, lock, the test suite on Ubuntu with Python
3.12, 3.13 and 3.14, the suite on macOS and on Windows with 3.12 and 3.14, a smoke test of the
built wheel, and a check that the JSON Schemas match the models. `test-macos` and `test-windows`
carry the same `if:` guard. On a public repository it passes every event, and on a private one it
admits only a manual run and a tag, because private Actions minutes are a 2,000 minute monthly
quota that macOS bills at 10x and Windows at 2x. `tests/unit/test_workflows.py` evaluates the
guard for every event a workflow starts on. `e2e.yml` runs weekly and installs the built wheel
with the newest releases its dependency ranges allow, so a pydantic, libcst or typer release that
breaks a fresh install shows within a week. `bench-smoke.yml`, `dependency-review.yml`,
`release.yml` and `stale.yml` run from the first commit.

The `main` ruleset blocks deletion and non-fast-forward pushes, allows admin bypass and requires
these eleven checks, written as GitHub shows them:

- `lint (ruff + mypy)`
- `lock (uv.lock is in sync)`
- `test (ubuntu, py3.12)`, `test (ubuntu, py3.13)` and `test (ubuntu, py3.14)`
- `test (macos, py3.12)` and `test (macos, py3.14)`
- `test (windows, py3.12)` and `test (windows, py3.14)`
- `smoke (built wheel, clean venv)`
- `schema-drift (JSON Schemas match the models)`

A tag ruleset restricts `v*` to me. CodeQL's default setup for Python and private vulnerability
reporting, which `SECURITY.md` points at, are on.

## Consequences

- A required check is matched by its exact name. A matrix job that its `if:` skips reports the
  unexpanded template, so the macOS and Windows checks can be required only while the repository
  stays public.
- The release workflow accepts only a successful `ci.yml` run on the commit it publishes, so a red
  leg on any of the eleven checks holds a release.
- GitHub turns scheduled workflows off after 60 days without activity in the repository. They
  start again from the Actions tab.
