# Benchmark protocol

How obelize's migrations and scan are measured. The numbers are in
[BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md); this file carries none. The
harness is argued in
[ADR-042](adr/ADR-042-benchmark-harness-tiers.md)
and
[ADR-043](adr/ADR-043-round-one-results.md). Gate 1 and the rounds were run for the Gemini pack only; the PyPDF2 and
openai packs have no Gate 1 measurement or round
([ADR-051](adr/ADR-051-second-migration-family.md), [ADR-053](adr/ADR-053-shared-module-migrations.md)),
and all three have a [dry-run measurement](#fix-dry-run).

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
| `forbidden_reported` | Findings of any kind at a `ground_truth.must_not_report` position. An actionable one is also a `false_positive`, but a `text_mention` there is nothing else. Recorded, not a tier input; round 1's records lack it, and [`bench/CASES.md`](../bench/CASES.md) counts the same positions in the scan records. |
| `patch_applied` | Whether a patch was written. |
| `patch_compiles` | Whether every `.py` file the run wrote compiles under the case's interpreter, or `null` when nothing was written. The harness checks it because `obelize fix` with no verification command does not. |
| `unmigrated` | Ground-truth rows, call sites and manifest pins, the run left as they were. A row is migrated when the run refused nothing at its `(path, line, symbol)` and an applied edit landed on its line; one `requirements.txt` line can hold an applied `google-genai` add beside a withheld legacy pin. |
| `false_positive_edit` | Applied edits at a position no ground-truth row names; on a negative control, every applied edit. |
| `tests_baseline` | `{status, passed, failed, skipped}` before the migration, run by the harness. `status` is `pass`, `fail`, `inconclusive` or `not_run`, the words `obelize verify` uses. A pytest exit code `1` is `fail` and `2`-`5` are `inconclusive`, except a `2` whose junit report counts an error, which is `fail`. The counts come from a junit report added to a pytest command (`pytest`, `py.test` or `python -m pytest`, as `obelize verify` reads one) and are `null`, never `0`, without one. |
| `tests_after` | The same, after the migration and the *to* SDK install, with the legacy SDK still installed ([step 7](#reproducible-run)). |
| `human_edits` | Hunks a human had to write after obelize; `0` means autonomous. `null` until a reviewer reads the patch, and never read as `0`. |
| `patch_correct` | The reviewer's judgement; `null` until made. |
| `pr_opened` | `null`: the harness opens no pull request. |
| `pr_merged` | Whether it was merged, plus `merged_without_changes`; `null` for the same reason. |
| `runtime_seconds` | Wall-clock time of the obelize run. |
| `llm_tokens_in` / `llm_tokens_out` | Token counts, if a model was used. |
| `llm_cost_usd` | Cost, if a model was used. |

Provenance: `obelize_version`, `obelize_commit` and `obelize_tree_dirty` (read once when the round
starts), `pack`, `pack_sha256`,
`spec_sha256` (the `ScanSpec` a scan reads),
`python`, `python_executable` (harness paths shown as `<case>`, `<logs>`,
`<work>`, `<repo>` or `<harness-python>`), `python_build` (its `sys.version`,
which tells two machines' resolutions of one key apart),
`machine`, `os`, `sdk_from` and `sdk_to` (versions observed in the venv), `uv_version`,
`exclude_newer` (the cutoff every install resolved as of), `packages_sha256` (the installed set
after step 7, with the checkout's own path elided) and `run_at`. Round 1's records lack
`obelize_tree_dirty`, `uv_version`, `exclude_newer` and `packages_sha256`.

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
- Round 2 starts with `kvcops__Virtual-Herbal-Garden` and
  `LJX2017__A-Song-of-Ice-and-Fire` in `dev`: they were holdout cases in round 1, and the
  rule that closed COVERAGE gap 29 was written from their code. `bench/cases.yaml` still reads
  `round: 1` and `holdout` for them, because `bench/results/round-1/` and the results page are
  round 1's and `python -m bench.summarize --check` holds the two together. The file changes in the
  commit that publishes round 2. A `fix` dry run over the 23 round-1 repositories at their pinned
  commits gives the rows 0.3.0 gave, except the 26 that the rule moved from `needs_review` to
  `auto`: 20 in kvcops and 6 in `Momen2410__Question-Answering-ChatBot-Using-Gemini1.5`.

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

`python -m bench.run` runs locally, from the repository root; CI runs only its `--fixtures-only` pass. It builds POSIX virtual
environments and is not run on Windows. It runs each repository's own install commands and test suite
with no sandbox and the network available, so run it only on a machine or VM that holds no
credentials. A round starts only on a committed tree (`bench/results/` aside) whose `src/` is where
`obelize` is imported from, not an installed copy, even one in the checkout's own `.venv`, so each
record names the code that ran. Every install resolves as of the
round's start (`UV_EXCLUDE_NEWER`, recorded as `exclude_newer`), and `--exclude-newer <UTC time>`
runs a round as of an earlier one. Per case:

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
   it. The legacy distribution from step 4 stays installed beside it, so a file the migration
   missed still imports and the after-run can pass over it. `uv pip freeze` then lists what is
   installed: the list is that step's log, and its sha256 is `packages_sha256`.
8. Run the tests again.
9. Compare the findings in `findings.json` against the ground truth, and the
   applied edits in `plan.json` and `run.json` against the rows it names.
10. Write the result JSON.

Step 6 passes no `--verify`: the *to* SDK arrives only at step 7, so obelize's
own after-phase would fail every case; steps 5 and 8 replace it.
The harness grades from the run folder, never from the
[exit code](CLI.md#exit-codes). Each step runs without a shell, in a session of its own whose
process group is killed when the step ends, so a process a suite leaves in that group does not
outlive its step, and its output goes to a file, so no child holds a finished step to its ceiling.
A child that starts a session of its own is not reached ([TM-10](THREAT_MODEL.md) says the same of
`obelize verify`). A step inherits `PATH`, `LANG`, `LC_ALL`, `TMPDIR`, `UV_CACHE_DIR`,
`UV_PYTHON_INSTALL_DIR` and `PIP_CACHE_DIR` where the harness has them, and a `HOME` of its own
under `<work>/home`, so no credential, key or tool configuration of the machine reaches an install
or a suite. Without the three directory variables, uv and pip keep their caches and interpreters
under that `HOME`, and the first round on a machine downloads them again. Step output goes to `<work>/<round>/<id>.logs/`
and is never committed. The gitignored `bench/work/` holds only
checkouts of `bench/gate1_collect.py`, `bench/candidates_collect.py` and
`bench/cases_collect.py`, which run no test suite.

**`--fixtures-only`** runs steps 5, 6 and 8 over the four repositories in
`bench/fixtures/` against their committed expected results, writing nothing to
`bench/results/`. Two carry doubles of both SDKs under `_vendor/`, which
obelize skips, so `verified_success` is reachable offline. Its executor refuses
every program but the running interpreter, so it cannot reach the network. `wrong` and `error` are covered by the tier function's own tests.

`python -m bench.summarize` writes the round block of
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
  would make the arm unreproducible. Every free choice favours the agent. Afterwards
  `python -m bench.comparison_collect record` installs each case's requirements and runs its
  suite over the agent's tree, as step 8 does over obelize's: with a step's environment
  ([above](#reproducible-run)) and as of the round's `exclude_newer`, which the comparison
  record repeats (round 1 named none).
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
| Resolved | `direct_import_resolved`, `alias_resolved`, `from_import_resolved`, `receiver_bound_same_scope`, `receiver_bound_module_const`, `receiver_bound_self_attr`, `receiver_typed_by_class` |
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
- **Five keys chosen for labelling cost** (`python -m bench.gate1_collect choose`): the
  first repository per band with two to eight Python files containing the
  token, plus one from the most populous band, so none of the largest.

## Fix dry run

What the rules alone would write, for each bundled pack, over a frame of repositories that use
its library ([ADR-024](adr/ADR-024-gate-1-measurement.md) D10). `python -m bench.gate1_collect dryrun --pack <id>`
fetches each repository at its pinned commit and runs `obelize fix --pack <id> --model none` once,
and keeps the number of files the plan would write, the pack's `blocked` reason, and every withheld
row with its symbol and bail. It always runs the whole frame, so a retry cannot replace the other
records. `bench/dryrun_score.py` tables the outcomes:

| Outcome | Meaning |
|---|---|
| `blocked` | the pack stops before it plans, for the `blocked` reason (the legacy distribution declared nowhere, or with no lower bound or one under the pack's floor, for one; a pack that names its newest release takes an unpinned declaration as that release, and one that names what only its old range defines takes it as that range beside code that uses one; each stops only where the repository shows another release) |
| `none` | the pack runs and finds no usage; a mention in a comment and a manifest row are none |
| `held` | usages found, no file written |
| `partial` | a file written and a row withheld |
| `complete` | a file written, nothing withheld |

The frame is drawn like Gate 1's, in the same four size bands, with a term per pack: `generativeai`
for Gemini, `PyPDF2` for PyPDF2, and `"openai.ChatCompletion"` for openai. The openai term is not the
pack's prefilter token: `openai` matches every modern file too, and the frame would be mostly
repositories the pack has nothing to say about. A repository whose only legacy call is
`openai.Embedding` is therefore not in its frame. The biases are the sample's
([above](#the-sample-and-what-is-wrong-with-it)), and there is no answer key, so a `complete` repository
means the plan wrote something, not that what it wrote is right; the rounds measure that, for Gemini.
The Gemini frame holds some of the round-1 cases its rules were written against, so its row is a
comparator and not a holdout.

Gate 1's scan and these three dry runs were taken with 0.9.0 and not again for 0.10.0, which changed
what `upgrade` writes. `scan` and `fix` with the bundled packs gave the same output in 0.10.0 as in
0.9.0 on the repositories of the test suite and the examples (findings, plans, diffs and reports
compared), and the fixtures of the packs are unchanged and pass, so their records say `obelize 0.9.0`.

## Upgrade dry run

What `obelize upgrade <distribution> --from A --to B` would write for a library that has no pack,
over four frames of twenty public repositories each that still use the old API of pydantic
1.10.26, SQLAlchemy 1.4.54, urllib3 1.26.20 and pandas 2.3.3, moving to 2.12.5, 2.0.55, 2.8.0 and
3.1.0. `python -m bench.upgrade_collect run` makes the pack once per migration from the two
releases, as `pack synth` does, and plans every repository of the frame with it in a dry run: no
`--apply`, so nothing is installed or tried, no model or agent is asked, no file of a clone is run
and nothing is written. Each repository is fetched at its pinned commit, shallow, into a directory
of its own. A record keeps what the scan read as a usage (a manifest row and a mention in a comment
are none), how many of those a rule rewrites by kind and how many the pack only flags, the files
the plan would write, and every withheld row with its symbol and bail. `bench/upgrade_score.py`
tables the outcomes with the tiers of the [fix dry run](#fix-dry-run), plus what became of each
usage. A record says what the plan is written by (`unit`): a record made with 0.9.0 names none and is
of a plan written whole or not at all, so a repository with a place left is `held`; a record made
after `upgrade` wrote a file at a time says `file`, and the same repository is `partial`. The
committed records are of 0.10.0 and say `file`; the scorer still words a record with no unit as the
one it is, and the 0.9.0 records are in the repository at the tag `v0.9.0`.
`python -m bench.upgrade_collect run -m SLUG --only OWNER/REPO --out DIR` checks part of a
frame and needs `--out`, since a committed record of part of a frame would replace the whole.

The frames are drawn like Gate 1's, in the same four size bands, with a term that only code written
for the old release spells: `from pydantic import validator`, `from sqlalchemy.ext.declarative
import declarative_base`, `method_whitelist "urllib3.util.retry import Retry"` and
`infer_datetime_format`. Forks, a second repository of an owner, the owners the mode was developed
on, a hit inside a vendored copy of the library and anything over 150 MB are dropped with a reason;
`bench/upgrade/<slug>/sample.yaml` holds the drawn list, the releases, the band populations and
every rejection. Its biases are the sample's ([above](#the-sample-and-what-is-wrong-with-it)), and
more:

- **The term picks repositories that import the old API.** A repository already on the new release,
  or that uses the library only through another part of it, is not in a frame, so a frame says what
  the pack does with code written for the old release and nothing about a typical user of the
  library.
- **Four libraries whose majors broke a lot.** What a pack made from two releases finds in a library
  that broke little is not measured.
- **The pack comes from the live index.** It is made from the two releases the frame names, read
  from the package index on the day of the run, so a later run can make another pack (an index that
  changed, a release withdrawn) and is not compared with this one except by a person.
- **No answer key, and no trial here.** A `complete` repository would mean the plan wrote something,
  not that it is right, and the tests of a repository are not run in the dry run. The trial of the
  repositories whose plan writes a file is [measured apart](#how-the-trial-is-measured).

## How the trial is measured

The [trial](CLI.md#a-trial) of `obelize upgrade <distribution> --apply --yes` installs the
dependencies of a repository, which runs the build scripts of whatever it installs, and runs that
repository's tests. I measure it only in a box that reaches nothing but the package index, and the
harness will not start a run until a self-test has shown, in that run, that it does.
`python -m bench.trial_collect run -m SLUG --work DIR` tries the repositories of a frame whose
dry-run record says the plan writes at least one file, whichever rule wrote that plan, each in a
container of its own, and writes `bench/results/trial/<slug>.json`. `python -m bench.trial_score`
tables the records in [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md#upgrade-trial), and says for each
frame with no record how many of its repositories have a plan that writes a file, so a frame with no
trial is shown with why. With no record at all the section is not there. `smoke` tries one
repository I made myself, for the box and not for a number.

### The box

The image is `python:3.12-slim` held to a digest, with git, a compiler, uv 0.12.15, the Pythons 3.9
to 3.14 that uv installed (never downloaded at run time) and the wheel under test, which is built
with `uv build` from a `git archive` of `HEAD` and never from the working tree. A container is made
only by `bench/trial_box.py`, whose parameters cannot express a privilege, a mount or a port, and
whose result is checked once more against a list of the flags it may hold. Its tests assert each
forbidden flag cannot be produced.

| What | How it is held back |
|---|---|
| Network | An internal Docker network with no route out and no name service for the outside. The only way out is a proxy in a container of its own: it carries `CONNECT` to `pypi.org:443` and `files.pythonhosted.org:443` and answers 403 to everything else. `HTTP_PROXY` and `HTTPS_PROXY` point at it, and `localhost` is kept off it so a test can reach its own server. |
| Privilege | No capability, `no-new-privileges`, a user that has no name on the host (uid 10001), no device, no host process or IPC namespace, no `--privileged`. |
| Files | Nothing of the machine is mounted and there is no Docker socket. The clone is copied in as it is, owned by that user, and one small file, `trial.json`, is copied out. No home directory, key or credential is given. |
| Environment | Only the two proxy variables and their lower-case forms, `NO_PROXY` and uv's timeout, each with the value the harness gives, and `CI`, which the harness may give and does not. No variable of the machine is passed. |
| Resources | 2 GiB of memory and no swap, two CPUs, 1,024 processes and, by default, 90 minutes of wall clock, after which the container is killed. The disk is looked at every 20 s and a container over 8 GiB is killed: that is a watch, so a write that ends between two looks is not caught. |
| Output | Docker keeps none. The harness keeps the first 128 KiB and the last 256 KiB. |

At most `--jobs` containers run at once (two by default, and the harness refuses a number that
does not fit in the memory of the Docker VM). Each repository is fetched at its pinned commit by
the machinery of the dry-run collector into a directory under `--work`, which must be outside this
repository, copied into a fresh container and deleted afterwards. Every name the harness makes
starts with `obelize-trial-`, and `python -m bench.trial_collect cleanup` removes only what carries
that prefix and its label.

### The self-test

`python -m bench.trial_collect selftest`, and the first step of `run` and `smoke`, makes a container
with the function that makes a trial's and asks it what it can reach and hold. It fails, with exit
`1`, and nothing is run, if any of these is not so:

- the user is 10001 with no other group, no capability is held, `no-new-privileges` is set and the
  container's process namespace is its own;
- no mount but the container's own file system, the kernel's and the init program is there, no host
  path (`/Users`, `/Volumes`, `/host_mnt`) exists, no Docker socket is there and no variable but
  those of the image and the allowlist is set;
- memory, swap, processes and CPUs are capped as asked, in the cgroup the container sees and in
  what the daemon reports for it;
- the network is internal, and a direct connection to three public addresses, to an IPv6 address
  and to the default gateway where the network has one, and a name lookup of `example.com`,
  `pypi.org`, `files.pythonhosted.org` and `host.docker.internal`, all fail;
- the proxy answers 403 to a `CONNECT` to `example.com`, `github.com`, an IP address, a port other
  than 443 on an index host, the host, itself and loopback, and to a plain request, and carries both
  index hosts through TLS.

The probe observes and `bench/trial_box.py` judges: a property the probe could not read is a
failure. The record keeps the result, the number of attempts, and what the proxy carried and
refused during the run, by host.

### What it does not protect

- A repository's tests can still reach the two index hosts and use the container's CPU for their
  limited time. The proxy does not read the TLS inside its tunnels, so it cannot tell a request
  for a package from another request to the same host. Nothing can be uploaded without a
  credential, and none exists in the box.
- The container shares the kernel of the Docker VM. A flaw in the kernel or the container runtime is
  outside what this protects against.
- The disk limit is a watch, as above. Containers that run at the same time are on one internal
  network and can reach each other, which `--jobs 1` avoids. The networks and the proxy have fixed
  names, so only one run at a time can use them.
- The box protects the machine, not the measurement. A hostile test can write the lines and the
  file the harness reads a verdict from, so a result is read as what the repository's own tests
  reported, never as proof about the repository.
- Nothing is pushed, published or sent anywhere, and the clones are deleted. The fetch itself runs
  on the machine with `git`, as the dry-run collector's does, and runs no file of a clone.

### What a record holds

The obelize version, the commit the wheel was built from, the wheel's sha256, the image id, the uv
and Docker versions, the date, the limits, the allowlist, the self-test's result and the proxy's
counts by host; and for each repository its commit, the Python it was given, the status and reason,
the tests compared and broken (the names, up to 20), the files written and left, the places left
for a person, the exit code, the seconds and, for an `error`, a `timeout` or an `inconclusive`, the
end of the output with this machine's paths written as `<work>/`.

A repository gets the newest of Python 3.9 to 3.13 that the `requires-python` in its
`pyproject.toml` admits, else the Python its `.python-version` names if the image holds it, else
3.12. A trial is classified by its own `Trial of ...` line and its `trial.json`, and the exit code
only checks them: `pass` (exit `0`, or `4` where places are left, which the record calls `partial`),
`fail` (`3`), `inconclusive` with the reason the engine gives (`6`), `timeout` where the container
was killed for its time, and `error` for a run that reached no verdict, with the cause the output
gives (the dependencies could not be installed, the container ran out of memory or disk, the
harness could not run it) or one the harness does not know.

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
  up, and each is an upper bound: a rule refuses at its first failed check, so a
  refusal behind the recorded one is not in the record, and fixing the recorded
  cause can release fewer rows than the lever says.
- **A wrong key** is corrected in `bench/cases.yaml` with the reason in the
  row's `why`; the round is republished only if a published number moves.
