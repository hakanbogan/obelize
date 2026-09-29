# Security Policy

## Supported versions

During `0.x`, only the latest release is supported: a fix ships in the next release, with no
backports. Before the first release, reports apply to `main`.

| Version | Supported |
|---|---|
| Latest `0.x` release | Yes |
| Any earlier `0.x` release | No, upgrade to the latest |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

- Email <hbogan93@gmail.com> with `Obelize security` in the subject line.
- Once the repository is public, GitHub private vulnerability reporting is the
  preferred channel, at `https://github.com/hakanbogan/obelize/security/advisories/new`.

What to expect:

- Acknowledgement within 72 hours. If you haven't heard from me by then, please send a
  reminder; the message may just have gone missing.
- Then a plain assessment of whether it is in scope, a fix or a reasoned "won't fix", and
  credit in the advisory and changelog if you want it.
- There's no bug bounty, and I don't pay for automated scanner output.

Include the obelize version or commit, Python version and OS, a minimal reproduction, and what
an attacker gains.

## Scope

`scan`, `fix`, `verify`, `undo` and `pack validate` read a repository, write files, spawn
process groups and, with a model configured, open a socket. The trust boundaries (B1-B6), and
each threat with its mitigation and test, are in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md#trust-boundaries).

### In scope: report these privately

- Writing outside the repository root (B5): a path traversal, symlink, submodule or
  absolute path that lands a write anywhere but a regular file inside the root that is on the
  impact plan.
- Running a command from a pack or another remote source (B1, B4): a pack's
  `verification.suggestions` running, or a repository's `.obelize.yml` command running in CI or
  non-interactively without `--trust-repo-config`.
- Leaking a secret into evidence or a model payload (B2, B6): a secret from the environment,
  a `.env`-style file or an excluded path reaching a run folder, a log or a request body.
- Applying an unvalidated model proposal (B3): a model response reaching the working tree
  without passing the [guard](docs/THREAT_MODEL.md#tm-4-in-detail), or without
  `--apply --accept-model`.
- Anything else that makes Obelize run code, reach the network, or modify git state (commit,
  branch, push, merge) when it was not asked to.

### Not in scope: open a normal bug instead

- A wrong but contained codemod result: a wrong rewrite, a miss, a false positive or an
  unneeded `needs_review`. It stays in your repository, shows in the diff, and `obelize undo`
  reverts it. Use the [bug report form](https://github.com/hakanbogan/obelize/issues/new/choose).
- Crashes and unhandled exceptions with no security consequence.
- The documented limitations: verification commands you configured run with your environment
  and are not sandboxed; local execution is not isolated; redaction is best-effort.
- Vulnerabilities in a third-party dependency: report it upstream first, and let me know so I
  can raise the minimum version here.

## Please don't send me secrets

A run folder under `.obelize/runs/<id>/` holds diffs, whole-file snapshots and the output of your
verification commands, any of which can contain secrets. Redaction is best-effort and misses
unknown formats ([docs/PRIVACY.md](docs/PRIVACY.md)). Read a `run.json`, `REPORT.md`, diff or log
before attaching it, and remove anything private. An excerpt is fine, and "I cannot share this
file" is an acceptable answer: describe the shape of the problem instead.
