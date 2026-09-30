## What this changes

<!-- One or two sentences: what is true after this PR that was not before? -->

## Testing

<!-- What you ran or added to check this: `uv run pytest`, a targeted test, manual steps. -->

## Fixes #

<!-- The issue this closes, e.g. "Fixes #123". No issue? Say why not. -->

## Checklist

- [ ] Tests added or updated, and `uv run pytest` passes locally.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
      `uv run mypy --platform win32` pass.
- [ ] Every claim about what `obelize` does is backed by a test, and no doc describes
      unimplemented behaviour as if it worked.
- [ ] If a transform rule changed: golden fixtures updated, with at least one positive and one
      negative fixture per rule change.
- [ ] If a migration pack changed: the pack PR review checklist in
      [CONTRIBUTING.md](https://github.com/hakanbogan/obelize/blob/main/CONTRIBUTING.md#pack-pr-review-checklist) is satisfied.
- [ ] Docs updated where they make claims: the commands table in `README.md` and a
      `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] No new runtime dependency, or the ADR that justifies it: <!-- docs/adr/ADR-0NN-....md -->
- [ ] A changed contract (subcommand/flag names, defaults, exit codes, `run.json` fields,
      `.obelize.yml` keys, run folder layout) changes its document, model and schema in the
      same pull request, and the description says what changed.
- [ ] Commits are signed off (`git commit -s`, DCO).

## Notes for the reviewer

<!-- Trade-offs, things you are unsure about, what you deliberately left out. -->
