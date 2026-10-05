# Changelog

Notable changes per release, in [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
format. Versions are `0.MINOR.PATCH`.

## Stability

Every format obelize reads or writes is unstable through 0.x: the CLI surface, the exit codes,
`.obelize.yml`, migration packs, the run folder and its JSON Schemas. None of them carries a
format version, so a 0.x release can change any of them, and this file lists each format change
in the release that makes it.

## [Unreleased]

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
