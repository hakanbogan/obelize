# After a run

`fix --apply` exits with a code that says what is left, and most runs end with a `Next:` line
naming the command to run. Every run also writes a folder, `.obelize/runs/<id>/`, whose
`REPORT.md` is the page to read ([the run folder](RUN_FOLDER.md) lists the rest).

## Exit codes

- `0`: everything it found is migrated and your tests passed. Read `git diff`, then commit it or
  undo it.
- `4`: some places are left for you. The summary names the most common reasons, what to change for
  each, and the first places behind them, and `REPORT.md` lists each one with its
  [reason](SCAN_VOCABULARY.md#4-bail-codes-editreason). Migrate them by hand with the guide of the
  pack that left them ([Gemini](https://ai.google.dev/gemini-api/docs/migrate),
  [openai](https://github.com/openai/openai-python/discussions/742),
  [pypdf](https://pypdf.readthedocs.io/en/stable/meta/history.html)), commit, then run
  `uvx obelize fix` again.
- `3`: your tests failed after the change. Either the change broke something, or a test is tied to
  the old SDK (a `mock.patch` target the report names, or a module that builds the new client when
  it is imported and finds no key). For the last two, update the test or set the key to any value
  for the run, then `obelize verify --run <id>`. If neither explains it, `obelize undo --run <id>`
  puts the files back. For `openai` with 0.28.1 still installed, `3` is the expected result:
  follow the [four steps](GETTING_STARTED.md#openai-0x-to-1x).
- `5`: obelize refused an apply over uncommitted changes, or a verification command it does not
  trust.
- `6`: the change is written but your tests gave no verdict, as happens without `--verify` or
  when they already failed before the change.

All the codes are in [CLI.md](CLI.md#exit-codes).

## What it writes and what it keeps

obelize writes a file only when it can migrate all of it, and keeps the old dependency line until
nothing in the repository uses the old SDK. It never removes a pin that nothing imports; a scan
lists it as `manifest_code_mismatch`. On a real project the usual result is `4`: obelize migrates
the files it can prove, which can be none, and lists the rest in the report.

## Putting a run back

`obelize undo --run <id>` puts back the files a run wrote, unless you edited them since. It never
overwrites content it did not write, and a second `undo` of the same run exits `0`. If a file was
skipped, the output names both hashes and the snapshot to copy from.
