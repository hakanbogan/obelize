# ADR-004: Repo visibility and CI

## Status

Accepted.

## Decision

The repository `hakanbogan/obelize` is **private now and goes public in Phase 5**
(task T32); an earlier flip, after the Phase 2 gate, is my call. CI and the full,
unsquashed git history exist from the first commit, and the repository becomes
visible when there is something to look at. Trusted Publishing on PyPI is a
**pending** publisher against `hakanbogan/obelize` and `release.yml` with
environment `pypi`, so the first release works whatever the visibility.

While it is private:

- The pull-request test matrix is **ubuntu-only**, kept at the full Python range
  (3.12-3.14).
- macOS and Windows jobs run only on `workflow_dispatch` and on tags, because
  private Actions minutes are a 2,000 minute monthly quota, macOS bills at 10x and
  Windows at 2x. `test-macos` and `test-windows` carry the same `if:` guard, which
  `tests/unit/test_workflows.py` evaluates for every event a workflow starts on.
- `ci.yml` (lint, lock, test, schema-drift), `e2e.yml`, `bench-smoke.yml`,
  `dependency-review.yml`, `release.yml` and `stale.yml` all run from the first
  commit. `e2e.yml`'s weekly run waits: its job's `if:` passes a schedule only on
  a public repository.

When it goes public, in the same phase:

- CodeQL's default setup for Python is enabled.
- Private vulnerability reporting is enabled, which `SECURITY.md` already
  points at.
- macOS and Windows join every push and pull request (the two ends of the
  supported range: 3.12 and 3.14); their guard passes any event on a public
  repository, so `ci.yml` needs no edit.
- `e2e.yml` runs weekly, installing the built wheel with the newest releases
  its dependency ranges allow, so a pydantic, libcst or typer release that breaks a
  fresh install shows within a week.
- The `main` ruleset is created (block deletion and non-fast-forward, require
  `lint`, `lock`, `test (ubuntu, py3.12)`, `test (ubuntu, py3.14)`,
  `test (windows, py3.12)`, `test (windows, py3.14)` and `smoke`, admin bypass
  allowed), with a tag ruleset restricting `v*` to me.

## Consequences

- macOS breakage can go unseen between tag runs; I develop on macOS arm64 daily.
  Windows breakage can too: `mypy --platform win32` checks every push, but the
  real Windows test suite only runs on a manual dispatch or a tag while the
  repository stays private.
- Until public, security review is manual plus Dependabot and `pip-licenses`, as CodeQL
  and `dependency-review.yml` do real work only on a public repository.
- Without GitHub Pro a private `main` has no branch protection, so only I
  push, and never over a red `ci`.
