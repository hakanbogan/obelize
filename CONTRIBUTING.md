# Contributing to Obelize

## Commands

```bash
obelize --help
obelize --version
obelize scan   [--repo .] [--pack <id|path>] [--json] [--jobs N] [--list-files]
obelize fix    [--pack <id|path>] [--repo .] [--apply] [--allow-dirty] [--verify "<cmd>"]...
obelize verify --run <id> [--repo .] [--verify "<cmd>"]...
obelize undo   --run <id> [--repo .]
obelize pack validate <id|path>
```

`tests/unit/test_status_claims.py` holds this block equal to the registered commands, and
`tests/unit/test_cli_surface.py` grades them against [docs/CLI.md](docs/CLI.md#surface).

Document only what is implemented, and mark anything planned as planned. A documentation PR
that describes unimplemented behaviour as if it shipped is treated like a code PR with a
failing test.

## Development setup

You need Python 3.12-3.14 and [uv](https://docs.astral.sh/uv/). Linux, macOS and Windows are
supported; the `bench/` scripts build POSIX virtual environments and are not run on Windows.

```bash
git clone https://github.com/hakanbogan/obelize.git
cd obelize
uv sync
uv run pre-commit install
```

Then the checks CI runs:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run mypy --platform win32
```

`uv run mypy` is strict over `src`, `tests` and `bench`, and `--platform win32` checks them as
Windows sees them. `uv sync` installs the `dev` group; `pip install -e . --group dev` (pip 25.1
or later) installs the same, but `uv.lock` is authoritative and CI checks it with `uv lock --check`.

## Project layout

Each module under `src/obelize/` owns one job. Do not spread a concern across modules, and do
not add a module without an ADR.

| Path | Owns |
|---|---|
| `__init__.py` | `__version__`, the only place the version is written |
| `cli.py` | Flags, help text and exit codes. Heavy imports stay inside command bodies so `--help` stays under 300 ms; a subprocess test checks the import graph, not the time |
| `_yaml.py` | The one YAML reader: `SafeLoader`, and a duplicate key is an error |
| `config.py` | `.obelize.yml`, its merge with the flags, and file selection |
| `models.py` | The closed vocabularies ([SCAN_VOCABULARY.md](docs/SCAN_VOCABULARY.md), [RUN_FOLDER.md](docs/RUN_FOLDER.md)) and the shared pydantic models |
| `gitutil.py` | git via subprocess: `tree` gates `--apply` and `state` records it. Staged files are uncommitted changes; untracked ones are not, since obelize writes its own run folder, unless the plan would rewrite one |
| `fsutil.py` | The path guard, the `O_NOFOLLOW` read, sha256, and `apply`, the only writer of a user's file: every path checked first, then a temporary file, `fsync`, the original mode and a rename |
| `native/` | The platform seam: `files` opens, creates, renames and deletes relative to a parent directory and never through a link, except the read by path, which guards only the last component, `processes` starts a verification command in its own session, or on Windows its own job object, reads its output against a deadline and stops everything it started, and `console` makes Windows' standard streams UTF-8. Each picks its implementation at import |
| `scan/` | Path selection, the input gates, name and binding resolution, cross-module reach, dependency manifests, the worker pool and its total order, and the declared Python floor |
| `packs/` | The pack schema, the loader, and the bundled pack |
| `impact/` | The escape rule and the bail ladder that turn a file's analysis into an `ImpactPlan` |
| `transforms/` | The `Rule` protocol, the registry (`IMPLEMENTED` says which kinds run), the import manager, one module per kind in `kinds/`, and `codemod.py`, the driver, which writes nothing |
| `providers/` | Which flagged findings a model is asked about, the guard on its answer, the one adapter (stdlib `urllib`) and the pass joining them |
| `verify/` | The command trust ladder and runner, the status-to-exit table, the one redactor, and the compile check of every changed file |
| `commands/` | What `fix`, `verify` and `undo` do; nothing here prints or exits. The model is asked only after the tree gate, so an apply the tree refused sends nothing |
| `evidence/` | The run folder and its write order, the reports (not contracts), and the diff, which obelize generates and never applies |
| `schemas/` | The generated, committed JSON Schemas; `ci / schema-drift` fails when one drifts from its model |

Tests live in `tests/unit/`, `tests/packs/`, `tests/oracle/` and `tests/e2e/`. `tests/oracle/`
grades the scan over the eight cases in `tests/fixtures/scan/`, the verification runner over
twenty-four more in `tests/fixtures/verify/` (real programs), and the transform rules over one
hundred and forty-seven more in `tests/fixtures/transforms/`: eleven for `rename_import`,
twenty-eight for `configure_to_client`, seventy-three for `generative_model_calls`,
twenty-four for `rewrite_call` and eleven for `flag_only`, beside the repository-shaped
`codemod/` and `manifest_dependency/` corpora. A rewrite-time bail stays out of
`tests/fixtures/scan/`, whose harness would read it as an answer `obelize scan` must give. A
`complete` column in `rename_import/` is about that one rule; in `configure_to_client/` and
`generative_model_calls/`, which run every implemented rule, it means `fix --apply` writes the
file.

`tests/unit/acme.py` holds the literals of an invented SDK the unit tests share, named unlike
the Gemini pack on purpose. `tests/e2e/` runs scan, plan, apply and apply again over
`examples/gemini-legacy-app/`; its `e2e` marker is a label, not a filter, so
`-m "not e2e"` skips it.

`bench/` holds the measurements; everything in it is type-checked.

| Scripts | Data | Measures |
|---|---|---|
| `crossover.py` | none | the pool sweep behind `POOL_THRESHOLD` |
| `gate1_collect.py`, `gate1_score.py` | `bench/gate1/`, `bench/results/gate1/` | scan precision and recall |
| `candidates_collect.py`, `candidates.py` | `bench/candidates.yaml`, `bench/results/candidates/`, `bench/CANDIDATES.md` | the candidate corpus |
| `cases_collect.py`, `cases.py` | `bench/cases.yaml`, `bench/cases_draws.yaml`, `bench/results/cases/`, `bench/CASES.md` | the benchmark cases and their hand-written answer keys |
| `run.py`, `summarize.py` | `bench/fixtures/`, `bench/results/round-<n>/` | a round (CI runs its offline fixtures pass), and the block `docs/BENCHMARK_RESULTS.md` publishes |
| `errors_collect.py`, `errors.py` | `bench/errors.yaml`, `bench/results/errors/` | the error analysis |
| `comparison_collect.py`, `comparison.py` | `bench/COMPARISON_PROMPT.md`, `bench/comparison.yaml`, `bench/results/comparison/` | the comparison arm |

Scripts outside the coverage gate carry their reason in `pyproject.toml`. `bench/fixtures/`,
like `tests/fixtures/`, is excluded from ruff, mypy and coverage: reformatting it would move
the lines its answer keys name. `bench/work/` is gitignored scratch for `gate1_collect.py`,
`candidates_collect.py` and `cases_collect.py`. A round checks out under the system temporary
directory: pytest, ruff, mypy, tox and setuptools search upward for configuration, and running
inside this repository would find this project's own. No committed result carries a test
suite's output or an absolute path.

`docs/adr/` holds the architecture decision records; [docs/DECISIONS.md](docs/DECISIONS.md) is
the index.

## What a good PR looks like

Keep each PR to one change and say what it does in the description. A PR that does several
unrelated things will be asked to split.

- Every behaviour change needs a test.
- A check that finds nothing today still has to prove it works: run it against a planted defect,
  not just against its own assertion turned into a tautology.
- Every transform rule needs golden fixtures: a `.before.py` input, a `.after.py` expected
  output matching byte for byte, and a negative fixture that produces zero findings.
- Output must be deterministic. Two runs over the same input produce byte-identical artefacts
  apart from `run.json`'s `timings`, the only place a wall clock appears; no set iteration
  reaches an output. `tests/oracle/test_scan_determinism.py` and
  `tests/oracle/test_scan_command_against_the_oracle.py` check it.
- No new runtime dependency without an ADR saying why the stdlib will not do; a new dev
  dependency needs a reason in the PR description.
- Update the docs that make claims. If a command's status changes, update the commands table
  in `README.md` and add a `CHANGELOG.md` entry under `[Unreleased]`.
- Do not change a contract silently. Command and flag names, defaults (dry-run stays the
  default), exit codes, `run.json` fields, `.obelize.yml` keys and the run folder layout have
  no version to bump through 0.x ([CHANGELOG.md](CHANGELOG.md#stability)); a change updates
  its document ([docs/CLI.md](docs/CLI.md), [docs/RUN_FOLDER.md](docs/RUN_FOLDER.md)), model and
  generated schema in the same commit, and the commit message says what changed.
- Comments and docstrings say what the code cannot: the reason, the invariant, the
  hazard, once, in as few lines as it takes. No history, task ids or restatement of the
  code; git and the ADRs keep those.
- Sign your commits (see DCO below) and keep the history readable.

## Contributing a migration pack

Start with [docs/PACK_SPEC.md](docs/PACK_SPEC.md). Packs carry no executable content: a pack is
declarative YAML that selects a rule `kind` implemented in Python and supplies its parameters.
A pack's `verification.suggestions` are displayed, never executed.

Every `change` needs at least one positive and one negative fixture. The whole fixture contract
is in [docs/PACK_SPEC.md](docs/PACK_SPEC.md#fixtures), and `tests/packs/test_all_packs.py`
enforces it.

### Pack PR review checklist

Self-check before asking for review:

- [ ] Every rule is sourced from an official domain (the vendor's own migration guide or
      reference), not a blog post or a model's recollection.
- [ ] `SOURCES.md` records the URL, a `retrieved_at` date, the page hash and a short quote,
      not the whole page, with one section per `changes[].id` (the pack tests check both
      directions).
- [ ] Symbols are fully qualified (`google.generativeai.GenerativeModel`, not
      `GenerativeModel`).
- [ ] Both SDK versions are installable so the claim can be checked.
- [ ] Negative fixtures cover the known traps: alias collision, the same class name in a
      different SDK (e.g. `vertexai`), and already-migrated code.
- [ ] No executable content anywhere in the YAML.
- [ ] `limitations` lists every semantic that is not 1:1, so the tool refuses instead of
      guessing.
- [ ] Commits are DCO signed off.
- [ ] CODEOWNERS approval is present.
- [ ] Any workflow the PR touches uses `pull_request`, never `pull_request_target`.

## DCO sign-off

Every commit carries a `Signed-off-by:` line (`git commit -s`): your statement under the
[Developer Certificate of Origin](https://developercertificate.org/) that you wrote the
contribution or have the right to submit it under Apache-2.0. `git commit --amend -s` fixes the
last commit; `git rebase --signoff main` fixes a branch.

## Issues and triage

Labels: `bug`, `migration-case`, `pack`, `question`, `needs-repro`, `roadmap`, `wontfix-v0`.

- Questions go to [Discussions](https://github.com/hakanbogan/obelize/discussions), bugs and
  migration cases to issues.
- I try to reply within 7 days, but I can't promise when a fix will land.
- Bug reports need evidence: a redacted `.obelize/runs/<id>/run.json` or a minimal
  reproduction, or the issue gets `needs-repro`, is marked stale after 14 days and closed at 30.
  Reopening with the missing detail is welcome.
- Out-of-scope requests are closed as `wontfix-v0` with a link to the non-goals in
  [docs/PRODUCT.md](docs/PRODUCT.md#v0-non-goals).
- Security issues do not belong in the tracker. See [SECURITY.md](SECURITY.md).

## Maintenance

I maintain Obelize alone in my spare time, so reviews can be slow and I turn down a lot of
scope. Before spending days on a large PR, open an issue and ask whether I'd merge it. Small,
tested PRs are much more likely to land.

## Beyond that

A few more rules for anything a reader sees: README, docs, CLI output, commit messages, and
issue or pull request text.

- I write as myself, in the first person. Never third person for the maintainer, and never
  "we" or "one person".
- No internal vocabulary reaches a reader: task id, gate, oracle, bail, round, row, finding key.
- No maxims. At most one "X, not Y" contrast per section.
- Bullets never open with bold text. No emoji, no legend of coloured symbols.
- No em dash in prose, and no double hyphen standing in for one.
- Headings are short noun phrases.
- Numbers 10 and above are written as digits; smaller ones as words.
- A reader-facing page names no ADR, decision or threat model number; it links to the
  document instead.
- UK spelling stays as written, and a flag or command name never changes to fit it.
- A commit subject is imperative, 72 characters or fewer, and carries no task id;
  `Signed-off-by` stays.
- I plan in a document that lives outside this repository. Naming that it exists is fine;
  quoting a section or a line from it is not, since a reader here has nothing to open.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Contributions are licensed under the [Apache License 2.0](LICENSE), like the rest of the
project.
