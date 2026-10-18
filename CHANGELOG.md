# Changelog

Notable changes per release, in [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
format. Versions are `0.MINOR.PATCH`.

## Stability

Every format obelize reads or writes is unstable through 0.x: the CLI surface, the exit codes,
`.obelize.yml`, migration packs, the run folder and its JSON Schemas. None of them carries a
format version, so a 0.x release can change any of them, and this file lists each format change
in the release that makes it.

## [Unreleased]

### Added

- `obelize scan --sarif` prints the findings as SARIF 2.1.0, which GitHub code scanning reads.
- `obelize scan --fail-on <status>` exits `4` when a finding has the status you name (`eligible`,
  `needs_review` or `unsupported`), and the run's `exit_code` records it.
- `obelize verify --json` and `obelize undo --json` print the `run.json` and `undo.json` they wrote.
- `obelize scan --library <distribution>` lists every place a repository uses a library that has
  no pack, with `--module` to name the modules when the library is imported under another name.
  Each place is `needs_review` with the new reason `no_pack_for_usage` and nothing is rewritten. The
  run records `source: inventory` in `packs[]` and holds no copy of a pack.
- `obelize pack new <id> --from "<requirement>" --to "<requirement>" --guide <url>` makes a pack
  that loads, with fixtures and sources to edit.
- `obelize pack test <id|path>` runs a pack over its own fixtures and sources: the checks the three
  bundled packs pass in the test suite, now available for a pack of your own.
- `obelize verify --current` runs a run's verification on the tree as it stands instead of
  answering `tree_changed`, and records the files that differ from what the run wrote in
  `verify.edited` (a new field of `run.json`, empty for any other verification). A run that wrote no
  file can be checked this way, so someone else's migration can be verified.
- `obelize mcp` serves obelize to a coding agent over the Model Context Protocol, on standard input
  and output and with no new dependency. Seven tools (`obelize_scan`, `obelize_plan`,
  `obelize_apply`, `obelize_residue`, `obelize_verify`, `obelize_report`, `obelize_undo`) run the
  commands and return what they print; `obelize_residue` lists the places obelize could not migrate
  with the code around each. No tool takes a command, a path, a model or a consent, and `--read-only`
  leaves out the two that write files.
- `action.yml` is a GitHub Action that runs a scan, annotates each place on its file and line,
  uploads the findings to code scanning if asked and fails the job on the statuses you name.
  `.pre-commit-hooks.yaml` offers the same scan as the hook `obelize-scan`.
- `obelize pack synth <distribution> --from <version>` makes a pack for a library that has none. It
  asks the package index for two releases and the last one between them, opens each for its source
  and nothing else, reads what each exports without importing or building anything, and writes a
  pack: a name the library's deprecation message says to replace is renamed, a name moved up out of
  a submodule is moved, everything else that changed is flagged with the library's own words, and
  the dependency line moves. The pack must pass `pack test` or it is not kept. Every host is printed
  before it is contacted, answers are cached for you alone, and `--offline` uses only the cache.
- `obelize outdated` lists the dependencies a repository declares that the package index says have
  moved on: the release in use, the newest, the size of the gap, whether the library marks itself
  inactive, the release was withdrawn or has an advisory, and what can migrate it (a bundled pack,
  or two releases to compare). `--json` prints the rows, described by the new `outdated.schema.json`.
- `obelize upgrade <distribution> --apply --yes` tries the move before it writes it: in a copy of the
  repository and two environments made with uv (the release in use, and the release moved to), it
  runs the repository's own tests before and after the migration, compares them test by test and
  runs the ones that broke once more. The move is written only if no test that passed now fails; the
  evidence is `.obelize/trials/<id>/`. It asks first, refuses a tree with uncommitted changes, and
  exits `3` for tests that broke and `6` for a trial that could not judge. `--branch` commits a
  passed move to a new branch instead of the working tree, with git's plumbing: no checkout, no hook,
  no signature, no push.
- `obelize upgrade <distribution> --apply --branch --agent claude_code` puts the places a pack only
  flags to your own `claude` program as a text-only model (every tool, session, MCP server, skill and
  setting of yours off, a fixed list of environment variables), checks each answer with the guard,
  writes it to the trial's copy, lets the rules write the rest and your tests judge. It needs
  `--branch`, so nothing a model helped write reaches your working tree; the commit message names the
  files it edited. `agent.backend` and `agent.model` in your own configuration do the same, and a
  repository's `.obelize.yml` may not set `agent`. Tests that passed before the move and fail after it
  are put to the agent too, with the error and the line of non-test code the traceback points at, for
  up to `--max-rounds` rounds (3); a test file is never edited. A place the pack flags is sent with
  the new names closest to the removed one, which `pack synth` keeps in `hints.json` beside the
  pack, and the dependency line follows the places the agent moved. A dependency line the rules
  cannot write is named in the summary and the commit message.
- `obelize upgrade <distribution>` shows what moving one dependency to a newer release would change:
  it uses the pack that migrates it, or makes one from the two releases and keeps it, then plans the
  migration as `fix` does without `--apply`. It writes nothing in the repository.
- `~/.config/obelize/config.yml` takes `network.index` and `network.offline`, and the environment
  `OBELIZE_INDEX_URL`, `OBELIZE_INDEX_AUTHORIZATION` and `OBELIZE_OFFLINE` do the same for one run.
  A repository's `.obelize.yml` may not set `network`: it is refused, as `model` is.
- `source.type` of a pack may be `api_diff`, the type of a pack made by `pack synth`. A bundled pack
  never is.
- griffelib is the seventh runtime dependency. It reads a release's API in a child process and is
  loaded by no other command.

### Changed

- A `rename_symbol` change may carry `renamed`, a name that stays in its module and takes
  another spelling, and `calls: allowed`, which lets a call of a renamed name be rewritten. The
  defaults leave every pack as it was, and the pack schema, `docs/PACK_SPEC.md` and the negative
  corpus describe the new fields.
- `obelize undo` skips a recorded path in `.git/` or `.obelize/` as `outside_root`: a run never
  writes either, so a run folder that names one was forged.
- A scan that finds no pack to apply names the libraries the repository imports most and the
  command that lists one.
- A pack made by `pack synth` no longer flags a function because one of its parameters is
  deprecated, or because a parameter's default became a sentinel such as `_Unset`: the library
  decides the value elsewhere, which a name cannot show. A trial that could not compare any test
  prints no counts, and names the dependency declaration that stopped the rules.
- The guard lets a replacement name `classmethod`, `staticmethod`, `property`, `super` and `object`.
- A model's or agent's proposal may carry `imports`, up to four plain `import` or `from ... import`
  statements of the pack's target modules. The guard adds them at module level, to the file's own
  `from m import ...` line when it has one, and refuses one that is not an import of a target or
  that would change a line the proposal replaces. A file's places are asked about from the bottom,
  each where the earlier answers left it, and the import of a name is covered once every place that
  uses it moved, so a rename that needs a new import is no longer out of reach.
- In a trial of a library that has one release for both APIs, a place left in a file the agent
  moved no longer holds the dependency line: the import of a name whose uses all moved is covered,
  and the places that remain in a file the agent edited were looked at. A test that fails because
  its module would not import is put to the agent with the line pytest points at.

## [0.6.1] - 2026-10-18

This release changes words and metadata and none of the behaviour. No format changed.

### Benchmark

I did not run the benchmark again. Every number is 0.6.0's.

### Changed

- The PyPI description now reads "Verified codemods for breaking Python dependency upgrades", and
  the project's keywords add `refactoring`, `breaking-changes`, `api-migration` and
  `static-analysis`. `obelize --help` opens with the same line.
- The README is shorter and opens with what obelize does and why a run can be trusted. The details
  moved to pages of their own: Getting started, After a run, With a coding agent, Packs, Safety,
  Limits and Testing, and a Glossary names the terms.
- The product page and the roadmap say that obelize is a tool for verified dependency upgrades, and
  list what I intend to build next as planned. Nothing on that list ships in this release.
- Reader pages no longer name a decision or threat number in their text. The links to the
  decisions stay.

### Added

- A documentation site at <https://hakanbogan.github.io/obelize/>, built from `docs/` with
  MkDocs. ci builds it strictly on every push, and a `v*` tag publishes it. The project's
  Documentation link on PyPI points there.

## [0.6.0] - 2026-10-18

### Benchmark

I did not run the benchmark again for this version. Round 1's numbers are still 0.1.0's and are for
the Gemini pack alone: 25 of 277 usages (9.0%) migrated in 20 repositories with no wrong edit. The
scan record of gate 1 and the three `fix` dry runs were measured again against the packs and the
engine of this version, and they read `obelize 0.6.0`. Each pack's record is bound to the sha of
the pack it was taken with, so a changed pack fails a test until it is measured again.

- Gate 1: scan precision is 100.0% and recall 98.4% over the same 64 usages in five repositories, and
  the zero-bail share is the 0.1.0 record's 57 of 80 repositories (71.2%). The record was taken
  again with `obelize scan --pack` (the harness now names the pack, since a scan without it runs
  every pack a repository uses).
- `openai/openai-0-to-1`: complete 12 to 27, blocked 41 to 27 and held 27 to 26. Nine repositories
  moved from blocked to complete, six from held to complete and six from blocked to held, and one
  moved from held to blocked on a Python floor that is now read.
- `py-pdf/pypdf2-to-pypdf`: complete 31 to 32, blocked 35 to 36, partial 6 to 5 and held 6 to 5.
  Two repositories moved from blocked to complete because a `requirement.txt` is now read. Three
  moved to blocked: a `pypdf` pin that admits nothing the pack writes (twice) and a Python floor read
  from `setup.py` (once).
- `gemini/google-generativeai-to-google-genai`: complete 35 to 27, held 32 to 40, partial 13 to 12
  and blocked 0 to 1. Eight repositories moved from complete to held and one from partial to held,
  because a read of `response.text` inside a bare, `Exception`, `BaseException` or `ValueError`
  handler is now refused, which is the price of failing closed. One moved from held to blocked on a
  Python floor read from a `Pipfile` or `setup.py`.

These are plans that wrote something, not accuracy: there is no answer key for these frames, and
"complete" means a file written and nothing withheld, not a correct migration. The dry-run records
also keep the declaration a blocked pack stopped at. The benchmark scripts are a package now and run
as `python -m bench.<name>`.

### Unsupported patterns

[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) lists what I know about and have chosen not to fix yet,
and most of what 0.5.0 listed is gone from it. What it names now:

- A file nested more than 300 levels deep is refused as one that does not parse, and a few hundred
  parts of an implicit string concatenation, which that count does not see, fail through libcst's
  own limit. The codemod's stack use per level is not measured.
- `openai`: a result bound to a module-level name is checked against the modules that name `openai`,
  so a module that imports it and never says so goes unseen. A requirement with extras, a hash, a
  continued line or a URL holds the repository until you edit it, and the old pin in a form the
  reader does not open (an `-r` of a file with another name, a Dockerfile, `tox.ini`) stays with no
  row. A notebook that calls the old API holds the pin until you migrate it by hand.
- `PyPDF2`: a requirement obelize cannot rewrite in place (extras, a hash, a continued line) leaves
  the manifest on `PyPDF2` while the code moves to `pypdf`. Releases 1.x and 2.x are flagged and
  never migrated. Installer settings outside the repository (a `pip.conf`, `PIP_*` variables) are
  not read, on purpose, so that a finding is the same on every machine.
- A model endpoint that drips the headers or the chunk sizes of a reply is held back only by the
  socket timeout of each read.

The formats that changed are `pack.yaml` (`from.since`, `to.introduces`, `manifest_dependency`'s
`declare_transitive`, `rewrite_call`'s `value_maps`, `literal_prefixes` and `warnings_unless`,
`flag_only`'s `variables` and the `rename_symbol` kind), the model proposal (`replaces`), the user
config (`model.allow_insecure_http`), `findings.json` and `run.json` (the bails `internal_error` and
`new_version_unsupported`, the limitation code `internal_error`, the warnings
`response_text_may_be_none` and `upload_display_name_unset`, the guard refusal
`replaced_text_differs`), the dry-run and round records (new provenance fields), and the JSON
Schemas, which now carry the patterns of the values the models check.

### Added

- A model proposal must quote the lines it replaces (`replaces`), and the guard refuses one whose
  quote is not the text of those lines as sent (`replaced_text_differs`); a reply without it is
  unanswered as `proposal_does_not_hold`. The code sent to a model carries each line's number in the
  file (`12: code`), added after redaction, and the prompt says the numbers are not code.
- `model.allow_insecure_http`: a plain `http://` model `base_url` to a host other than `localhost`,
  `127.0.0.0/8` or `::1` is refused unless it is `true`.
- An unexpected error on one file no longer ends a run. A scan reports the file as one `parse_error`,
  and `fix` leaves it as it was and withholds its rows as the new bail `internal_error`;
  `run.json`'s `limitations` names the exception's class and never its message.
- A manifest that pins the new distribution so that it admits no release the pack writes
  (`pypdf==3.0.0`, `pypdf<6`) blocks the run as `new_version_unsupported` and names the path.
- `pack validate` refuses a pack whose two `flag_only` changes name one surface, naming both.
- After a manifest pin is written, the summary and `REPORT.md` name the lock files to regenerate,
  and the fix summary says what to change for each reason a finding was left (also in
  `REPORT.md` and `SCAN_VOCABULARY.md`).
- A file that uses the legacy API and that no rule writes (a notebook, with the cells that call it,
  or a stub) is named in the terminal summary and under Limitations in `REPORT.md`, also where the
  pin has already moved and the run used to say "No pack applies".
- Warnings on a rewritten Gemini call: `response_text_may_be_none` where the result's `.text` is
  read (it is `None` now where it raised `ValueError`), and `upload_display_name_unset` on a
  rewritten `upload_file` that leaves out `display_name`, whose old call named the file after its
  path.
- Benchmark rounds resolve every install as of the round's start (`UV_EXCLUDE_NEWER`, repeatable
  with `--exclude-newer`) and record uv's version, that cutoff and a hash of the installed set in
  each case's provenance. Results also record `forbidden_reported`, the findings at a position the
  answer key forbids, and `bench/CASES.md` prints how many of the 38 forbidden positions the scan
  reported.

### Changed

- A file that an `-r` or `-c` line names is read whatever its name (inside the repository, eight
  includes deep, never written): a legacy pin in it holds the pack with one distribution for both
  APIs, and the newest-release check no longer stops at the include alone.
- A `.py` file that the scan cannot read (over `max_file_bytes`, or unopenable) holds the pin of a
  pack with one distribution for both APIs (`openai`), and its limitation says so; raise
  `max_file_bytes` or list the file under `exclude`. A file over 32 MiB that the newest-release
  search skipped is named as a limitation.
- The `model:` block of the user config and a pack's `retrieved_at` refuse a value of another type
  instead of converting it (`log_prompts: 'yes'`, a quoted date).

- The code of a model reply that `compile()` refuses is `output_does_not_compile`, and
  `output_does_not_parse` is for a result `compile()` accepted and libcst cannot read. A reply
  nested deeply enough to crash libcst's parser is refused before libcst sees it, and a statement
  over 500 tokens in a replacement is refused as `replacement_too_large`.
- A model `base_url` with a query string or fragment is refused, with a message that sends the key to
  `api_key_env`; the failure detail of an unreachable endpoint names the host and port, not the URL.
- A file nested more than 300 levels deep (a long chain of operands, attributes or calls, a dotted
  name, an `elif` ladder, about a hundred brackets inside brackets) is refused as one that does not
  parse, the same on every `--jobs` and every Python. On Python 3.14 a chain of about thirteen
  thousand terms killed the scan with a segmentation fault.
- A configuration or pack file over 1 MiB is refused unread, with the limit in the message. A YAML
  set (`!!set`) in `.obelize.yml` or a pack is refused with a line and column, where it was read in
  hash order.
- `.obelize.yml`, the user's `pack_dirs` and `verify.allow`, and a pack's `layout.line_length`,
  `match.shared` and `coroutine` refuse a number, flag or string of the wrong type
  (`allow_dirty: 'yes'`, `max_file_bytes: '1000'`) instead of coercing it, so a config that loaded
  by luck is refused.
- The published JSON Schemas carry the regular expression of every digest, run id, instant, pack id,
  version and symbol the models check, and the length limits of display text; a pack's
  `pack_version` no longer accepts a digit of another script.
- The `fixtures/` directory beside a pack of your own that sits inside the repository is left out of
  a scan, not the whole directory the pack file is in: a helper beside `pack.yaml` that imports the
  legacy API is scanned and holds the pin. `REPORT.md` says `Not scanned` and names the directory,
  and `scan --list-files` leaves it out.
- The `Next: regenerate each lock file` line names only the lock files in the written manifest's
  directory or above it. The `--jobs` help says that Windows takes at most 61 workers.
- A dependency file is read the way pip reads it: a line ending in a backslash joins the next,
  options after a requirement (`--hash`, `--config-settings`) are cut, and a hash-pinned, continued
  or editable requirement or a local wheel keeps its name and gets no pin edit
  (`manifest_pin_shape_unsupported`) instead of being missed.
- A `dev-requirements.txt`, `requirement.txt` or any other `*requirement*.txt` is a manifest and is
  rewritten like `requirements.txt`. A `requirements.in` and a constraints file are read for their
  declarations and never written, so a legacy pin in one is `manifest_pin_shape_unsupported` where
  it stayed with no row. The arrays uv, PDM and Hatch keep requirements in are read and rewritten
  like PEP 621's, and a Poetry dependency given as its own table is read and refused.
- A Poetry or Pipfile inline table that holds only a version (`openai = {version = "0.28.1"}`) is
  rewritten inside its quotes. A `setup.py` that assigns its requirements to a list or tuple first
  (`REQS = [...]`, `setup(install_requires=REQS)`) is read, and the pin is rewritten where the list is
  assigned.
- The Python gate reads a `Pipfile`'s `[requires]` and a string `python_requires=` in `setup.py`,
  so a repository that builds on a Python below the pack's floor there is blocked as
  `runtime_unsupported`. A Pipfile that is not TOML 1.0 is reported as an unread manifest.
- A module only the legacy distribution installed (`requests`, `aiohttp`) counts as declared for a
  file only where a manifest in its directory or above it declares it, so one app's declaration no
  longer covers another app in a monorepo.
- A notebook that names the library is read as code, its cells in order, and holds the pin only where
  a cell calls the legacy API, with the cell numbered, where it held the pin whether or not it did.
  A notebook is still never written.
- A read of `response.text` inside a `try`, `except*` or `contextlib.suppress` whose handler is bare,
  `Exception`, `BaseException` or `ValueError` is refused as `response_shape_changed`, and the read
  of an awaited call's result is judged like a sync one.
- A `legacy_version_unsupported` block says that a pin moves the release and not the code, so a call
  to a name the pinned release removed has to be ported first; it no longer reads as advice to move
  `PyPDF2` code written for a release below 3 to `>=3` as it stands.
- A block of an unversioned `PyPDF2` in a directory that is not the top of a git repository says that
  obelize lists every file only at the top of a git repository, and to run it there or pin.
- For `PyPDF2`, a `dev-requirements.txt`, `requirements.in` or constraints file no longer stops the
  run for being there; each is read like a manifest, so only one that names another release
  (`PyPDF2<3`), a bare `PyPDF2` or an option that moves the index does. A name in `[tool.isort]`, a
  Ruff or mypy list, a project description or a URL no longer counts as an unread declaration. A
  listed file over `max_file_bytes` is searched in 1 MiB windows up to 32 MiB, an ignored `.venv`,
  `venv` or `env` stops the inference beside any listed file, and the pip options of a manifest the
  user's `exclude` removed are judged.
- The benchmark harness runs each case's installs and test suites with an allowlisted environment
  (`PATH`, the locale, `TMPDIR`, the uv and pip cache and interpreter directories) and a home
  directory of its own, in a session whose process group is killed when the step ends. A round
  records the commit and tree state it started on (`obelize_tree_dirty`) and refuses to start on a
  dirty tree, outside a git checkout, or when `obelize` is imported from elsewhere than the
  checkout. The comparison arm's installs and suites get the same environment and cutoff.
- The bundled legacy example application defaults to `gemini-2.5-flash`, the model the README and
  `examples/quickstart` use, instead of the retired `gemini-1.5-flash` and `gemini-1.0-pro`.
  CI installs a pinned uv and numpy, runs `pre-commit` over every file, and runs ruff from the
  project environment; the hook repository is held to a commit, not a tag.
- `obelize.models` is a package of six modules, with no import path or JSON Schema changed
  ([ADR-058](docs/adr/ADR-058-models-by-section.md)).

### Fixed

- A model reply of one very long `or`, `and` or (from Python 3.14) `+` chain no longer kills
  `obelize fix` with a segmentation fault; a reply nested deeply enough for the guard's tree walks,
  deeply nested JSON and a lone surrogate no longer end the run with a traceback, and neither does a
  120 KB body of brackets on Python 3.15. A model that quotes the lines it replaces as newline-joined
  text is no longer refused when the range ends in a blank line.
- The model request's 120-second limit bounds the whole reply body, not each read of it, so a reply
  dripped a byte at a time is `endpoint_unreachable`. A 4xx or 5xx reply whose body stalls or resets
  is `endpoint_refused` with the status, not a traceback.
- Asking a model about several rows of one file parsed the file once per row (about 135 ms each on a
  2,800-line file); it is parsed once now.
- An impossible date, an over-long integer, a deeply nested document or an explicit tag on a value it
  cannot read (`!!bool maybe`) in `.obelize.yml`, a pack or `~/.config/obelize/config.yml` ends in a
  refusal with a line and column where there is one, not a traceback. A non-UTF-8 user config, or a
  deeply nested config or `approved.json`, is a refusal, and the approvals store fails closed.
- A YAML merge key (`<<`) failed with "could not determine a constructor for the tag merge"; merge
  keys work in `.obelize.yml` and packs, and a duplicate key is found without constructing it twice.
- `obelize undo` reads no configuration, so an invalid `.obelize.yml` no longer stops it.
- An apply refused over a file only a model proposed runs no baseline command first.
- The hint after a baseline that failed in obelize's own environment shows `.venv/Scripts/python.exe`
  on Windows, and the refusal of a command that needs a shell advises `cmd /c` there.
- The packs the wheel carries no longer add a `Not scanned` line to `REPORT.md` when obelize is
  installed inside the scanned repository.
- A `pyproject.toml` or `Pipfile` nested too deep for `tomllib` no longer aborts the scan with a
  `RecursionError`; it is reported as `input_does_not_parse`.
- A constraints file no longer counts as a declaration of a module's distribution, which let
  `fix --apply` drop the legacy pin while a file still imported what only that pin installed.
- The syntax check on a file no longer applies obelize's own `from __future__ import annotations`,
  so a walrus in an annotation is not refused as unparsable on Python 3.12 and 3.13.
- A requirement line PEP 508 refuses (`PyPDF2~=1`, `PyPDF2==1.*.*`, a `setup.cfg` line with a
  trailing comment) is a row for its name with no version, so the version gate can no longer pass over
  it. A local build of the legacy release (`PyPDF2==3.0.1+corp`) no longer reads as the release.
- A rewritten call inside a multi-line bracket is laid out at the indent of the line it starts on, a
  Gemini call written in an f-string field stays on one line, and a call in an f-string field written
  with `=` is refused as `response_shape_changed` instead of rewritten.
- A comment written inside a call the codemod replaces (between its arguments, after its opening
  parenthesis, in the dotted callee) is kept, beside its argument where one remains and on a line
  above the statement otherwise. A comment on a deleted `GenerativeModel(...)` statement, or between
  its arguments, moves to the next statement, and onward when that is deleted too, and a comment
  between the brackets of a rewritten string-key read moves to a line above its statement.
- A combined import such as `import types, google.generativeai as genai` no longer lets the rewrite
  take the name `types` for `from google.genai import types`; the submodule is bound as
  `genai_types`.
- `embed_content`'s literal `task_type` is written as the UPPER_SNAKE name the service reads, and a
  name, integer, enum member or unknown string is refused as `unsupported_kwarg`. A mapping
  `system_instruction` with string parts or a `system` role, which raises a `ValidationError` in
  `GenerateContentConfig`, is refused as `history_parts_shape_incompatible`.
- A call on a client built with `genai.Client()` in a file that also builds a legacy model is no
  longer reported as `receiver_unresolved`, which withheld every other row of the file.
- The benchmark harness no longer records a finished command as a timeout when a background process
  it started still holds its output. A round is refused when obelize is imported from anywhere but
  the checkout's `src/`, and `--exclude-newer` refuses a time that is not written digit for digit
  (`2026-10-15T09:00:00Z`), which uv would refuse after the round had started.

### Packs

- `openai/openai-0-to-1` 0.3.1 and `py-pdf/pypdf2-to-pypdf` 0.4.1 stop printing limitations the scan
  contradicts: a notebook holds the pin only where a cell calls the legacy API, a pin-less `openai`
  beside `ChatCompletion` or `Audio` code is taken, a Python in `setup.py` or a `Pipfile` is read,
  and every requirement shape the pack cannot rewrite leaves its manifest line.

- `openai/openai-0-to-1` 0.3.0:
  - A declaration with no lower bound (`openai`, `openai<1`, `openai>=0.20`) beside a call of
    `openai.ChatCompletion` or `openai.Audio` is taken as a release in `>=0.27.0,<1`, the only range
    that can run them, and migrated where it stopped the run as `legacy_version_unsupported`. The run
    says what it took, and a lock, a constraint or a version written elsewhere that rules the range
    out still stops it (pack field `from.since`).
  - A pin that admits only 0.x (`openai==0.28.1`, `openai<1`) beside code that uses `openai.OpenAI`,
    `AsyncOpenAI` or `AzureOpenAI` is a `manifest_code_mismatch` row for review, where the run said
    "No pack applies" (pack field `to.introduces`).
  - A module that 0.28.1 installed (`requests`, `aiohttp`, `tqdm`) which an app imports and no
    manifest of the app declares is declared by name, with no version, below the `openai` requirement
    of a requirements file as the pin moves, where the run held the pin as
    `transitive_dependency_in_use` (pack parameter `declare_transitive`).
  - `openai.error.RateLimitError`, `PermissionError` and `Timeout` are rewritten as
    `openai.RateLimitError`, `PermissionDeniedError` and `APITimeoutError`, in references and in
    `import openai.error` and `from openai.error import X`, by a new `rename_symbol` rule kind
    ([ADR-057](docs/adr/ADR-057-rename-symbol.md)); the other `openai.error` classes stay reported,
    each with a message that says what it became.
  - `engine=` and `request_timeout=` of a chat, completion or embedding call are carried as `model=`
    and `timeout=`, where they were refused.
  - A one-argument `.get("key")` of a result is rewritten to `getattr(result, "key", None)` instead of
    withholding the repository.
  - A key read inside a handler for an imported class, which may subclass `KeyError`, is no longer
    rewritten, and a result bound to a module-level name that another module imports or reads off the
    module is withheld.
  - `Image.create` is refused when the model is written out as one that is no `dall-e`, since
    `gpt-image-1` returns no url.
  - The pack reports a write of `OPENAI_API_BASE` or `OPENAI_ORGANIZATION` in code, which the new
    releases do not read (`flag_only.variables` and the `environment_write` shape); a patch target
    written under your own package, `patch.object(myapp.llm.openai, "Leaf")` and a dict literal keyed
    by `openai` handed to `patch.dict(sys.modules, ...)` or `sys.modules.update`; a legacy name inside
    a quoted annotation; and a read of `http_status`, `json_body` or `user_message` off the name of an
    `except openai.APIError` or `openai.OpenAIError` handler.
- `py-pdf/pypdf2-to-pypdf` 0.4.0 names `PyPDF2.pdf`, `PyPDF2.utils` and `PyPDF2.merger`, the modules
  only PyPDF2 1 ships, in `from.lacks`, and reports them. A name the newest release lacks, written
  in a notebook, a Python 2 file, a stub, excluded code or prose, counts as evidence of an older
  release as the same name in a parsed file already did. The suggestion for `PdfFileReader`,
  `PdfFileWriter` and `PdfFileMerger` names what their members become and the renames that are wrong
  by name alone (`rotateCounterClockwise`, the fourth positional of `merge*Page`, `removeImages`,
  `removeText`); no method is rewritten.
- `gemini/google-generativeai-to-google-genai` 0.4.0 carries the two warnings, the `task_type` table
  (`value_maps`) and the `system_instruction` refusal above. A call that passes `display_name` has
  nothing to be told about it (`warnings_unless`), and the limitation about a bare `configure()` says
  it is rewritten to `Client()` with one warning about the key being checked at construction.

## [0.5.0] - 2026-10-15

### Benchmark

I did not run the benchmark again for this release. Its numbers are still 0.1.0's and are for the
Gemini pack alone: scan precision 100.0% and recall 98.4% over 64 usages in five repositories, and
25 of 277 usages (9.0%) migrated in 20 repositories with no wrong edit, on the
[results page](https://github.com/hakanbogan/obelize/blob/v0.5.0/docs/BENCHMARK_RESULTS.md). The
scanner and the rewriter have changed since, so read those numbers as dated. The new gate rule is
measured without the tests: a `fix` dry run with no model over the 80-repository frame of each pack
plans for openai and Gemini what 0.4.0 planned, and for `py-pdf/pypdf2-to-pypdf` plans for 19 of the
53 repositories the version gate stopped: 15 complete, 3 partial and 1 held, so 31 of 80 repositories
plan completely against 16 (the other 34 that the gate stops still stop, and one stops on a Python).
That says what is written, not whether the result passes a repository's tests, and "complete" means
a file written and nothing withheld, not a correct migration. `openai/openai-0-to-1` and
`py-pdf/pypdf2-to-pypdf` still have no accuracy figure and no benchmark; they rest on fixtures, on
each change measured against both library versions installed side by side, and on a weekly job that
runs their facts on the oldest and newest releases and now also checks that PyPI has no PyPDF2
release newer than the one the pack takes an unversioned requirement as.

### Unsupported patterns

[docs/KNOWN_ISSUES.md](https://github.com/hakanbogan/obelize/blob/v0.5.0/docs/KNOWN_ISSUES.md) lists
what I know about and have chosen not to fix yet. The gaps listed under 0.4.0 stand. A `PyPDF2`
requirement with no version is now taken as 3.0.1 where git lists the files and nothing in them
shows another release, which is a claim about an install nobody ran: the environment the code runs
in, a `pip.conf` in your home directory and a release another package requires are not seen, and the
section on the PyPDF2 pack lists the rest. The formats that changed are `pack.yaml` (the optional
`from.newest` and `from.lacks`), `run.json` (`packs[].assumed`) and their JSON Schemas.

### Added

- A pack may name the newest release of the distribution it migrates from (`from.newest`) and the
  names that release no longer defines (`from.lacks`), and a declaration that names no version, or
  a range that reaches below the floor but admits that release, is then taken as it
  ([ADR-056](docs/adr/ADR-056-newest-legacy-release.md)). The `PyPDF2` pack names 3.0.1 and its
  three removed classes. Nothing else in a pack changes: a pack that names no `newest` is gated
  as before, and `to` takes neither field.
- A run that took such a release says so: `packs[].assumed` in `run.json` holds it, and the
  terminal and `REPORT.md` say that the distribution is declared with no version that rules the
  release out and is taken as it.
- The weekly end-to-end run fails when PyPI lists a final PyPDF2 release newer than the pack's
  `from.newest`, so the claim cannot lapse unseen.

### Changed

- The legacy version gate no longer stops a `PyPDF2` repository for a requirement with no version,
  or a range that reaches below 3 but admits 3.0.1 (`PyPDF2`, `PyPDF2>=2.10`), where the
  repository shows no other release. On the 80-repository PyPDF2 frame that unblocks 19 of the 53
  repositories the gate stopped: 15 plan completely, 3 partly and 1 only holds. It still stops, and names the file, where one does: code that uses `PdfFileReader`,
  `PdfFileWriter` or `PdfFileMerger`; a lock, a constraints file, a `pip.conf` or another
  installer setting; an index setting in `pyproject.toml` or `Pipfile`; a pip option that moves
  the index; a manifest that names `PyPDF2` where no requirement was read or cannot be read; a
  version of `PyPDF2` written anywhere git lists that rules 3.0.1 out (a Dockerfile, a CI file, a
  `tox.ini`, a notebook); a virtual environment kept in the repository with another release. A
  requirement with an environment marker or a pre-release is not taken, and nothing is taken in a
  directory that is not the top of a git repository. The `openai` and Gemini packs are gated as
  before. A repository the gate no longer stops can now have its rows asked of a model you
  configured, so its source can reach that endpoint, which the stop had kept it from.
- The message for a pack that plans nothing because of what a repository declares (the legacy
  version gate, or a Python the new distribution does not install on) now says what the edit
  leads to: in a git repository, commit it before `fix --apply`, which refuses uncommitted changes
  unless you pass `--allow-dirty`. For a repository that declares the library nowhere, it names the
  requirement to declare (`PyPDF2>=3`) and a manifest that will do (`requirements.txt`).

### Fixed

- A Poetry caret on a `0.x` version is read as Poetry reads it: `^0.27` stops below `0.28` and
  `^0.0.3` below `0.0.4`, not below `1` and `0.1`. Nothing in a run changes yet, since only the
  floor of a declaration is read today.
- A `setup.py` requirement that code builds around its string (`"PyPDF2" + VERSION`,
  `"PyPDF2" ">=3"`, `"PyPDF2=={}".format(v)`, a subscript) is named without a pin, so `fix` no
  longer rewrites the literal into `"pypdf>=6.19" + VERSION`; the row needs review.

### Packs

- `py-pdf/pypdf2-to-pypdf` 0.3.0 names `from.newest` `3.0.1` and `from.lacks` `PdfFileMerger`,
  `PdfFileReader` and `PdfFileWriter`, and its limitations say what is taken as 3.0.1, what stops
  that, and what lives outside the repository and is not seen. The rules are unchanged.

## [0.4.0] - 2026-10-12

### Benchmark

I did not run the benchmark again for this release. Its numbers are still 0.1.0's and are for the
Gemini pack alone: scan precision 100.0% and recall 98.4% over 64 usages in five repositories, and
25 of 277 usages (9.0%) migrated in 20 repositories with no wrong edit, on the
[results page](https://github.com/hakanbogan/obelize/blob/v0.4.0/docs/BENCHMARK_RESULTS.md). The
scanner and the rewriter have changed since, so read those numbers as dated. The rule for a held
generation config is measured without the tests: a `fix` dry run over the 23 round-1 repositories at
their pinned commits gives the rows 0.3.0 gave, except 26 that moved from `needs_review` to `auto`
(20 in `kvcops__Virtual-Herbal-Garden`, 6 in
`Momen2410__Question-Answering-ChatBot-Using-Gemini1.5`). That says what is written, not whether it
passes a repository's tests, which a new round measures, with those two repositories in `dev`.
`openai/openai-0-to-1` and `py-pdf/pypdf2-to-pypdf` have no benchmark. They rest on fixtures, on
each change measured against both library versions installed side by side, and on a weekly job that
runs their facts on the oldest and newest releases.

### Unsupported patterns

[docs/KNOWN_ISSUES.md](https://github.com/hakanbogan/obelize/blob/v0.4.0/docs/KNOWN_ISSUES.md) lists
what I know about and have chosen not to fix yet. The gaps listed under 0.3.0 stand, except that
Python 3.15 is supported. The Gemini pack still withholds a model and the chat it starts in one
chain (`GenerativeModel(...).start_chat(...)`), and a generation config or safety settings held by a
name that is assigned twice, changed after its assignment, passed on, read by anything but the call
or taken as a parameter.

### Added

- `fix --apply` and `verify` print one line on stderr before each phase of tests: how many
  commands are about to run and after how many seconds each is stopped, so a long suite no longer
  looks like a hang. It names no command, since one can carry a credential, and stdout is unchanged.
- The Gemini pack rewrites a `generation_config` or `safety_settings` held by a name, where it
  refused as `generation_config_not_static` or `safety_settings_not_static` (COVERAGE gap 29).
  The name needs one plain assignment, a mapping, a list of mappings or a `GenerationConfig(...)`,
  and no reader but that argument of a call the rule rewrites, so nothing else sees the value or
  changes it between the assignment and the call. The keys are written into each call. A module's name stays where it
  is, and a `GenerationConfig(...)` it holds becomes the new SDK's `GenerateContentConfig(...)`;
  a function's own goes with the model, and so does the `GenerationConfig(...)` it holds. A name
  assigned twice, changed by a stored key or `update`, passed on, read elsewhere or a parameter is
  still refused. A module's name that another module changes after importing it is not seen.

### Changed

- `scan` and `fix` do less work on a large repository and write the same findings. The pass that
  finds a module another one reads (`model_object_read_elsewhere`) parses only the modules that
  spell both the module's name and a name read, and walks each once, where it walked every parsed
  module again for each model (9.5 s to 3.5 s on 800 synthetic modules). `fix` no longer parses
  a file that only mentions the library in prose or a comment: 28 s to 4 s on 200 files, 180 of
  them such. A pack the repository does not use, with no code to migrate and no pin to judge, no
  longer parses the files that name a module only its legacy distribution installed, and one that
  does reads imports only where a statement can hold one (11 s to 6 s over 5,000 files).
  End to end, `fix` takes 4.6 s on a repository of 1,000 files where 200 use the legacy SDK, which
  took 40 s, and 4.4 s on one file of 800 calls, which took 15 s.
- `patch.diff` for a file of more than four million line pairs (about 2,000 lines each side) is
  made without the matcher's repeated-line pass, which cost the square of a repeated line's
  count. Below that size the hunks are the ones 0.3.0 wrote; above it a hunk can be larger or
  split differently, and `git apply` reads the patch the same.

### Fixed

- A second `obelize undo` of a run exits `0` when every file already holds its original, where it
  exited `4` as if something had gone wrong, and it leaves the first `undo.json`, which says what
  was put back, instead of replacing it with a row of `hash_mismatch` skips. `undo.json`'s
  `exit_code` is now derived from files that were reverted or already original.
- The note `obelize verify` appends to `REPORT.md` names the commands it ran, on one line, so a
  reader of the report is not left with the first run's. A command with a backtick or a newline in
  it stays inside its code span: the fence is longer than any run of backticks, and the newline
  is spelled out.
- A run folder that an older obelize wrote and this one cannot read now names the release that
  wrote it and the command that undoes the run (`uvx obelize@0.2.0 undo --run <id>`), where `undo`
  and `verify` only said the record was unreadable.
- The terminal output of `scan` and `fix` has less in it that nobody acts on. A planned file shows
  `path  (N hunk(s))` and not the list of rules that produced the hunks, which `REPORT.md` and
  `plan.json` keep. An eligible row has a blank reason, where it printed the code that resolved
  its name. A dry run prints no `Verification:` line and its `REPORT.md` no empty phase, since no
  test was attempted, and two packs that suggest the same tests say them once.
- `fix --apply` no longer refuses a dirty tree when it has nothing to write. A repository where
  every finding is held back used to exit `5` with "uncommitted changes", which hid the real
  reason; it now exits `4` with the findings. A configured model keeps the gate, since a
  proposal could write.
- `fix --apply --verify "<cmd>"` looks for the command's program before it reads a file. A typo, or
  a `.venv/bin/python` that is not there, is a usage error (exit `2`) and nothing is written; it
  used to write the patch and end `inconclusive` (exit `6`) with `command_not_executable`. A
  command from `.obelize.yml` or the allowlist is still started, and still ends that way.
- When the commands you pass to `--verify` change a tracked file, the refusal of `fix --apply`
  says they did, where it asked you to commit or stash changes you had not made. The tree was
  clean when the run began, which `git_dirty: false` already recorded.
- A verification command that timed out gets a hint naming `--timeout <s>` and the default of 600
  seconds, which the flag's help and `docs/CLI.md` now state.

### Security

- `fix --apply` tries to make a file in each directory it will write into before it writes any,
  and refuses the whole apply as `unreadable` for a directory that takes none. A read-only
  directory used to stop the write partway and leave a half-migrated tree; a partial write that a
  race still causes now ends with `obelize undo` in its `Next:` line.
- A file name that holds a control or format character, a backtick or a pipe is skipped as
  `unusable_name`. Printed as it was, an escape sequence in a name moved a terminal's cursor or
  colours, and a backtick or a pipe ended a code span or a table cell in `REPORT.md`. Its name is
  spelled out (`\x1b`) in the skip, and the detail of a limitations row is escaped as a pack's
  text is.
- `.obelize/latest` is replaced by a rename below a `.obelize` opened without following a link,
  where a check for a link and then a write could race a swap; a link there is now replaced and
  what it named is not written. `.obelize.yml` is read without following a link, so a repository
  cannot make a parse error quote another file. A relative `XDG_CONFIG_HOME` is ignored, as the
  specification says, where it could have put the user's model block, allowlist and pack
  directories under the repository being scanned. Approving a command appends a row and keeps the
  rows already there, with their command text, where it rebuilt the file from the keys.

### Python 3.15

- obelize supports Python 3.15, which CI runs on Linux, macOS and Windows and the classifier names.
  `uv.lock` moves to pydantic 2.14.1 and pydantic-core 2.50.1, which have 3.15 wheels, where the
  older pair made pip compile pydantic-core with Rust. PyYAML has no 3.15 wheel yet, so pip builds
  it in pure Python, with no compiler. An Intel Mac installs libcst 1.8, which has no 3.15 wheel,
  so it compiles that with Rust there; the other systems install libcst 1.9's wheel.
  `tomllib` reads TOML 1.1 from 3.15 on, so a `pyproject.toml` that uses it has its Python floor
  read there, and is still reported as unreadable on 3.12 to 3.14.

### Packs

- `gemini/google-generativeai-to-google-genai` 0.3.0 writes `google-genai>=1.55` where it wrote
  `>=1`. Releases 1.0 to 1.54 do not hold what the pack claims: 1.54 has no
  `enable_enhanced_civic_answers`, one of the fifteen generation-config keys the pack moves into a
  config, so code it wrote could fail on an install `>=1` admitted. A `google-genai` line you
  already declare is left as you wrote it. The weekly job now runs the pack's facts on 1.55.0 and
  on the newest `google-genai`, and the `py-pdf/pypdf2-to-pypdf` facts on the newest `pypdf`; the
  Gemini facts also check that every keyword a rewritten call carries is one its method takes.

## [0.3.0] - 2026-10-12

### Benchmark

I did not run the benchmark again for this release. Its numbers are 0.1.0's and are for the Gemini
pack alone: scan precision 100.0% and recall 98.4% over 64 usages in five repositories, and 25 of
277 usages (9.0%) migrated in 20 repositories with no wrong edit, on the
[results page](https://github.com/hakanbogan/obelize/blob/v0.3.0/docs/BENCHMARK_RESULTS.md). The scan
specification the Gemini pack hands the scanner is the one measured, which `tests/unit/test_gate1.py`
checks, and the verdict of every hand-written answer key under `tests/fixtures/scan/` is unchanged;
one row of the encoding key moved from line 8 to line 6, the line `compile()` names. The scanner and
the rewriter are not unchanged, so read those numbers as dated. `openai/openai-0-to-1` and
`py-pdf/pypdf2-to-pypdf` have no benchmark. They rest on fixtures, on each change measured against
both library versions installed side by side, and, for `openai`, a weekly job that runs the same
fixtures on 0.27.0, on 0.28.1 and on the new releases.

### Unsupported patterns

[docs/KNOWN_ISSUES.md](https://github.com/hakanbogan/obelize/blob/v0.3.0/docs/KNOWN_ISSUES.md) lists
what I know about and have chosen not to fix yet. The 0.1.0 gaps for the Gemini pack stand. The main
gaps of the two other packs:

- `openai`: async and streamed calls, Azure, every resource but the seven calls under 0.2.0's Added,
  and the `openai.error` classes are reported and never rewritten. A write to a module setting
  through `exec`, `globals()`, `sys.modules` or `setattr`, `OPENAI_API_BASE` set in code, and a base
  URL formed once at assignment are not seen. A handler for top-level `openai.APIError` that reads
  `http_status` or `json_body` fails after the pin moves, with no warning. The pack writes nothing
  while any row of it is withheld.
- `PyPDF2`: a method or a parameter is never rewritten or reported, so only your own tests find that
  `PdfWriter(path)` starts empty on PyPDF2 and clones the file on pypdf, that page boxes turn from
  `Decimal` into `float`, or that `extract_text` puts different whitespace between the pieces of a
  line. A repository that does not declare `PyPDF2` at 3 or above, or a Python below 3.9, is
  blocked.
- Model names are kept as they are, in every pack.
- A source file with a chain of about four hundred terms is a `parse_error` row, not a rewrite. On
  every Python `compile()` accepts a chain of about thirteen thousand `and` or `or` operands, and
  on 3.14 and later a chain of tens of thousands of terms, and libcst can still segfault on them.
- Python 3.15 is not in the supported range yet.
- The four safety gaps in
  [docs/THREAT_MODEL.md](https://github.com/hakanbogan/obelize/blob/v0.3.0/docs/THREAT_MODEL.md) are
  narrower and still open: a filter driver named in a repository's own `.git/config` and, on
  Windows, a DLL placed in the repository; `obelize verify` or `obelize undo` run twice overwriting
  the record of the first; a credential shape the redactor does not list, a secret a Windows program
  writes as UTF-16 and a key in the model adapter's traceback; on Linux and macOS, `SIGTERM` or
  `SIGHUP` sent to obelize itself, which leaves a verification command running where Ctrl-C does
  not; and, on Windows, a process that WMI, Task Scheduler or `docker` starts for a verification
  command.

### Fixed

- A manifest that already declares the new distribution is no longer given a second line for it:
  the legacy row is withheld as `manifest_pin_shape_unsupported` and the file stays as written.
- One deeply nested expression no longer ends the whole scan. `compile()` now runs before libcst's
  parser, which overruns the C stack on thousands of nested parentheses, a chain of tens of
  thousands of operands or a stack of `not`s and killed the process; the file is one
  `input_does_not_parse` row. A tree that parses but overruns the analysis or the rewrite is that
  row, or is kept as it was with `output_does_not_parse`. A file `compile()` and libcst both refuse
  is now blamed on the line `compile()` names. A `setup.py` that does not compile declares nothing.
- A PEP 810 `lazy import` of the legacy module (Python 3.15) is no longer invisible. libcst binds
  no name for it, so the uses after it were never seen and the pin could be rewritten under code
  that still used it. The statement is now one `needs_review` row, `lazy_import`, a new value of
  the closed `bail` vocabulary in `findings`, `plan`, `run` and `proposal` schemas; the file and
  the pin stay. libcst 1.8, which an Intel Mac installs, cannot parse the statement, so there such
  a file is an `input_does_not_parse` row and is not written.
- A legacy pin that nothing imports is no longer `not_a_usage`. Code already on `google-genai` or
  `pypdf` with `google-generativeai` or `PyPDF2` still pinned is now a `needs_review` row,
  `manifest_code_mismatch`, so the CI check in `docs/CLI.md` exits `1` on it and a pack that only a leftover pin
  names is chosen. `fix` still writes nothing for it. An excluded file that names the library, a
  module only it installs, and `openai` (one distribution for both APIs) keep `not_a_usage`.
  `legacy_version_unsupported` is no longer raised for a pin below the floor when no code uses the
  library.
- A notebook, stub or windowed script that the default `include` leaves out and that names the
  library kept the pin whatever `exclude` said. `exclude` now releases it: the file is named as
  excluded and blocks nothing, so the rest migrates. A module a narrower `include` leaves out is
  named the same way instead of dropped without a word.

- A pin copied below a legacy one that something still imports is no longer joined to its
  neighbour. A quoted array element that no comma follows (the last one of a `pyproject.toml` list
  or a `setup.py` `install_requires`) was copied as it stood, which left a `pyproject.toml` that
  `tomllib` refuses and a `setup.py` requirement of `PyPDF2==3.0.1pypdf>=6.19`. The row is now
  withheld as `manifest_pin_shape_unsupported`.
- A manifest edit that its rule would not write (extras, a URL, the case above, the new
  distribution already declared) is withheld like a source rule's refusal. It was reported `auto`
  with the manifest unchanged, so the run said `Verification: pass` and exited `0` or `6`. It is now
  in `withheld[]`, is not counted in `counts.auto`, and the exit is `4`.
- A `setup.py` with a lone carriage return before the requirement, or a byte order mark on its
  line, no longer has its pin written at the wrong place (a `SyntaxError` on a line ending
  `)>=6.19pypdf`): libcst counts those lines differently from the edit, so the row is named
  without a pin. One that parses but overruns the stack in libcst's metadata pass (about four
  hundred terms) declares nothing, where it ended `scan` and `fix` with a `RecursionError`.
- A `SyntaxWarning` in the code obelize reads (an invalid escape, `is` with a literal) is no longer
  printed to stderr, where `compile()` and libcst printed one for each use, with the line that
  caused it.

### Changed

- The `fix` summary says why findings were left for you, with a file written or not: how many, the
  most common reasons, up to five of the rows that cause them (`path:line symbol code`), the files
  that hold the pin without a row (a notebook, a file importing a module only the old distribution
  installed), and a link to what each code means at this release's tag. A pack whose one
  distribution holds both APIs says that the repository moves whole or not at all.
- A warning on an edit that is written, or would be, is printed as
  `Check <file>:<line>: <code>: <what to look at>`.
- A command that follows: `Next: obelize fix --apply ... writes it.` after a dry run that planned a
  file, and `Next: obelize fix ... shows what it would change.` after a `scan` with an `eligible`
  row and no blocked pack. Both repeat `--pack` and `--repo`. After exit `6` the step is now one path
  for every pack: undo, `fix --apply`, install what it wrote, then `verify --run <new id>`, since
  a baseline that failed leaves nothing to compare with; when the tests merely gave no verdict, the
  line says to install what the run wrote into the manifest first.
- `scan` names the first three files that block a pin and, in `REPORT.md`, the files that import a
  module only the old distribution installed. A blocked pack's rows are introduced as what `fix`
  would try once the block is lifted. The limitations of a pack name its guide.
- `--verify` says in its help that it runs only with `--apply`.
- A report that was misleading now is not. An apply that wrote nothing prints no `Next:` line,
  since there is nothing to undo; a `Check` line after `--apply` says its line number is the one
  before the change; a blocked migration says that migration plans no change, not the run; the
  importers of a module only the old distribution installed are not listed as unanalysed; the
  count of dependency declarations counts declarations, not the rows one is graded into; the
  legend says a file is left as it was when any row in it is `needs_review` or `unsupported`; a
  verification command with a `|` and the words of a model endpoint no longer break the tables of
  `REPORT.md`.
- A pack's `source.url` may hold no whitespace, control character or Markdown or HTML character,
  since the report prints it.
- `REPORT.md` no longer lists a manifest as "still importing the legacy distribution" when the
  pin waits on a module only that distribution installed; it lists the files that import it.

### Documentation

- The README leads with the example, says what to do after each exit code (three guides for `4`,
  two causes for `3`), gives `openai` a four-step way to check a migration whose two versions are one
  install, and has a "With a coding agent" section. `skills/obelize/SKILL.md` is the same workflow as
  a skill file, and a test parses every command in it.
- `docs/CLI.md`'s CI check prints one `::error` annotation per finding and pins `X.Y.Z`, and has a
  paragraph on monorepos. The phase order says the compile check belongs to the verification, and
  that pytest's exit `5` is a failure here. `PACK_SPEC.md` no longer promises the rewrite matches
  your formatter. `KNOWN_ISSUES.md` names the half-migrated file, the import order, lockfiles and
  an `openai` notebook on a pin that has already moved. `PRODUCT.md` fixes Gate 5 at 2026-11-03 and
  updates the neighbouring tools. The issue templates name no single pack. `BENCHMARK_RESULTS.md`,
  `bench/errors.yaml` and ADR-044 no longer give counts and levers that disagree with the table
  `bench/errors.py` generates: an `alias_collision` is worth nothing alone, and ADR-044 says 25
  migrated rows where it said 34.

### Packs

- `openai/openai-0-to-1` (0.2.0) migrates from `openai` 0.27.0, not only 0.28.1. A second Gate 0
  found one surface across 0.27.0 to 0.28.1 and identical results from the ten legacy fixtures;
  a pin below 0.27.0 blocks the pack. The weekly job runs the legacy fixtures on 0.27.0 too.
- The openai and Gemini packs name model deprecations. All three suggest `<project python> -m pytest -q`
  and say a patch target "stops standing in for the code once it has moved". The Gemini pack
  (0.2.0) also names the class-wrapper refusal and the optional types `google-genai` returns. The
  openai pack names the Azure environment variables, `httpx2`, optional types, libraries that call
  0.x themselves, and what a notebook does to the pin. The pypdf pack (0.2.0) names that
  `extract_text` spaces text differently. The Gemini pack's `pack_version` rises from 0.1.0, which
  0.2.0 should have done.

### Security

- Every git command obelize runs sets `core.fsmonitor` to empty, so a hook the repository's own
  `.git/config` names no longer runs while obelize reads the tree. A filter driver in that file,
  which a clone does not carry, and on Windows a DLL placed in the repository, remain.
- Ctrl-C no longer leaves a verification command running on Linux and macOS: closing the command
  kills what is left of its process group.
- The command and the command line a run records are redacted, and the redactor knows more shapes:
  AWS session keys, GitHub OAuth, server and fine-grained tokens, Hugging Face, Slack, Stripe, GitLab
  and PyPI tokens, JWTs, a `Bearer` token, the password of a URL and a quoted `password`.
- Every git command also takes `--no-optional-locks`, so `status` does not rewrite a stale index
  and run a `post-index-change` hook that the repository's config names through `core.hooksPath`.
- The JWT and PEM patterns of the redactor took minutes on a megabyte of repeated starts
  (`eyJeyJ...`, a `BEGIN` line with no `END`); both are read once now. A URL password with no user
  (`redis://:secret@host`) is redacted. A redaction that crossed a quote no longer leaves a
  record that cannot be split, which raised after the command had run: the record keeps the program
  and `[REDACTED]`.
- A model proposal that repeats a `[REDACTED` placeholder it was shown, where the lines it replaces
  hold none, is refused as `replacement_carries_redaction`, a new value of `GuardRefusal` in the
  `proposal` schema (the `refusal` of `model/proposals-<n>.json`); `run.json` is unchanged.

## [0.2.0] - 2026-10-10

### Benchmark

I did not run the benchmark again for this release. Its numbers are 0.1.0's and are for the Gemini
pack alone: scan precision 100.0% and recall 98.4% over 64 usages in five repositories, and 25 of
277 usages (9.0%) migrated in 20 repositories with no wrong edit, on the
[results page](https://github.com/hakanbogan/obelize/blob/v0.2.0/docs/BENCHMARK_RESULTS.md). The scan
specification the Gemini pack hands the scanner is the one measured, which `tests/unit/test_gate1.py`
checks, and the verdict of every hand-written answer key under `tests/fixtures/scan/` is unchanged.
The scanner and the rewriter are not, so read those numbers as dated. `openai/openai-0-to-1` and
`py-pdf/pypdf2-to-pypdf` have no benchmark. They rest on fixtures, on each change measured against
both library versions installed side by side, and, for `openai`, a weekly job that runs the same
fixtures on 0.28.1 and on the new releases.

### Unsupported patterns

[docs/KNOWN_ISSUES.md](https://github.com/hakanbogan/obelize/blob/v0.2.0/docs/KNOWN_ISSUES.md) lists
what I know about and have chosen not to fix yet. The 0.1.0 gaps for the Gemini pack stand. The main
gaps of the two new packs:

- `openai`: async and streamed calls, Azure, every resource but the seven calls under Added, and the
  `openai.error` classes are reported and never rewritten. A write to a module setting through
  `exec`, `globals()`, `sys.modules` or `setattr`, `OPENAI_API_BASE` set in code, and a base URL
  formed once at assignment are not seen. The pack writes nothing while any row of it is withheld.
- `openai`: a handler for top-level `openai.APIError` that reads `http_status` or `json_body` fails
  after the pin moves, with no warning.
- `PyPDF2`: a method or a parameter is never rewritten or reported, so only your own tests find that
  `PdfWriter(path)` starts empty on PyPDF2 and clones the file on pypdf, or that page boxes turn from
  `Decimal` into `float`. A repository that does not declare `PyPDF2` at 3 or above, or a Python
  below 3.9, is blocked.
- A source file with a chain of about four hundred terms is a `parse_error` row, not a rewrite.
- The four safety gaps in [docs/THREAT_MODEL.md](https://github.com/hakanbogan/obelize/blob/v0.2.0/docs/THREAT_MODEL.md)
  are still open.

### Added

- One run can use several packs. `obelize scan` and `obelize fix` try every known pack over one read
  of the repository, and run each one with a finding that is not `not_a_usage`; `--pack` is
  repeatable and names exactly the packs that run. A run no pack applies to says so and exits `0`.
  Packs run in id order over what the ones before them wrote, each as a single-pack run; two that
  could feed each other are refused with exit `2`.
- `pack_dirs` in `~/.config/obelize/config.yml` adds directories of your own packs, chosen by id like
  the bundled ones. A repository's `.obelize.yml` may not set it.
- A second bundled pack, `py-pdf/pypdf2-to-pypdf`: the import, the names that exist unchanged on
  both sides, and the dependency line, from `PyPDF2` 3 to `pypdf` 6.19 or later. It reports the
  camelCase classes PyPDF2 3.0.0 removed and the names pypdf dropped, and blocks a repository
  below Python 3.9 or with PyPDF2 pinned below 3.
- A third bundled pack, `openai/openai-0-to-1`, so obelize ships three. It migrates `openai` 0.28.1
  to 1.109.1 or later, one library whose module keeps its name. It rewrites
  `openai.ChatCompletion.create`, `Completion.create`, `Embedding.create`, `Image.create`,
  `Moderation.create`, `Audio.transcribe` and `Audio.translate` to the same calls on the module client
  (`openai.chat.completions.create`, `openai.images.generate`) when every argument and every read of the result
  is one it has checked, and moves the pin to `openai>=1.109.1`. A read of the result by string keys
  along a path it lists (`response["choices"][0]["message"]["content"]`), also through a name that
  holds a part of the result or a loop over its items, is rewritten to the
  attribute path with the call, where the name holds the result alone and no handler for a missing key
  or `contextlib.suppress` surrounds the read. It rewrites the assignment `openai.api_base = value`
  to `openai.base_url = value` with the value ending in `/`, which the new module client needs, and
  refuses any other use of `api_base`. It reports async calls, twelve
  module settings the new releases ignore or read differently, the `openai.error` classes, the other
  resources, the modules of the 0.28.1 package and indirect use. Both versions are one distribution,
  so it writes no file while any row of the pack is withheld: each row of another file it would have written reads `repo_not_fully_migrated`, and the pin stays. A declaration that
  already admits only 1.109.1 or later (`openai==3.26.0`) is left as written, and one it cannot rewrite
  in place (extras, a URL) holds every file (`manifest_pin_shape_unsupported`, shown by `scan`). It does
  not report top-level `openai.APIError`, which both sides have and code on the new release writes, so a
  handler that reads `http_status` or `json_body` fails after the pin moves with no warning.
- Pack format: a seventh kind, `rename_setting` (ADR-055), for a shared module whose setting is
  assigned under another name in the new release. `settings` maps the legacy dotted attribute to
  its new name, and `value_ends_with` is one character the value must end with: a string literal gets
  it, anything else is written `("%s" % (value,)).rstrip(c) + c`. Any use of the old name but a plain
  assignment is `attribute_removed`, and a file that already uses the new name is `alias_collision`. `pack.schema.json` lists the kind. A pack field that names an identifier (a new symbol or setting name, a keyword argument) is refused when it is a Python keyword.
- Pack format, for a library that keeps its module name. `match.shared` makes only the names in
  `match.symbols` legacy, and a shared pack has no `rename_import` change. `rewrite_call` takes
  `root: module` (the call stays on the root the author wrote, and no `configure_to_client` is
  needed), `keywords` (parameters carried when written as keywords) and `result_paths` (the only
  reads of a result that carry; a string key that is the next segment of a path is rewritten to the
  attribute). A `manifest_dependency` may name one distribution on both sides,
  the two told apart by `from.version` and `to.version`, and a declaration `to.version` already admits is
  left as written. `arg_map` may not rename a parameter onto `config_kwarg`, which named the keyword twice.
- `scan` and `fix` print what a pack says about the findings it flagged: for each `flag_only` change
  that claimed one of its own pack's, its id, how many, its message and its suggestion. `REPORT.md`
  has the same under Guidance, lists the limitations of every pack that ran, and lists a fix's
  `verification.suggestions` as suggested and not run. The pack format has promised all three since
  0.1.0 and nothing printed them. `REPORT.md` escapes the Markdown and HTML characters in pack text,
  and display text refuses `U+2028` and `U+2029`.

### Changed

- `findings.json`, `plan.json` and `run.json` carry `packs[]` in place of `pack`, and `run.json`'s
  `blocked` moved into each pack's row. A run folder holds each pack's copy under
  `packs/<provider>/<slug>/` in place of `pack.yaml` and `pack.sha256`. An edit's `rule_id` is
  `<pack id>:<rule id>`.
- A pack whose repository rules it out has every row withheld for that reason, so an apply that
  writes for one pack and is blocked for another exits `4`. The reason is `runtime_unsupported`, or
  the new `legacy_version_unsupported`: the pack's `from.version` has a floor and the legacy
  distribution is declared below it, unpinned, or not at all while the code uses it. The text for a
  blocked pack names the declaration and what would unblock it, in place of "the new SDK".
- `--pack` has no default, and `cli.DEFAULT_PACK` is gone.
- In a shared module the scanner reports a read off a call's result (`f(...).choices[0].x`) as part of
  the call's own row, with no attribute finding of its own. A pack that is not shared keeps that finding,
  so the Gemini results are unchanged. It also reports the bare module fetched by its string
  (`importlib.import_module("openai")`, `__import__`, `sys.modules`) as `dynamic_access`, a read of its
  `__dict__` or `__getattribute__` as `module_alias_rebound`, and a star import only from the module
  itself or a legacy name.
- `repo_not_fully_migrated` also lands on the source rows of a pack whose new distribution is its
  legacy one, import rows included, `manifest_pin_shape_unsupported` is also raised by `scan` for such
  a pack, and `from_import_unmigrated_symbol` is also raised for a call a module-rooted `rewrite_call`
  reaches through `from M import Name`. No code was added to the vocabularies.
- A pack describes its target more generally. `to.requires_python` is required and replaces the
  fixed Python 3.10 floor. `rename_import` takes `symbol_map` (`Name` or `<submodule>.Name`) and
  `alias_fallbacks` in place of `types_symbol_map` and `types_alias_fallback`. A pack with no
  `configure_to_client` is valid when no change rewrites calls onto a client.
- `obelize fix` never asks the configured model about a pack whose new library is its old one, since a
  proposal is one row and the pack writes a whole repository or none. `--model`, `--accept-model` and
  `--show-context` with such a pack exit `2`, and a configured model is skipped with a line on stderr.
- `rewrite_call` counts a read of a result's name that the scope analysis links to no assignment (in a
  loop's second pass) and refuses a result bound in a class body. A call inside an f-string field is
  laid out on one line, since Python before 3.12 takes no newline there.

### Removed

- The pack fields `changes[].preconditions`, `changes[].replacement` and
  `generative_model_calls.default_model_name`, which nothing read. A pack that sets one is refused,
  and the Gemini pack's sha256 changes.
- `import_policy` from every plan in a run folder, and the unused codes
  `file_object_fields_not_verified`, `tests_touched_by_migration` and `stale_mock_target`. A run
  folder written by 0.1.0 no longer loads, so undo a 0.1.0 apply with 0.1.0.

### Fixed

- A `match` statement with a mapping pattern that captures a name (`case {"k": name}`) crashed the
  scan of every pack.
- A `setup.py` string literal Python cannot evaluate (an invalid `\U` escape, a NUL) crashed the
  manifest reader. It now declares nothing.
- A `setup.py` that a run changed as a source and as a manifest crashed it, whether one pack or two
  edited it, because the file is read as both. It is now one outcome from its first bytes to its
  last, and the manifest edit is made on the bytes the code edit wrote.
- A source file whose rendering overran the stack (a chain of hundreds of terms) stopped the whole
  scan with a `RecursionError`. It is now one `parse_error` row for that file.
- A call after a form feed, `U+2028` or `U+0085` in an earlier line was laid out from the wrong source
  line, since `str.splitlines` breaks where Python does not. The time to rewrite a file grew with the
  square of its legacy calls (about thirty seconds for four hundred in one file) and is linear now.
- A pack with one distribution on both sides left the pin lines it could write when another line
  of the same distribution could not be written (`openai` with and without extras). Every legacy line
  is now held with it.
- `importlib.import_module(".error", "openai")`, `pkgutil.resolve_name` and `sys.modules.get`, `pop`
  and `setdefault` with the module's name are `dynamic_access` rows, as `sys.modules["openai"]` was.
  A name in a string annotation (`"openai.OpenAI"`, `Annotated[int, "openai-beta"]`) no longer
  counts as the module used as a value.

## [0.1.0] - 2026-10-06

### Benchmark

I measured this release on public repositories, against answer keys I wrote by hand. The sample
leans towards small single-purpose applications. The
[results page](https://github.com/hakanbogan/obelize/blob/v0.1.0/docs/BENCHMARK_RESULTS.md) has
the method and every case.

- Scan precision is 100.0% and recall is 98.4%, over 64 usages I labelled in five repositories
  before the scanner ran on them. The scan reported 63 of the 64, and all 63 were right.
- obelize migrated 25 of 277 usages (9.0%) in 20 repositories and left the other 252 for a
  person. The most common reason, for 98 of them, is that something else in the same file or
  repository was not migrated, since obelize writes a file only when it can migrate all of it.
  Another 129 were withheld for a stated reason, most often a module with more than one
  `configure()` call (19 usages), the old SDK imported inside a function (18) or the module alias
  reassigned (17). The last 25 the scan never reported, mostly code reached through a function's
  return value, a star import in another file or a container.
- obelize wrote nothing in 14 of the 20 repositories, migrated part of five and finished one.
  None got a wrong edit. The scan did report three usages that my answer keys do not list, and
  none of the three was edited.
- None of the 20 was migrated and verified by its own tests. Of the 20, 16 have no test command,
  including the one obelize finished, and each of the four that do holds a usage no rule writes.
- On 13 of those repositories (174 usages) I also ran a general-purpose coding agent, given
  Google's migration guide and one fixed prompt. It migrated 154 usages (88.5%) against
  obelize's 17 (9.8%), and one of its migrations was verified by the repository's tests where
  none of obelize's was. It made a wrong edit in two of the 13 repositories, both real defects,
  and obelize in none. The agent does far more of the work, so I do not claim obelize is more
  accurate. The comparison shows that obelize made no wrong edit and names a reason for each
  usage it withholds. It is one agent, one day and one snapshot of the guide, on the split
  obelize's rules were tuned against. The agent's side dates from 2026-09-22 and was not rerun
  for 0.1.0, so its guide and model may have moved since.

### Unsupported patterns

The bundled pack declares 20 limitations, among them rewrites never checked against a live API
call. [docs/KNOWN_ISSUES.md](https://github.com/hakanbogan/obelize/blob/v0.1.0/docs/KNOWN_ISSUES.md)
lists what else I know about and have chosen not to fix yet. The main gaps:

- Every tool declaration is reported and never rewritten, because automatic function calling is
  on by default in `google-genai`.
- Model names are kept as written. Google has retired the `gemini-1.5` models, so change such a
  name yourself.
- Notebooks (`.ipynb`) that use the old SDK are found and not migrated, and the old dependency
  line stays while one does.
- Code that reaches the SDK through a function's return value, a star import in another file or
  a container is not found.
- obelize leaves a whole file as it was when the file has a `configure()` call in another module
  or more than one in the module, the old SDK imported inside a function, the module alias
  reassigned, or a model object passed around or read from another module.
- `mock.patch` targets, dynamic imports and surfaces with no rule, such as `protos`, `caching`
  and tuning, are reported and never rewritten. A `sys.modules` stub of the old module can be
  left in place without a report.
- Four safety gaps stay open, described in
  [docs/THREAT_MODEL.md](https://github.com/hakanbogan/obelize/blob/v0.1.0/docs/THREAT_MODEL.md):
  a git command obelize runs can start a program that the repository's git configuration names
  (on Windows it can also load a DLL from the repository that git finds nowhere else),
  running `obelize verify` again or `obelize undo` twice can overwrite the earlier record,
  redaction misses common credential shapes, and Ctrl-C can leave a verification command's
  processes running. On Windows that last gap is a process a broker such as WMI or Task
  Scheduler starts, and redaction also misses a secret written as UTF-16 or, with non-ASCII
  characters, in an older code page. Run obelize in a repository that is committed or backed up.

### Added

- obelize runs on Windows. It writes files, and opens run-folder files, relative to their parent
  directory and refuses a symbolic link or a junction as it does elsewhere, and a verification
  command and everything it starts run in a job object that the deadline ends. CI runs the suite on Windows for Python 3.12
  and 3.14. A real console, a OneDrive folder and a path longer than 260 characters are untried.
- `.obelize/` carries its own `.gitignore` holding `*`, so `git add -A` never picks up a run
  folder.
- A dry run of `obelize fix` prints up to 200 lines of the diff after its file list, with
  secrets redacted and control characters escaped, then the path of the whole `patch.diff`.
  `--json` output is unchanged.
- An apply ends with a `Next:` line naming the command to run after its exit code, and a
  run with nothing to write names the reason that held back the most findings. A
  `--verify` program that never started is named, with the interpreter form to use instead.
  `--json` output is unchanged.
- `python -m obelize` runs the CLI where the `obelize` script is not on `PATH`.
- `obelize scan` explains its table's columns in one line under it.

### Changed

- `obelize pack validate --help` links the pack format on GitHub instead of a `docs/` path,
  which an installed copy does not have. A defect in a bundled pack links the issue tracker,
  a refusal over a dirty tree names `--allow-dirty`, and `obelize --help` names the migration
  it supports.
- `obelize fix` uses the bundled Gemini pack when `--pack` is not given, as `obelize scan`
  does.
- `obelize fix --help` names the two `--model` providers, `none` and `openai_compat`.
- Help, terminal output, `REPORT.md` and error messages use plainer words and cite no design
  records. A refused `--verify` names the flag without pydantic's "Value error," prefix, and an
  apply refused over a file git does not track says to commit it, since `git stash` would
  leave it in place. `~/.config/obelize/config.yml` lists every problem under its key, and a
  misspelt key is matched against the keys that file accepts.
- The run folder's path is printed under `--repo` as typed, so it opens from the directory
  the command ran in. A second `obelize undo` of a run marks each file that holds its
  original again "(already the original)"; it still exits `4`. Terminal output and
  `--help` carry no Markdown backticks.

### Fixed

- An Intel Mac installs libcst 1.8, which has a wheel for that platform, so installing
  obelize there needs no Rust compiler. libcst 1.9 has no Intel macOS wheel.
- `--json` writes its document as UTF-8 bytes whatever the terminal's encoding, so stdout
  holds the same bytes as `findings.json` or `plan.json`.
- A file or directory whose name holds a backslash or is not valid UTF-8 no longer stops
  `obelize scan` before it writes any evidence. `run.json` lists it as `unusable_name` with no path, and the
  detail quotes the name.
- A run blocked by a declared Python floor below 3.10 says which file to change and to what,
  and `obelize fix` prints that reason too, where it only counted rows it did not write. An
  empty plan prints "No change planned.", and the verification line counts the commands a
  failing baseline ran.
- `obelize fix --apply` refuses to rewrite a file git does not track unless `--allow-dirty`
  is given, since `git diff` could not show that change. Other untracked files, the run
  folder among them, still do not count.
- `obelize verify --run` records its result after an apply that ran no verification command.
- A `Next:` line quotes the repository and the suggested tests the way the shells of the
  system it runs on read them, and a path the summary names inside the run folder uses one
  separator throughout.
- When an apply's write is refused after the tests before it ran, the verification line
  counts the commands that ran, and `run.json` keeps their results as the baseline and
  their time in `timings.verify_ms`.
- The note `obelize verify` adds to `REPORT.md` says whether tests ran before the change,
  and where they did, points at the report's Baseline section.
- The hint about a test command from obelize's own environment says whether it failed or
  timed out.
- A `--model` refused over the model block names the configuration file obelize read,
  wherever `XDG_CONFIG_HOME` puts it.
- A `--verify` command that needs a shell or has an unclosed quote exits `2` with the reason
  instead of a traceback, and so does an unusable allowlist entry in `obelize verify`.
