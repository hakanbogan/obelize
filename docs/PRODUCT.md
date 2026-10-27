# Product boundary

Where this page and the code disagree, the code and [CLI.md](CLI.md) win.

## What obelize is

A local-first command-line tool for verified dependency upgrades. When a Python library makes a
breaking change, obelize rewrites the code it can prove safe to change, refuses the rest with a
reason, and checks the result against your own tests. Today it ships three migrations of libraries, from
`google-generativeai` to `google-genai`, from `openai` 0.x to 1.x and from `PyPDF2` to `pypdf`, three
for the Python itself (`datetime.utcnow()`, `pkg_resources` and the modules Python 3.12 and 3.13
removed), and it makes a pack for another library from two of its releases; they are examples of the method, and
the [roadmap](ROADMAP.md) says where it goes next. The chain:

```
change source (a migration pack: a bundled one cites an official guide, one made from two releases cites them)
  -> source and schema validation
  -> repository scan and impact candidates
  -> call-site evidence and a migration plan
  -> deterministic transformation, or an explicit refusal
  -> a controlled patch
  -> verification against a baseline, using your commands
  -> an evidence report for human review
```

Three properties define the boundary:

- Local-first. Scan, patch and verification run on your machine, with no account, hosted
  runner or required service, and no network call unless you configure a model endpoint
  or ask it to read a library's releases from the package index ([PRIVACY.md](PRIVACY.md)).
- Evidence over confidence. Every finding carries a file, line, resolved symbol and a
  `confidence_reason` from a closed vocabulary, and every run writes `.obelize/runs/<id>/`. No
  numeric confidence score is reported until calibration data backs one.
- Refusal is a valid outcome. A transformation that is not a 1:1 semantic match is marked
  `needs_review` or `unsupported` with a reason code, not guessed.

obelize is not a general-purpose coding agent, and it does not let a model migrate code on its own.
Its models, an endpoint you configure or your own `claude` program in a trial, are optional
fallbacks for the places a rule cannot write, behind a guard. In a trial only your tests decide
whether what they wrote stays; an endpoint's edits are written on request and are lines to review.
It works beside a coding agent: the agent edits, and obelize reports what is
left and runs the check.

## Who it is for

A developer or small team with Python code on GitHub that depends on a library which is retired or
has made a breaking release.

## What ships today

