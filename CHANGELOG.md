# Changelog

Notable changes per release, in [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
format. Versions are `0.MINOR.PATCH`.

## Stability

Every format obelize reads or writes is unstable through 0.x: the CLI surface, the exit codes,
`.obelize.yml`, migration packs, the run folder and its JSON Schemas. None of them carries a
format version, so a 0.x release can change any of them, and this file lists each format change
in the release that makes it.

## [Unreleased]

## [0.1.0] - 2026-09-29

### Added

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
