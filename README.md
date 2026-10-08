# obelize

[![PyPI](https://img.shields.io/pypi/v/obelize)](https://pypi.org/project/obelize/)
[![Python](https://img.shields.io/pypi/pyversions/obelize)](https://pypi.org/project/obelize/)
[![Licence](https://img.shields.io/pypi/l/obelize)](https://github.com/hakanbogan/obelize/blob/main/LICENSE)
[![CI](https://github.com/hakanbogan/obelize/actions/workflows/ci.yml/badge.svg)](https://github.com/hakanbogan/obelize/actions/workflows/ci.yml)

obelize migrates Python code off libraries and library versions that are being retired:
`google-generativeai`, the deprecated Gemini SDK, to `google-genai`, `PyPDF2` to `pypdf`, and `openai`
0.28.1 to 1.109.1 or later. Each migration is a pack that ships with it:
`gemini/google-generativeai-to-google-genai`, `openai/openai-0-to-1` and `py-pdf/pypdf2-to-pypdf`.

It finds every legacy call it can resolve, rewrites what it can prove, and leaves the rest with a
reason. It runs on your machine, changes none of your files until you pass `--apply`, and can run
your tests before and after the change. Google has ended support for the old SDK, which now warns
on import that "All support for the `google.generativeai` package has ended", and `PyPDF2` warns
that it "is deprecated. Please move to the `pypdf` library instead." Run with no `--pack`,
obelize runs every pack whose library your repository uses. `--pack` names one or more
instead, and your own packs can sit in a directory your config lists.

## Install

Run it once, in your project's directory, with [uv](https://docs.astral.sh/uv/):

```bash
uvx obelize scan
```

Or keep it installed, with uv or pipx:

```bash
uv tool install obelize
pipx install --python python3.12 obelize
```

obelize is a command-line tool, so install it as one and not into your project's environment. It
needs Python 3.12 or newer, and pipx takes the one `--python` names. The project it migrates
needs the Python its new library does: 3.10 or newer for `google-genai`, 3.9 or newer for `pypdf`,
3.8 or newer for `openai`, where pip picks the newest release that installs. obelize runs on Linux,
macOS and Windows.

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
a tracked file. `uv pip` works whether pip or uv made the environment. Your tests then run once
before the change and once after:

```bash
uv pip install --python .venv/bin/python google-genai pypdf
uvx obelize fix --apply --verify ".venv/bin/python -m pytest -q"
git diff
```

Name your project's own interpreter in `--verify`, so the tests run with its dependencies. On
Windows that is `.venv/Scripts/python.exe`, written with forward slashes, since `--verify` reads a
backslash as an escape. The run ends with a `Next:` line, and after a clean apply that line names
`obelize undo --run <id>`, which puts the files back.

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
+google-genai>=1
+pypdf>=6.19
```

The model object has no counterpart in `google-genai`, so its model name and generation config
move into the call, and each dependency line moves to its new package.

## After a run

`fix --apply` exits with a code that says what is left, and most runs end with a `Next:` line
naming the command to run:

- `0`: everything it found is migrated and your tests passed. Read `git diff`, then commit it or
  undo it.
- `4`: some places are left for you. `.obelize/runs/<id>/REPORT.md` lists each one with its
  [reason](docs/SCAN_VOCABULARY.md#4-bail-codes-editreason). Migrate them by hand with
  [Google's migration guide](https://ai.google.dev/gemini-api/docs/migrate), then run
  `uvx obelize scan` again.
- `3`: your tests failed after the change. `obelize undo --run <id>` puts the files back.
- `5`: obelize refused an apply over uncommitted changes, or a verification command it does not
  trust.
- `6`: the change is written but your tests gave no verdict, as happens without `--verify` or
  when they already failed before the change.

obelize writes a file only when it can migrate all of it, and keeps the old dependency line
until nothing in the repository uses the old SDK. On a real project the usual result is `4`: obelize
migrates the files it can prove, which can be none, and lists the rest in the report. All the codes are in
[docs/CLI.md](docs/CLI.md#exit-codes).

`openai` is the exception to that. Version 0 and version 1 are one install, so `openai/openai-0-to-1`
writes no file while it leaves anything in the repository, and the new pin moves in the run that
migrates all of it.

## Safety

`scan`, and `fix` without `--apply`, change none of your files. obelize never commits, branches,
pushes or merges, and it refuses to apply over uncommitted changes unless you pass `--allow-dirty`,
so `git diff` shows the migration alone. In the repository it writes only its own `.obelize/` folder
and the files on its plan. Each file on the plan goes through a temporary file and a rename, and it
follows no symbolic link.
It runs the verification commands you pass with `--verify` or allow in your own configuration. A
command from the repository's `.obelize.yml` runs only once you approve it at a prompt, and in CI
only if your allowlist holds it or you pass `--trust-repo-config`. A command that runs past your
timeout is stopped, and its output is redacted before it is recorded. There is no telemetry, and no
network access unless you configure a model in your own `~/.config/obelize/config.yml` or with
`--model`.

Run obelize in a repository that is committed or backed up, and pass only verification commands
you trust. These gaps are known in 0.1.0:

- A git command obelize runs can start a program that the repository's git configuration names,
  such as `core.fsmonitor`, and on Windows it can load a DLL from the repository that git finds
  neither beside itself nor in the system directories.
- Running `obelize verify` again on a run, or `obelize undo` twice, can overwrite the record of
  the earlier attempt.
- Redaction misses common credential shapes, the recorded command line is not redacted, and a
  key can reach a traceback. obelize reads a command's output as UTF-8, so a secret that a
  Windows program writes as UTF-16, or with non-ASCII characters in an older code page, is not
  redacted. Read a run folder before you share it.
- On Linux and macOS, Ctrl-C leaves the verification command's processes running, and a child
  process that ignores `SIGTERM` or has closed its output can outlive the command. On Windows
  the command runs in a job object that ends with it, but a process that WMI, Task Scheduler or
  `docker` starts on its behalf is outside the job and outlives it.

[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) has the details, and
[docs/PRIVACY.md](docs/PRIVACY.md) lists what a run folder holds.

## Commands

| Command | What it does |
|---|---|
| `obelize scan` | Lists the imports, calls and dependency lines the migration affects, and edits nothing. |
| `obelize fix` | Plans the migration and prints its diff. `--apply` writes it, and `--verify` runs your tests before and after. |
| `obelize verify` | Runs the verification again for an applied run. |
| `obelize undo` | Puts back the files a run wrote, unless they were edited since. |
| `obelize pack validate` | Checks a migration pack against the [pack format](docs/PACK_SPEC.md). |

`scan` and `fix` run every pack your repository uses, or the ones `--pack` names. The Gemini pack,
`gemini/google-generativeai-to-google-genai`, declares the 16 changes the migration makes and 20
limitations. The limitations say what it reports instead of rewriting, such as every tool
declaration, because automatic function calling is on by default in `google-genai`; what it cannot
find; and what it rewrites without having checked it against a live API call. `scan` and `fix` print
what a pack says about each surface it flags, and `REPORT.md` lists the limitations of every pack
that ran. [docs/CLI.md](docs/CLI.md) has every flag and exit code. Every format, from the flags to
the run folder, may change in any 0.x release, and [CHANGELOG.md](CHANGELOG.md#stability) lists each
change.

## Packs

| Pack | Rewrites | Reports and leaves to you |
|---|---|---|
| `gemini/google-generativeai-to-google-genai` | The import, `configure`, the model object and its generation, chat and streaming calls, safety settings, file uploads and the dependency line. | Every tool declaration, since automatic function calling is on by default in `google-genai`. |
| `openai/openai-0-to-1` | `openai.ChatCompletion.create`, `Completion.create` and `Embedding.create`, to the same calls on the module client (`openai.chat.completions.create`), the reads of their results by string keys, and the dependency line. | Async and streamed calls, Azure, the other resources, the module settings the new releases ignore, the exception classes, and any call whose arguments or reads of its result it has not checked. |
| `py-pdf/pypdf2-to-pypdf` | The import, the names that exist unchanged on both sides, and the dependency line. | The camelCase classes PyPDF2 3.0.0 removed and the names pypdf dropped. |

The `openai` pack builds no client object, so `openai.api_key` and `openai.organization` keep their
meaning. A 0.28.1 result is a dictionary and a new one is not, so it rewrites a call only when every
read of the result is a path it has checked, `response.choices[0].message.content` or the same path
as keys (`response["choices"][0]["message"]["content"]`, which it rewrites to the attribute form). A
call whose result is read with `.get`, looped over or passed on is left to you. It writes nothing
while any place is left. The other two
packs write each file they can migrate whole and leave the rest.

## Testing

Each case under [tests/fixtures/scan/](tests/fixtures/scan/) has an answer key written by hand that
grades every usage: migrated, or left and why. The first five were written before the scanner
existed. The suite reproduces every key, and each rewritten file matches its expected file byte for
byte. [tests/fixtures/scan/COVERAGE.md](tests/fixtures/scan/COVERAGE.md) lists 36 gaps the fixtures
do not cover, 18 of them closed. CI runs the suite on Linux for every supported Python and on macOS
and Windows for the oldest and newest, and holds each system to 100% branch coverage of the code it
runs.

## Benchmark

Each number comes from [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md), which lists every
case behind it. The method is in [docs/BENCHMARK.md](docs/BENCHMARK.md). Every number is for the
Gemini pack; `openai/openai-0-to-1` and `py-pdf/pypdf2-to-pypdf` have not been measured.

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

The 13 repositories are the ones obelize's rules were written against, and the agent's column is a
snapshot from 2026-09-22 that I did not measure again for 0.1.0. The agent migrated far more, so I
do not claim obelize is more accurate. Each change obelize makes was measured against both SDKs
installed side by side, and each place it leaves has a written reason.

## Limits

- It keeps model names as they are. Google has retired the `gemini-1.5` models, so change a name
  such as `gemini-1.5-flash` yourself.
- It finds notebooks (`.ipynb`) that use the old SDK but does not migrate them, and while one
  does, the old dependency line stays.
- It does not find every use. Code that reaches the SDK through a function's return value, a star
  import in another file or a container is missed, and the benchmark counts those misses.
- On Windows, the test suite on GitHub's runner is all that has run. A real console, a OneDrive
  folder and a path longer than 260 characters are untried.
- It handles the migrations its bundled packs describe. There is no pack registry, hosted service, dashboard, GitHub App
  or automatic pull request.
- For `openai` it rewrites three calls and no other. A repository that uses the module in a way the pack lists is left
  as it was, with each place in the report; [KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md#the-openai-pack)
  says which ways it does not see.

## Documents

- [docs/CLI.md](docs/CLI.md): commands, flags and exit codes.
- [docs/RUN_FOLDER.md](docs/RUN_FOLDER.md): what a run writes under `.obelize/`.
- [docs/PACK_SPEC.md](docs/PACK_SPEC.md): the migration pack format.
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) and [docs/PRIVACY.md](docs/PRIVACY.md): what can
  go wrong, and what leaves your machine.
- [docs/BENCHMARK.md](docs/BENCHMARK.md) and
  [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md): the method and the results.
- [docs/DECISIONS.md](docs/DECISIONS.md): the design decisions and their reasons.
- [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
  [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Licensed under the [Apache License 2.0](LICENSE).
