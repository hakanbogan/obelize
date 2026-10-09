# Changelog

Notable changes per release, in [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
format. Versions are `0.MINOR.PATCH`.

## Stability

Every format obelize reads or writes is unstable through 0.x: the CLI surface, the exit codes,
`.obelize.yml`, migration packs, the run folder and its JSON Schemas. None of them carries a
format version, so a 0.x release can change any of them, and this file lists each format change
in the release that makes it.

## [Unreleased]

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
