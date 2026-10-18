# ADR-059: Verified dependency upgrades

## Status

Accepted.

## Decision

obelize is a tool for verified dependency upgrades. When a Python library makes a breaking change,
it rewrites the code it can prove safe, refuses the rest with a reason, and checks the result
against the user's own tests. The three bundled migrations are examples of that, not its scope.

I decided this on 2026-10-18, after the first release had measured two things: a migration pack for
each library is the whole cost of reaching a new user, and 0 of 20 public repositories could check a
migration with their own tests. A tool that needs a hand-written pack per library, and cannot run
the check in one command, stays a tool for three libraries.

### D1. What does not change

- The tool is local-first. Nothing is written without `--apply`, and `undo` puts the files back.
- A pack is reviewed data and carries no code (ADR-006). A rewrite that cannot be proven is
  `needs_review` or `unsupported`, never a guess.
- Evidence over confidence: every place carries a reason from a closed vocabulary, and every run
  writes a run folder.
- obelize never pushes. Only a pipeline the user configures may open a pull request.

### D2. What the boundary now allows

The earlier boundary listed these as things obelize would not do. Each is now a direction, built in
its own release, described as planned until it ships, and written up in its own ADR when it does:

- Finding the places a library's upgrade breaks without a bundled pack, from the two releases' API.
- Reading a package index and a migration guide, only when the user allows it, with every host
  named before the request and `--offline` always available.
- More than one way to reach a model, including the user's own coding agent.
- A pack registry, and packs the tool drafts, each marked with where it came from.
- Commits on a branch the user asks for, and a pipeline that opens the pull request.
- Isolated environments for the old and the new release, so the tests run on both in one command.

### D3. What stays out

A hosted service, a dashboard, a GitHub App, telemetry, an editor extension, and a command that
pushes. Pack signing waits until after 1.0.

### D4. Consent comes from the user

Anything beyond reading the repository (the network, a model, installing an environment, running a
plugin, writing a branch) is allowed by a flag or by the user's own `~/.config/obelize/config.yml`.
A repository's `.obelize.yml` cannot grant it, as it cannot name a model or a pack directory today.

### D5. The date of the first public count

The count of installs, issues and stars set for 2026-11-03 stays a measurement. It no longer decides
whether feature work stops, because the work above is what gives an outside reader a reason to
open an issue.

## Consequences

`docs/PRODUCT.md` and `docs/ROADMAP.md` are rewritten to say this. The README, the PyPI description
and the command help describe what ships, and the roadmap describes the rest as planned.
