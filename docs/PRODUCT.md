# Product boundary

Where this page and the code disagree, the code and [CLI.md](CLI.md) win.

## What Obelize is

A local-first command-line tool that migrates Python code across versions of an external SDK
or API and leaves an evidence trail a reviewer can check: which file is affected, whether the
fix is correct, whether your tests still pass. The chain:

```
change source (a migration pack citing an official guide)
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
  ([PRIVACY.md](PRIVACY.md)).
- Evidence over confidence. Every finding carries a file, line, resolved symbol and a
  `confidence_reason` from a closed vocabulary, and every run writes `.obelize/runs/<id>/`. No
  numeric confidence score is reported until calibration data backs one.
- Refusal is a valid outcome. A transformation that is not a 1:1 semantic match is marked
  `needs_review` or `unsupported` with a reason code, not guessed.

Obelize is not an API diff engine, a general-purpose coding agent, or an LLM that migrates code
on its own. Its one model adapter is an optional fallback for ambiguous cases, behind a guard.

## Who it is for

A developer or small team with Python code on GitHub that integrates an external API or SDK.

## Layer boundary

v0 is the open-source command-line tool and nothing else, all on your machine. A hosted product
is out of scope and has no code. Being open source or using a CST is not by itself a
defensible advantage.

## v0 scope

- The commands in [CLI.md](CLI.md#surface); `fix` is dry-run unless given `--apply`.
- One bundled pack, `gemini/google-generativeai-to-google-genai`.
- One example repository, `examples/gemini-legacy-app`.
- The evidence run folder, the benchmark protocol and a published result file.

## v0 non-goals

An issue asking for one of these is closed with a link here.

- A SaaS or cloud product, or any hosted component.
- A dashboard or web UI.
- A GitHub App.
- Automatic pull requests, commits, branches or merges.
- A second provider or migration family.
- `pack create`.
- Remote pack download or a pack registry.
- Pack signing.
- Telemetry of any kind.
- More than one model adapter.
- An advanced cache.
- The `--guide` flow that reads a migration guide directly (candidate for v0.2).
- Finding migrations without a pack, and checking HTTP API integrations.

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
- Gate 5: four weeks after release, I count what needs no telemetry: downloads outside CI
  by installer (PyPI's public BigQuery data), issues and migration-case reports, and stars. No
  outside issue, report or pull request means feature work stops, five interviews are held,
  and a pivot is decided (scan-only, a different migration family, or stopping).

## Neighbouring tools

As of September 2026, from each project's own public material, which states its claims about
itself; re-check before any public comparison.

- Portover, closest to Obelize's long-term direction: detects call sites in consenting
  consumer repositories for provider-driven breaking changes, tests the result in a micro
  virtual machine and opens migration pull requests with evidence (JavaScript/Node and Python).
  Closed-source SaaS, no CLI; pilots by email.
- GitHub can assign security-focused Dependabot alerts to coding agents that open draft
  remediation pull requests; Renovate covers dependency updates; OpenRewrite and Moderne cover
  bulk source transformation; oasdiff and Bump.sh cover API diffing.

Obelize has to earn, not assert, its difference: free local scanning and fixing that works,
distribution starting with the individual developer, usage and impact evidence for specific
provider migrations, and a verified change with a reproducible, model-free path.