- The commands in [CLI.md](CLI.md#surface); `fix` is dry-run unless given `--apply`.
- Seven bundled packs, `gemini/google-generativeai-to-google-genai`, `numpy/numpy-1-to-2`,
  `openai/openai-0-to-1` and `py-pdf/pypdf2-to-pypdf` for libraries, `python/datetime-utcnow`,
  `setuptools/pkg-resources-to-importlib` and `python/removed-stdlib-modules` for the Python
  itself, and packs of your own from directories your config lists, several to a run.
- Finding a library's breaking changes without a bundled pack: `scan --library` lists the places a
  library with no pack touches, and `pack synth` makes a pack from two releases of it.
- `outdated` and `upgrade`, which try a move in a copy of the repository with two environments and
  your own tests, write it only if no test that passed now fails, and can commit it to a branch you
  ask for, with your own `claude` program moving the places a pack can only flag.
- Tools for writing a pack, `pack new` and `pack test`, and kinds a pack can use to rename a member
  of a class, rewrite a call from the shape of its arguments, or hand a change to a plugin you
  install and allow.
- A server that lets a coding agent call obelize, `obelize mcp`, and a GitHub Action and pre-commit
  hook that run a scan. The action also upgrades a dependency in one job, and a documented second
  job opens the pull request.
- An optional network step that reads a package index, with every host named first and `--offline`.
- Two example repositories, `examples/gemini-legacy-app` and `examples/quickstart`.
- The evidence run folder, the benchmark protocol and a published result file.

## Planned

The [roadmap](ROADMAP.md) lists these in the order I intend to build them. None of them ships until
the changelog says so, and the README describes only what ships.

- Reading a migration guide to draft rules, and a pipeline that opens the pull request of an
  upgrade.
- A registry to share a pack, and more fixers such as ruff behind the same evidence
  ([the first one ships](adr/ADR-074-external-fixer.md)).

## Not planned

An issue asking for one of these is closed with a link here.

- A SaaS or cloud product, or any hosted component.
- A dashboard or web UI.
- A GitHub App.
- Telemetry of any kind.
- A command that pushes, or opens a pull request itself.
- Checking HTTP API integrations.

## What would make this a product

Each phase closes on an observable gate. A missed gate reduces scope; it never moves the date
by adding work.

- Gate 0: migration semantics (the automatic/manual boundary) and the fixture ground truth
  used to measure them are validated; if fewer than two changes can be expressed as
  deterministic codemods, the migration family is changed.
- Gate 1: real call sites are found, and false positives and missed cases are measured
  (working target: FP <= 10%, missed <= 10% across 5 cloned repositories); if more than 30% of
  call sites cannot be resolved statically, `scan` narrows to module-level imports and direct
  `GenerativeModel` use. **Passed.** As written, the rate has no denominator and "resolved
  statically" no definition, so each clause is measured by a formula fixed before counting:
  [BENCHMARK.md](BENCHMARK.md#scan-precision-and-recall) defines them,
  [the reasoning behind them](adr/ADR-024-gate-1-measurement.md) is written up separately, and
  [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md#scan-precision-and-recall-gate-1) has the numbers.
- Gate 2: one real migration runs safely on both a clean and a dirty repository; if the
  `GenerativeModel(...).generate_content` rewrite is not finished in time, the release ships
  with imports and `configure` to `Client` automatic and the rest flagged for manual work.
- Gate 3: the known rules work with no model at all, and ambiguous cases fail closed in a
  way that can be trusted; if the schedule slips, Phase 3 moves to v0.2 in full.
- Gate 4: the benchmark is published with the denominator of every number, and the result
  decides what the announcement says, not whether there is one. At >= 70% `verified_success`
  on unique patterns the announcement leads with the rewrite; below that it leads with the
  scan, puts the failure table first and gives each rewrite number with its `n`.
- Gate 5: on 2026-11-03, I count what needs no telemetry: downloads outside CI
  by installer (PyPI's public BigQuery data), issues and migration-case reports, and stars. An
  outside post in Discussions counts as a report, and the date does not move. The count is a
  measurement and does not stop the work on the [roadmap](ROADMAP.md): with no outside issue,
  report or pull request, I hold five interviews and decide whether the direction is right
  ([the decision](adr/ADR-059-verified-dependency-upgrades.md)).

## Neighbouring tools

As of October 2026, from each project's own public material, which states its claims about
itself; re-check before any public comparison.

- Moderne, built on OpenRewrite, added Python support in February 2026 and publishes recipes for
  Python version upgrades, the standard-library modules PEP 594 removed, `datetime.utcnow`,
  Pydantic, pandas and LangChain. It is a platform with a command-line tool and an MCP server, and
  at least one Python recipe is under a proprietary licence.
- Codemod and ast-grep run pattern rules over a syntax tree; ast-grep supports Python under the MIT
  licence, and Codemod is JavaScript and TypeScript first.
- GitHub can assign security-focused Dependabot alerts to coding agents that open draft
  remediation pull requests, and Renovate covers dependency updates.
- AWS Transform custom has an agent write the edits from a definition authored in conversation, and
  checks them with the build and test command you give it.
- Portover detects call sites in consenting consumer repositories for provider-driven breaking
  changes, tests the result in a micro virtual machine and opens migration pull requests with
  evidence (JavaScript/Node and Python). Closed-source SaaS, no CLI; pilots by email.

OpenAI's own `openai migrate` command was removed in `openai` 2.35.0, and `bump-pydantic` is
archived. A coding agent, given a library's migration guide, edits more than obelize does, and
that is the nearest competitor; obelize is the part around it that an agent's own report cannot
be: a deterministic scan that says what is left, a diff that changes nothing else, and an undo.
