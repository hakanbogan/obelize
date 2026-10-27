# obelize

Verified codemods for breaking Python dependency upgrades. obelize rewrites the code it can prove
safe to change, tells you why it left the rest, and runs your tests before and after. It ships
migrations from `google-generativeai` to `google-genai`, `numpy` 1.x to 2.x, `openai` 0.x to 1.x and
`PyPDF2` to `pypdf`, three for the Python itself (`datetime.utcnow()`, `pkg_resources` of
`setuptools`, and the modules Python 3.12 and 3.13 removed), and for another library it makes one
from two of its releases.

[![Python](https://img.shields.io/pypi/pyversions/obelize)](https://pypi.org/project/obelize/)
[![Licence](https://img.shields.io/pypi/l/obelize)](https://github.com/hakanbogan/obelize/blob/main/LICENSE)
[![CI](https://github.com/hakanbogan/obelize/actions/workflows/ci.yml/badge.svg)](https://github.com/hakanbogan/obelize/actions/workflows/ci.yml)

A library that breaks its API is slow to leave by hand, and a coding agent edits fast but gives no
proof. obelize sits between them:

- It rewrites a place only when it can resolve the call and prove the rewrite with a
  [migration pack](docs/GLOSSARY.md#migration-pack), a file of data: the bundled ones are reviewed
  and cite the library's own guide. Every other place stays as written and is listed with its reason.
- It changes nothing until you pass `--apply`, refuses to write over uncommitted changes, and
  `undo` puts the files back.
- It runs your tests before the change and after it. A run is verified when they passed before and
  still pass after, and `upgrade` compares them test by test.
- It runs on your machine, with no account and no telemetry, and makes no network call unless you
  configure a model yourself or ask it to read a library's releases from the package index or a
  migration guide you name.

## Example

[examples/quickstart/](examples/quickstart/) is a small script on both old libraries, which the two
packs migrate one after the other. `obelize fix` prints this diff for it:

```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -3,22 +3,26 @@
 import os
 import sys

-import google.generativeai as genai
-import PyPDF2
+from google import genai
+from google.genai import types
+import pypdf

-genai.configure(api_key=os.environ["GEMINI_API_KEY"])
-model = genai.GenerativeModel("gemini-2.5-flash", generation_config={"temperature": 0.2})
+client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


 def read(path):
     if path.endswith(".pdf"):
-        return "\n".join(page.extract_text() for page in PyPDF2.PdfReader(path).pages)
+        return "\n".join(page.extract_text() for page in pypdf.PdfReader(path).pages)
     with open(path, encoding="utf-8") as handle:
         return handle.read()


 def summarise(text):
-    response = model.generate_content(f"Summarise this in two sentences:\n\n{text}")
+    response = client.models.generate_content(
+        model="gemini-2.5-flash",
+        contents=f"Summarise this in two sentences:\n\n{text}",
+        config=types.GenerateContentConfig(temperature=0.2),
+    )
     return response.text


diff --git a/requirements.txt b/requirements.txt
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,2 +1,2 @@
-google-generativeai==0.8.6
-PyPDF2==3.0.1
+google-genai>=1.55
+pypdf>=6.19
```

The model object has no counterpart in `google-genai`, so its model name and generation config
move into the call, and each dependency line moves to its new package.

## Install

Run it once, in your project's directory, with [uv](https://docs.astral.sh/uv/):

```bash
uvx obelize scan
```

Or keep it installed, with `uv tool install obelize` or `pipx install --python python3.12 obelize`.
obelize needs Python 3.12 or newer and runs on Linux, macOS and Windows; the project it migrates
needs only what the new library does. [Getting started](docs/GETTING_STARTED.md) has the details.

## Quickstart

In a git repository with everything committed:

```bash
uvx obelize scan
uvx obelize fix
```

`scan` lists each import, call and dependency line of the old libraries that it can resolve, and
whether it can migrate it. `fix` is a dry run until you pass `--apply`: it prints the plan and the
diff, and writes only its own record under `.obelize/`, which git ignores.

To apply the change and have your tests check it, first install the new libraries, here
`google-genai` and `pypdf`, into your project's environment beside the old ones, without changing
a tracked file. Your tests then run once before the change and once after:

```bash
uv pip install --python .venv/bin/python google-genai pypdf
uvx obelize fix --apply --verify ".venv/bin/python -m pytest -q"
git diff
```

The exit code says what is left, and most runs end with a `Next:` line naming the command to run:

| Exit code | Meaning |
|---|---|
| `0` | Everything it found is migrated and your tests passed. |
| `4` | Some places are left for you. `REPORT.md` in the run folder lists each with its reason. |
| `3` | Your tests failed after the change. `obelize undo` puts the files back. |
| `5` | obelize refused to apply over uncommitted changes, or to run a command it does not trust. |
| `6` | The change is written, but your tests gave no verdict. |

[After a run](docs/AFTER_A_RUN.md) explains each code. For `openai`, 0.x and 1.x are one install,
so it takes four steps instead: see [Getting started](docs/GETTING_STARTED.md#openai-0x-to-1x).

## Upgrading a dependency

For a library with no pack, obelize makes one from the public API of two of its releases and tries
the move in a copy of your repository:

```bash
uvx obelize outdated
uvx obelize upgrade pydantic
uvx obelize upgrade pydantic --apply --yes --branch --agent claude_code
```

`outdated` lists what has moved on. `upgrade` is a dry run: it plans the move and prints the diff.
With `--apply --yes` it installs the old and the new release into two environments made with uv,
runs your tests in each, and writes the move only if no test that passed before fails after;
`--branch` commits it to a new branch and leaves your working tree alone. `--agent` puts the places a
pack can only flag, and then the tests the move broke, to your own coding agent one at a time, with
every tool of the agent turned off, and obelize checks each answer before it reaches the copy. The
tests are the check: a weak suite proves little. Where the library keeps its import name (`pydantic`,
`SQLAlchemy`), `upgrade` writes a file at a time: a file that holds a place the pack can only flag is
left as it was and named, the others are written, and the move ends `4` without `--branch`. A pass
then says that the tests that passed before still pass, not that the rest has moved.
[Upgrading a dependency](docs/UPGRADING.md) has the steps and the four runs on three public
repositories, and [Upgrading in CI](docs/UPGRADING_IN_CI.md) runs it as a GitHub Action in one job
and opens the pull request in another.

How far a pack made from two releases gets on real repositories is measured for the dry run, over
80 repositories, and for the trial, over the 5 of them whose plan writes a file. Over 80 public
repositories that use the old API of pydantic 1, SQLAlchemy 1.4, urllib3 1 and pandas 2, the dry run
of `upgrade` with no pack writes a file for 5 and none for the other 75: 32 stop before planning, 32
are held and 11 have no usage of a name the pack lists. It finds 944 usages: 78 are places a rule
would rewrite (all in pydantic, `rename_member`), the pack only flags 810 and 56 are held for a cause
of its own, and 14 are in a file the dry run would write. The trial of the 5 whose plan writes a
file, run in a box that reaches only the package index, passed for 1 (with 20 places left for a
person and 3 tests compared), could not install the dependencies of 3 and got no test result from 1.
That is one repository and not a rate: the sample is drawn by code search of repositories that
import the old API, and a pass means the tests that passed before still pass ([the
numbers](docs/BENCHMARK_RESULTS.md#upgrade-dry-run), [the trial](docs/BENCHMARK_RESULTS.md#upgrade-trial)).
What limits the dry run now is that a pack made from two releases mostly flags: 810 of the 944
usages (85.8%) are places it only flags and never rewrites.

## With a coding agent

An agent migrates more than obelize does, and obelize gives the migration a check. A study of 321
real Python library migrations found that language models got 89 to 94 percent of the individual
code changes right, but only 36 to 64 percent of whole migrations passed the tests that passed in
the developers' own migration ([arXiv 2504.13272](https://arxiv.org/abs/2504.13272)). Let obelize
write what it can prove, give the agent the places it lists, and run `obelize scan` and your tests
until nothing is left. [With a coding agent](docs/WITH_A_CODING_AGENT.md) has the steps, and
[skills/obelize/SKILL.md](skills/obelize/SKILL.md) is the same workflow as a skill file.

## Commands

| Command | What it does |
|---|---|
| `obelize scan` | Lists the imports, calls and dependency lines a migration affects, or with `--library` every use of a library that has no pack, and edits nothing. |
| `obelize fix` | Plans the migration and prints its diff. `--apply` writes it, and `--verify` runs your tests before and after. |
| `obelize verify` | Runs the verification again for an applied run. |
| `obelize undo` | Puts back the files a run wrote, unless they were edited since. |
| `obelize mcp` | Serves obelize to a coding agent over the Model Context Protocol, with tools that take no command and no consent. |
| `obelize outdated` | Lists the dependencies a repository declares that the package index says have moved on, and what can migrate each. |
| `obelize upgrade` | Shows what moving one dependency to a newer release would change, with a bundled pack or one made from the two releases. `--apply` tries the move in a copy and runs your tests before and after. |
| `obelize pack validate` | Checks a migration pack against the [pack format](docs/PACK_SPEC.md). |
| `obelize pack test` | Runs a migration pack over its own fixtures and sources. |
| `obelize pack new` | Makes a migration pack that loads, with fixtures and sources to edit. |
| `obelize pack synth` | Makes a migration pack from the public API of two releases of a library, read from the package index without installing or running anything, and with `--guide` from a migration guide that a model you set up has read and code has checked. |

[docs/CLI.md](docs/CLI.md) has every flag and exit code. The formats, from the flags to the run
folder, may change in any 0.x release, and [CHANGELOG.md](CHANGELOG.md#stability) lists each change.

## Packs

| Pack | Rewrites | Leaves to you |
|---|---|---|
| `gemini/google-generativeai-to-google-genai` | The import, `configure`, the model object and its generation, chat and streaming calls, safety settings, file uploads and the dependency line. | Every tool declaration, since automatic function calling is on by default in `google-genai`. |
| `numpy/numpy-1-to-2` | Twenty-three names NumPy 2 removed, as the name that also exists on NumPy 1 (`np.float_` as `np.float64`, `np.NaN` as `np.nan`, `np.cumproduct` as `np.cumprod`), by your own [ruff](https://docs.astral.sh/ruff/rules/numpy2-deprecation/) (`NPY201`), kept only if it changed no other line, and the dependency line. | Every other name NumPy 2 removed or moved, and what it changes besides names (promotion, the C API). |
| `openai/openai-0-to-1` | Seven calls (`ChatCompletion.create` and six more) to the module client, the reads of their results, `api_base`, three exception classes and the dependency line. | Async and streamed calls, Azure, other resources, and any call whose arguments or result reads it has not checked. |
| `py-pdf/pypdf2-to-pypdf` | The import, the names that exist unchanged on both sides, and the dependency line. | The names `PyPDF2` 3.0.0 removed and the ones `pypdf` dropped. |
| `python/datetime-utcnow` | `datetime.utcnow()` and `utcfromtimestamp(x)`, written as `now(timezone.utc)` and `fromtimestamp(x, timezone.utc)` with the zone dropped again, so the value stays naive. | A reference that is not a call (`default=datetime.utcnow`), and a move to aware values. |
| `setuptools/pkg-resources-to-importlib` | Nothing. Every use of `pkg_resources` is reported with the `importlib.metadata` or `importlib.resources` call that replaces it. | All of it, since none is the same call under another name. |
| `python/removed-stdlib-modules` | `pipes.quote`, as `shlex.quote`. | The rest of the modules Python 3.12 and 3.13 removed, reported with where Python says they went. |

The three packs for the Python name no distribution to install, so nothing in a manifest changes and
a repository that declares a Python they do not run on is left alone. None of them has been measured
on public repositories yet.

Your own packs load from a directory your `~/.config/obelize/config.yml` lists as `pack_dirs`. For a
library that has none, `obelize pack synth` makes one from the public API of two of its releases. A
pack can rename a method of a library's class wherever your code reads it off an instance of a class
you wrote, rewrite a call from the shape of its arguments, or hand a change to a
[plugin](docs/PLUGINS.md) you install and allow ([the pack format](docs/PACK_SPEC.md)).
[Packs](docs/PACKS.md) says what each bundled pack covers, and the [roadmap](docs/ROADMAP.md) says
which migrations come next.

## How it works

```
migration pack -> scan -> plan -> codemod -> patch -> verify -> report
(cites the guide)  every   what    libcst     only     your     what is left,
                   place   it can  rewrites   proven   tests    and why
                   found   prove              edits    twice
```

The codemods are [libcst](https://libcst.readthedocs.io/) transformations, so a rewrite keeps the
formatting and comments of the code around it. A rewrite that cannot be proven is refused, and the
file stays as it was.

## Safety

`scan`, and `fix` without `--apply`, change none of your files. The commands never push or merge,
and `upgrade --apply --branch` makes a branch and a commit only when you ask, without touching your
working tree; only the second job of the [workflow in CI](docs/UPGRADING_IN_CI.md), which you add to
your repository, pushes a branch and opens a pull request. In your repository obelize writes only
its own `.obelize/` folder and the files on its plan, each through a temporary file and a rename,
and it keeps what it reads from the package index in your cache folder. `upgrade --apply` is the one
command that installs packages: it asks first and does it in a copy of the repository, with
environments outside it. A verification command runs only from your own configuration or a flag, or
after you approve it at a prompt. [Safety](docs/SAFETY.md) lists what
is mitigated and what is not, and [the threat model](docs/THREAT_MODEL.md) and
[privacy notes](docs/PRIVACY.md) have the detail.

## Benchmark

Every number comes from [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md), which lists the cases
behind it, and the method is in [docs/BENCHMARK.md](docs/BENCHMARK.md). All of them are for the
Gemini pack: I measured the migration with obelize 0.1.0 and the scan again on a later scanner, with
the same result. The `openai` and `PyPDF2` packs have no accuracy figure; a
[dry run](docs/BENCHMARK_RESULTS.md#fix-dry-run) over 80 repositories each shows how many get a
written plan. The `numpy` pack and the three for the Python have no benchmark, and the dry run of
`upgrade` with no pack, over 80 repositories and, for the trial, 5, is [described
above](#upgrading-a-dependency) and [published](docs/BENCHMARK_RESULTS.md#upgrade-dry-run). `scan`
and `fix` with the bundled packs gave the same output in 0.10.0 as in 0.9.0 on the repositories of
the test suite and the examples, so the records of Gate 1 and of the three fix dry runs are those of
0.9.0 and were not taken again.

| Measure | obelize | n |
|---|---|---|
| Scan precision | 100.0% | 63 usages reported in 5 repositories labelled by hand |
| Scan recall | 98.4% | 64 usages labelled by hand |
| Usages migrated | 25 (9.0%) | 277 usages in 20 public repositories |
| Repositories with a wrong edit | 0 | 20 |
| Repositories migrated and verified by their own tests | 0 | 20, of which 16 have no test command |

The second table puts obelize beside a general-purpose coding agent that was given Google's
migration guide and one fixed prompt.

| Against a coding agent | obelize | The agent | n |
|---|---|---|---|
| Usages migrated | 17 (9.8%) | 154 (88.5%) | 174 usages in 13 of those repositories |
| Repositories with a wrong edit | 0 | 2 | 13 |

The two tools do different jobs. The agent migrated far more of these usages. obelize migrates the
part it can prove, made no wrong edit where the agent made two, and lists the rest with a reason.
The 13 repositories are the ones obelize's rules were written against, and the agent's column is a
snapshot from 2026-09-22 that I have not measured again. I have not measured the two together.

## Documentation

The [documentation site](https://hakanbogan.github.io/obelize/) has everything below, and each page
is a file under [docs/](docs/).

- [Getting started](docs/GETTING_STARTED.md), [After a run](docs/AFTER_A_RUN.md),
  [Upgrading a dependency](docs/UPGRADING.md) and
  [With a coding agent](docs/WITH_A_CODING_AGENT.md).
- [CLI](docs/CLI.md), [Pack format](docs/PACK_SPEC.md), [Run folder](docs/RUN_FOLDER.md) and
  [Glossary](docs/GLOSSARY.md).
- [Limits](docs/LIMITS.md), [Known issues](docs/KNOWN_ISSUES.md), [Roadmap](docs/ROADMAP.md) and
  [Decisions](docs/DECISIONS.md).
- [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
  [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Licensed under the [Apache License 2.0](LICENSE).
