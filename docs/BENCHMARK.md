# Benchmark protocol

How obelize's migrations and scan are measured. The numbers are in
[BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md); this file carries none. The
harness is argued in
[ADR-042](adr/ADR-042-benchmark-harness-tiers.md)
and
[ADR-043](adr/ADR-043-round-one-results.md).

The target is **at least 20 real migration cases with at least 70% autonomous
`verified_success`** ([Gate 4](PRODUCT.md#what-would-make-this-a-product)): a
target, not a scientific threshold.

## Case definition

A case is a repository at a pinned SHA, a provider change and ground truth
written by hand before its scan record is opened, in `bench/cases.yaml`, read in
[`bench/CASES.md`](../bench/CASES.md) and decided field by field in
[ADR-041](adr/ADR-041-case-definitions-split.md).

| Field | Description |
|---|---|
| `id` | Case identifier, stable across rounds. |
| `provider` | Provider identity, for example `gemini`. |
| `change` | The migration being tested. |
| `from_version` / `to_version` | Mandatory exact (`==`) SDK pins, frozen for the round ([why](#version-pinning-is-mandatory)). |
| `repo` | Repository URL. |
| `sha` | Full 40-character commit SHA. |
| `license` | SPDX identifier, or `none`. |
| `split` | `dev` or `holdout`. |
| `pattern_key` | The sorted set of legacy symbols the case uses; the de-duplication key. |
| `python` | A full uv interpreter key, for example `cpython-3.12.9-macos-aarch64-none`, never `3.10`. |
| `install` | Reviewed commands from the repository's own manifest, only to make `test_cmd` runnable; none without one. |
| `test_cmd` | A command that exercises the changed code with no credentials and no network, or `null` with the reason in the ground truth. |
| `tests_require_network` | Whether the tests need network access. |
| `ground_truth.call_sites` | Every legacy call site, rendering to `file:line:symbol:auto|manual`, with `kind`, and a `why` on every `manual` row. `auto` means a correct edit follows from the code alone, not that the scanner can make it. |
| `ground_truth.manifests` | The dependency pins the migration must move, in the same form; a pin is not a symbol and does not enter `pattern_key`. |
| `ground_truth.must_not_report` | Positions where nothing may be reported, each with a reason (a mock target naming the project's own function, a confusable distribution, a call inside a string). |
| `ground_truth.files_read` | Every file the reviewer opened. |
| `ground_truth.tests_cover_change` | The reviewer's judgement on whether the tests exercise the changed code. |
| `reviewer` | Who prepared the ground truth. |
| `reviewed_at` | When. |
| `notes` | Anything a later reader needs to interpret the case. |

## Per-case result

One JSON file per case at `bench/results/<round>/<id>.json`, with no absolute
path in it.

| Field | Description |
|---|---|
| `detected` | Call sites obelize found. |
| `false_positive` | Findings that are not real usage. |
| `missed_call_site` | Ground-truth call sites obelize did not find. |
| `patch_applied` | Whether a patch was written. |
| `patch_compiles` | Whether every `.py` file the run wrote compiles under the case's interpreter, or `null` when nothing was written. The harness checks it because `obelize fix` with no verification command does not. |
| `unmigrated` | Ground-truth rows, call sites and manifest pins, the run left as they were. A row is migrated when the run refused nothing at its `(path, line, symbol)` and an applied edit landed on its line; one `requirements.txt` line can hold an applied `google-genai` add beside a withheld legacy pin. |
| `false_positive_edit` | Applied edits at a position no ground-truth row names; on a negative control, every applied edit. |
| `tests_baseline` | `{status, passed, failed, skipped}` before the migration, run by the harness. `status` is `pass`, `fail`, `inconclusive` or `not_run`, as in `obelize verify`. A pytest exit code `1` is `fail` and `2`-`5` are `inconclusive`, except a `2` whose junit report counts an error, which is `fail`. The counts come from a junit report added to a pytest command and are `null`, never `0`, without one. |
| `tests_after` | The same, after the migration and the *to* SDK install. |
| `human_edits` | Hunks a human had to write after obelize; `0` means autonomous. `null` until a reviewer reads the patch, and never read as `0`. |
| `patch_correct` | The reviewer's judgement; `null` until made. |
| `pr_opened` | `null`: the harness opens no pull request. |
| `pr_merged` | Whether it was merged, plus `merged_without_changes`; `null` for the same reason. |
| `runtime_seconds` | Wall-clock time of the obelize run. |
| `llm_tokens_in` / `llm_tokens_out` | Token counts, if a model was used. |
| `llm_cost_usd` | Cost, if a model was used. |

Provenance: `obelize_version`, `obelize_commit`, `pack`, `pack_sha256`,
`spec_sha256` (the `ScanSpec` a scan reads),
`python`, `python_executable` (harness paths shown as `<case>`, `<logs>`,
`<work>`, `<repo>` or `<harness-python>`), `python_build` (its `sys.version`,
which tells two machines' resolutions of one key apart),
`machine`, `os`, `sdk_from` and `sdk_to` (versions observed in the venv), and
`run_at`.

## Version pinning is mandatory

An unpinned install resolves silently to a different SDK: on CPython 3.9.6,
`uv pip install google-generativeai google-genai` exits `0` with
`google-genai==1.47.0`, not the API the pack targets. A bare `--python 3.10`
has resolved to two different interpreters on two runs. So:

- After steps 4 and 7 of the run, the runner asks the case's own interpreter
  (`importlib.metadata`, not `uv pip show`) which version it imports. A
  mismatch, or no answer, errors the case with `version_mismatch`.
- `python` is a full uv interpreter key, and a reviewed command starting with
  `python` runs the case's interpreter, not `PATH`'s.

## Outcome tiers

Tiers are computed from the fields above, never assigned. A reviewer's answer
is a field of the record, and a `null` is never read as a zero or a true. Tiers are tried in this order:

| Tier | Definition |
|---|---|
| `error` | Crash or timeout at any step: the case measured nothing. |
| `wrong` | `patch_correct` is false, `patch_compiles` is false, `false_positive_edit` > 0, or a patch turned a passing baseline into a failing after-run. A tool that broke a repository has not partially succeeded. |
| `unsupported` | Nothing was written: the fail-closed refusal. Whether it was informed is the `missed_call_site` column. |
| `partial` | `unmigrated` > 0, with no wrong edit. |
| `verified_success` | Everything the key names migrated; `false_positive`, `missed_call_site` and `human_edits` all 0; baseline and after both `pass`; `tests_cover_change` true; and, when the after-run has a junit count, at least one test passed, since a suite can exit `0` having skipped everything. |
| `patched_unverified` | A complete migration nothing verified: tests `not_run`, `inconclusive` or not covering the change, a failing baseline, or `human_edits` unanswered. |

- **Only `verified_success` counts toward the target.** A case with no test
  command cannot reach it and stays a case. `pr_merged` is a
  separate, stronger metric, reported on its own.
- **The ceiling is published before the round.** `bench/run.py` `ceiling` caps
  a case from its key alone: no test command, tests that do not cover the
  change, a row the key marks `manual`, or a row the pack flags rather than
  edits. `bench/summarize.py` publishes it.
- **A case with `llm_tokens_in > 0` is a separate arm, never in the headline.**
  The headline measures the deterministic rules; a model's edit that passes a
  repository's tests is otherwise indistinguishable from a rule's. The arms are reported side by
  side, each with its own `n`.

## Dev / holdout split

- Whole owners go to one side. Per stratum (repositories with a Python test
  file, and without), repositories are sorted by `sha256(full_name)` and their
  owners taken in that order into the holdout until it holds at least a third
  of the stratum's cases (`bench/cases.py` `split`). Stratifying
  keeps cases that can reach `verified_success` on both sides; nobody chooses a
  side.
- The holdout is frozen at the start of a round. A case whose holdout failure
  led to a rule change moves to `dev`, and the round number increments.

## Anti-inflation rules

- **No forks.**
- **At most 2 cases per repository owner.**
- The headline rate is reported over cases and, beside it, over unique
  `pattern_key` values (a pattern succeeds when any of its cases does), so forty
  near-identical call sites are one pattern.
- Every headline figure carries `n` and the split it was computed over.

Candidate selection already applies these.

## Negative controls

Cases that must produce no migration: a repository already on `google.genai`,
one on `vertexai.generative_models`, one on
`vertexai.preview.generative_models`, and one that mentions the SDK only in
documentation. Each is confirmed by a scan reporting no call site and no pin,
never by the search that found it, and is excluded from the success rate. The
drawn controls are in [`bench/CASES.md`](../bench/CASES.md#the-negative-controls).

Known false-positive traps, also CI fixtures: the `genai` alias both SDKs use
(resolution follows the import origin, never the alias); the live
`GenerativeModel` in `vertexai.generative_models` and in
`vertexai.preview.generative_models`, which only the import origin tells from
the legacy one; `google.ai.generativelanguage`; a repository's own `genai`
module; and a manifest that disagrees with the code (the code is the evidence).

## Reproducible run

`bench/run.py` runs locally; CI runs only its `--fixtures-only` pass. Per case:

1. Shallow-fetch the repository at the pinned SHA into `<work>/<round>/<id>/`,
   under the system temporary directory. A `pyproject.toml`, `pytest.ini`,
   `.pytest.ini`, `tox.ini`, `setup.cfg`, `setup.py` or `conftest.py` in any
   directory above it errors the case with `work_root_not_isolated`: pytest
   searches upward and would run the suite under that project.
2. `uv venv --python <py>` with the case's full uv interpreter key. Record the
   resolved interpreter path, its `sys.version` and `platform.machine()`.
3. Run the reviewed `install` commands.
4. Install `google-generativeai==<from_version>` and assert the installed
   version equals it.
5. Run `test_cmd` as the baseline, with a timeout and an output cap.
6. `obelize fix --pack gemini/... --apply --non-interactive --model none --json`,
   then compile every `.py` file it wrote with the case's interpreter.
7. Install `google-genai==<to_version>` and assert the installed version equals
   it.
8. Run the tests again.
9. Compare the findings in `findings.json` against the ground truth, and the
   applied edits in `plan.json` and `run.json` against the rows it names.
10. Write the result JSON.

Step 6 passes no `--verify`: the *to* SDK arrives only at step 7, so obelize's
own after-phase would fail every case; steps 5 and 8 replace it.
The harness grades from the run folder, never from the
[exit code](CLI.md#exit-codes). Step output goes to `<work>/<round>/<id>.logs/`
and is never committed. The gitignored `bench/work/` holds only
checkouts of `bench/gate1_collect.py`, `bench/candidates_collect.py` and
`bench/cases_collect.py`, which run no test suite.

**`--fixtures-only`** runs steps 5, 6 and 8 over the four repositories in
`bench/fixtures/` against their committed expected results, writing nothing to
`bench/results/`. Two carry doubles of both SDKs under `_vendor/`, which
obelize skips, so `verified_success` is reachable offline. Its executor refuses
every program but the running interpreter, so it cannot reach the network. `wrong` and `error` are covered by the tier function's own tests.

`bench/summarize.py` writes the round block of
[BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md), which lists every generated block
and its test; `--check` runs in the `bench-smoke` workflow. The candidate
corpus (URLs, SHAs, licences and metadata only) is
[`bench/CANDIDATES.md`](../bench/CANDIDATES.md).

## Licensing and publication rules

- **Repository code is never vendored.** What is stored is the URL, the SHA,
  the licence, ground-truth line references and the metrics.
- `patch.diff` is kept **only** for repositories under MIT, BSD, Apache or ISC;
  for copyleft or unlicensed repositories, only the metrics.
- **Every case in every round is published**, including `wrong`, `error` and
  `unsupported`.
- A case is never deleted. It is marked `retired` with a reason.

## Comparison arm

Once, on the dev split, a general-purpose coding agent given the official
migration guide runs blind against the same ground truth, and its runtime,
human corrections and accuracy are reported beside obelize's. The claim under
test: obelize adds an evidence chain, reproducibility and a path that needs no
model, not raw accuracy. The result is published either way;
[ADR-045](adr/ADR-045-comparison-arm.md)
argues each part.

- **The arm.** One agent with filesystem and shell tools, one run per case,
  given the repository at the pinned commit, a guide snapshot and
  [one fixed prompt](../bench/COMPARISON_PROMPT.md) whose only per-case content
  is three paths; `bench/comparison_collect.py` refuses a case whose prompt
  differs. *Blind* means no context from this project and a working directory
  named by a digest of the case id; the agent is not sandboxed from this
  repository.
- **Same restrictions.** One pass over the source: neither arm installs
  anything or runs the tests. No network beyond the guide, since live search
  would make the arm unreproducible. Every free choice favours the agent.
- **One instrument.** A key row is *cleared* when a scan of the tree afterwards
  no longer reports it, matched on `(path, kind, symbol)` because edits move
  lines. A row the scan misses on the untouched tree is credited to neither
  arm but stays in both arms' corrections. Obelize's cleared count must equal
  what its plan and withheld list say, case by case; that agreement licenses
  the scan for an arm with no plan.
- **Accuracy** is key rows cleared over key rows, plus any legacy usage an arm
  added. **Human corrections** are key rows still legacy plus edits the review
  rejected: rows, not `human_edits`' hunks, because grouping rows into hunks
  needs an arbitrary gap. **Runtime** is the wall clock of one
  pass: obelize's `runtime_seconds`, the agent's two stamps it writes; neither
  includes fetching, venvs or suites.
- **Review.** Whether what an arm wrote is right is recorded per arm per case in
  `bench/comparison.yaml`, and `patch_correct` derives from it; the round's
  `bench/cases.yaml` stays frozen.
- **Repeatability.** Three cases run a second time from the same bytes in a
  fresh tree, compared on files touched, line counts and rows cleared.
- **The ceiling.** `no test command` caps any arm; a `manual` row caps only a
  rule, so an arm exercising judgement can still reach `verified_success`. The
  results show the [ceiling](#outcome-tiers) beside `verified_success`.

## Scan precision and recall

Gate 1 ([PRODUCT.md](PRODUCT.md#what-would-make-this-a-product)) asks only whether `obelize scan` finds what is
there. None of its clauses is computable as written, so each is replaced by a
definition below.

### What is measured, and over what

| Quantity | Over | Why that population |
|---|---|---|
| Precision and recall | Five cloned repositories, hand-labelled before the scanner ran on them | Gate 1's number; five keys fit a budget where each is written by reading the files. |
| Repositories with at least one zero-bail file | The whole sample: at least sixty repositories from GitHub code search | Decides which rules are worth writing. |
| The unresolved share | Every usage in the whole sample | Gate 1's fallback trigger, a property of real code. |
| What each repository declares about its Python | The whole sample | How often [ADR-023](adr/ADR-023-scan-command.md) D6's manifest floor fires outside a fixture, read through the shipped `scan/runtime.py`. |

### A row, and what counts as a match

A finding matches a labelled call site when **path, line, kind and symbol** are
all equal, symbols fully qualified
(`google.generativeai.GenerativeModel.generate_content`); rows are multisets.
The right line with the wrong symbol is one false positive and one miss,
because `obelize scan` prints the symbol. Precision is `TP / (TP + FP)` and recall `TP / (TP + FN)`; with no findings,
precision is published as `--`, never `100%`.

### Which findings the rate is computed over

Only `import`, `call`, `method_call` and `attribute`. `text_mention`,
`manifest`, `dynamic`, `star_import` and `parse_error` are deliberate, not call
sites, and tabled separately. The byte prefilter's file-level precision is a
parsing cost, not a false-positive rate. Each key also lists `expected_other`
(non-actionable rows it is right to report) and `must_not_report`, both written
before the scan, so "unexpected" is a pre-registered count.

### A zero-bail file

A file with at least one actionable `scan_status: eligible` finding and none a
scan-time rule withheld (`needs_review` or `unsupported`); a repository counts
when it has one. Both halves follow from
[ADR-010](adr/ADR-010-fixture-oracle-and-atomicity.md) F-1: one bail withholds
the whole file, and no rule acts on a `text_mention`.

### "Cannot be resolved statically", as a set

Gate 1's fallback trigger is computed over these `confidence_reason` values
only:

| | Values |
|---|---|
| Resolved | `direct_import_resolved`, `alias_resolved`, `from_import_resolved`, `receiver_bound_same_scope`, `receiver_bound_module_const`, `receiver_bound_self_attr` |
| Unresolved | `conditional_binding`, `module_alias_rebound`, `receiver_unresolved`, `dynamic_access`, `star_import`, `star_import_candidate` |

`string_or_comment_mention`, `mock_patch_target`, `manifest_dependency` and
`parse_error` are not a usage and in neither set; a test asserts the three
sets are exactly the vocabulary.

### The sample, and what is wrong with it

The frame is GitHub code search for the prefilter token `generativeai` in
Python, in four file-size bands allocated by population, sampled systematically
across the first four pages of each band. Forks, second repositories of an
owner, the three development-corpus owners and anything over 150 MB are dropped
with a reason; `bench/gate1/sample.yaml` holds the drawn list, the band
populations and every rejection. Its biases:

- **Not random**: code search is relevance-ordered and indexes only default
  branches; size bands remove only the largest visible bias.
- **Not reproducible**: GitHub re-indexes continuously, so the drawn list is
  committed, not the query.
- **Small single-purpose applications**, not codebases that would look for a
  migration tool.
- **Five keys chosen for labelling cost** (`bench/gate1_collect.py choose`): the
  first repository per band with two to eight Python files containing the
  token, plus one from the most populous band, so none of the largest.

## Error analysis

After each round, every key row the round did not migrate is read and becomes a
**rule change**, a **scan change** or a **recorded limitation**, and nothing
else. `tests/unit/test_bench_errors.py` fails on a cause without a disposition
and on a disposition without a cause.
[ADR-044](adr/ADR-044-error-analysis.md) argues
each part.

| File | Written by | Holds |
|---|---|---|
| `bench/cases.yaml` | a reviewer, before the round | the rows a complete migration has to change |
| `bench/results/errors/round-<n>.json` | `bench/errors_collect.py`, from the run folders | what the round did with each row, and every finding it reported |
| `bench/errors.yaml` | a reviewer, after reading the rows | one disposition per cause, and a cause for each row the scan never reported |

The run folders sit in temporary checkouts the next round overwrites, so the
collector commits the rows once. A row the scan never reported has no bail
code, so its cause is hand-written; the test asserts that list is exactly the
round's misses.

- **Recorded where.** A `limitation` names the ADR that decided it; a
  `rule_change` or `scan_change` names an open, numbered gap in
  `tests/fixtures/scan/COVERAGE.md`. The test checks that the ADR exists and
  the gap is open.
- **The lever.** A bail's count does not say what fixing it buys, because
  [ADR-010](adr/ADR-010-fixture-oracle-and-atomicity.md) F-1 withholds a whole
  file on any bail and F-2 withholds the legacy pin until the repository has
  migrated. The lever is the round recomputed with one cause fixed. With
  nothing lifted it reproduces the round's migrated count; with everything
  lifted it falls short by exactly the rows no pass reported. Levers do not add
  up.
- **A wrong key** is corrected in `bench/cases.yaml` with the reason in the
  row's `why`; the round is republished only if a published number moves.
