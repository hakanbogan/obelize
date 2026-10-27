# ADR-074: A maintained fixer, held to the proof of a rule

## Status

Accepted.

## Decision

Some migrations already have a tool that rewrites them: ruff's `NPY201` for NumPy 2, `AIR301` for
Airflow 3, pyupgrade, django-upgrade. Writing the same rules again as pack data would always be
behind the tool, so a pack may name one, and obelize starts it. The tool is a source of edits and
never of trust: what it prints is held to the proof every rule's own output is held to, and kept
only if all of it holds. The kind is `external_fixer`, the first user is `numpy/numpy-1-to-2`, and
obelize installs nothing (D5).

### D1. The form: an id from a registry in code, and the names it is run for

```yaml
- id: ruff-npy201
  kind: external_fixer
  params:
    fixer: ruff:NPY201
    symbols: [numpy.float_, numpy.NaN, ...]
```

`fixer` is a member of `FixerId` (`obelize.models`), a closed `Literal` that
`transforms/fixers.py` holds the same set of (tested), as `ChangeKind` and the registry of rules
are. For each id the registry holds the program, the releases of it that are accepted, the
arguments, and what installs it. A pack carries none of them: no command, flag, path or release can
be written in one, and each is a refusal in the negative corpus (`args`, `version`, a command line
as the id). `symbols` are the legacy names the tool is run for. The scan finds them as it finds any
change's (they are also under `match.imports` or `match.symbols`), and a row it grades `eligible`
that a fixer claims is the fixer's. A name two changes claim, or one a `flag_only` change reports
or sits under, is refused as for every kind, and a pack names a fixer once: the tool rewrites every
place it knows, so a second change with the same id would find the first's fixes outside its own
lines.

The smallest form needs no more. The tool reads a file on standard input and writes it on standard
output (`ruff check --isolated --select NPY201 --fix-only --stdin-filename={name} -`), so there is
no temporary file in the repository, no path to hand over and nothing for the tool to write
beside the output. A tool that can only work on a file would need one file in an empty directory;
none registered needs it.

### D2. One run of a tool

The tool is started as the agent of ADR-003 is: an argv list and no shell, a cleaned environment,
an empty directory, a deadline and a size on both ends, standard output only.

- **Where it is.** Among the absolute entries of the user's `PATH` (`processes.locate` on those),
  never the working directory or a relative entry, so a repository cannot stand in for it. It is
  not installed (D5).
- **Its environment.** `PATH`, `HOME`, `USERPROFILE`, `SYSTEMROOT`, `TMPDIR`, `TEMP`, `TMP`, `LANG`
  and `LC_ALL`, and nothing else: no token, and none of the tool's own settings. That matters: ruff
  reads `RUFF_NO_CACHE` and `RUFF_OUTPUT_FORMAT`, and `RUFF_NO_CACHE=1` makes it refuse to start
  (`invalid value '1' for '--no-cache'`).
- **What it reads.** Its standard input and nothing of the repository: the directory is empty, and
  `--isolated` makes ruff read no configuration file, which a repository's `pyproject.toml` could
  have used to widen what `--fix-only` fixes. The file's name is given for rules that depend on it.
- **Its limits.** 60 seconds, 4 MiB in and 4 MiB out, exit status `0`. A tool that cannot start,
  prints no release or exits otherwise is `external_tool_failed`; the others are
  `external_tool_timeout` and `external_tool_size_limit`.
- **Its release.** `ruff --version` is read once for each program and environment, and only a
  release the registry lists runs (`external_tool_version_unsupported`), because what a rule fixes
  changes between releases (D8).

### D3. The order: the pack's other rules first, the tool last, over their output

The tool is run on what every other rule of the pack wrote, not on the original, and each line it
changes is mapped back to the file the scan read through the equal blocks of the two files
(`difflib`, the differ of `patch.diff`). A line a rule wrote has no origin, so the tool may not
change it: the proof refuses any hunk that touches one.

The alternative was to run the tool on the original bytes and require its hunks not to touch a line
another rule of the pack edits. That needs the lines a rule edits, which the rules record as
replaced nodes and not as lines, and a three-way merge of two edits of one file, where a rule that
adds an import has moved every line below it. Running last needs neither: the tool sees valid
Python, the mapping is one function (`_carry`), and a second fixer would be mapped through the
first. A file another rule withholds is not given to the tool at all, since it is written by no
one, and its rows read `file_not_fully_migrated` with that rule's code in `caused_by`.

### D4. The proof, and what replaced one of the four parts of the brief

What the tool printed for a file is kept only if:

1. **Every line it changed lies in a claimed row.** The lines of the output that replace or delete
   a line must map back to a line the scan reported, as a row `eligible` and claimed by this
   fixer. A line it adds must be an import statement, or blank or a comment (`ruff` writes
   `from ast import literal_eval` for `safe_eval`); and no line it writes may be wider than the
   pack's `layout.line_length` or the line it replaced. Otherwise the whole output is dropped:
   `external_fix_out_of_scope`.
2. **A second run changes nothing.** `external_fix_not_idempotent`.
3. **The scan of the output finds none of the claimed names**, and the output passes the driver's
   gates as any rule's does: it parses and compiles (`output_does_not_parse`) and reads no name
   the input did not (`output_names_unresolved`), and the file is written whole or not at all.
   The obvious test, that a row whose line the tool did not change stays withheld, is the wrong
   one, and the real tool shows it: given `from numpy import float_, cumproduct`,
   ruff 0.16.8 writes `from numpy import float_, cumproduct, float64, cumprod`, a line it changed,
   that still imports the name NumPy 2 removed. And the other way, a fixer that moves an import
   (ruff's `UP035`) changes one line and leaves every use, which are no longer the legacy name. Only
   the scan can tell a name from a line, so the scan of the output is the test
   (`external_fix_incomplete`), and the rows that read it are those whose name is still found.
   A tool that changed nothing is the same case.

The proof holds a tool to the lines it may change and to a scan of what it wrote; it does not hold
it to what the change means. That is the pack author's: `symbols` lists only names that were each
measured. A first list of the names included `NINF` and `NZERO`, which ruff does fix, as `-np.inf` and `-0.0`
written in place, so `np.NINF ** 2` becomes `-np.inf ** 2` (`inf` becomes `-inf`) and
`np.NZERO.hex()` becomes `-0.0.hex()`, a `TypeError`. The output parses, compiles and names nothing
new, and no part of the proof can see it. They are `flag_only`.

### D5. obelize installs nothing (a deviation from the plan)

The approved plan had obelize install the tool, pinned by hash, when it is missing and the network
is on. That is not built. The platform wheels of ruff are too many to pin in code (a wheel for each
of the operating systems and architectures, each release), and an installer would reach the network
and run a build or a hook, which THREAT_MODEL TM-6 and the offline default of `fix` say obelize does
not do. A missing tool is a reason on the rows (`external_tool_missing`, `external_tool_version_unsupported`), the
other rows of the pack are written as they would be, and the way to install one is printed where a
person looks: `obelize pack validate` prints the command (`uv tool install ruff==0.17.2`), and
`obelize pack test` has a check for it that is about the machine and not the pack, so a bundled pack
that fails only it exits `7` and does not blame obelize. Whether to build an installer is for the
user to decide later; the registry already holds what one would need to say (the release and the
command).

### D6. Evidence, and the header

`run.json` records, under `packs[].fixers`, for each fixer a run started: the fixer, the tool, the
release it printed, the arguments it was started with (`{name}` stands for the file's name) and, for
each file, the sha256 of what the tool was given (the file as the pack's other rules wrote it) and
of what it printed, whether or not the proof kept it, and the lines it changed. The tool's own
output stays out of the run folder; the patch is the file's. A refusal is in `withheld[]` with its
code. `fix` says what it runs ahead of the diff, a dry run included, since a tool only reads:
`numpy/numpy-1-to-2 runs ruff (NPY201) on 3 files.` `undo` and `verify` read the files the run
wrote and know nothing of how.

### D7. What the registry holds, and what it does not

`ruff:NPY201`. Probed by running them, and not registered:

- **`pyupgrade`** prints no release (`--version` is an unrecognised argument), so the registry cannot
  hold it to releases it has measured.
- **`django-upgrade`** reads a file from standard input and prints its release, but its rewrites
  depend on the Django release it targets (`--target-version`), which the registry has no way to
  state: a fixed one could write what the pack's `to.version` does not admit.
- **`ruff:UP035`** and the other `UP` rules write for the Python a repository targets
  (`--target-version`), which is the same gap; and `UP006` leaves the `from typing import List`
  beside its rewritten uses.
- **`ruff:AIR301`**'s one safe fix in 0.16.8 renames a keyword (`schedule_interval` to `schedule`),
  which names no symbol a pack can claim, and **`AIR302`** (the moves to provider packages) has only
  unsafe fixes, which `--fix-only` does not apply.

Each is a row in the registry and, where it needs a target, a way for the pack to state one, so
none is a data-only addition yet. Airflow and Django packs are to be written when that is decided,
with their own measurement.

### D8. The releases of ruff the registry accepts

0.6.2 to 0.17.2, the PEP 440 range `>=0.6.2,<=0.17.2`. The five fixtures of the numpy pack that
name the rewritten names were run under every one of the 115 releases in it (0.12.6, yanked on
PyPI, included) and wrote the same bytes; twenty of them also went through the driver and its
answer keys. The output differs in 0.5.0 to 0.6.1, so they are refused, and so is a release newer
than 0.17.2 until it is run the same way. Between 0.15.16 and 0.16.3 the output for names the pack
does not claim changed twice (`np.in1d` stopped being rewritten to `np.isin`, which is not the same
call; `compare_chararrays` changed how it is imported), which is why a range is checked and not
assumed.

The lock holds ruff 0.16.8. A dependabot bump past the range fails `test_the_ruff_the_suite_runs_is_one_the_registry_accepts`
instead of skipping the fixtures, so widening the range and measuring are one change.

### D9. Measured over public repositories

Dry runs of `numpy/numpy-1-to-2` with ruff 0.16.8 over five shallow clones of public repositories
that use removed names, found by code search (`np.float_`, `np.NaN`, `np.cumproduct`), none of whose
code or tests was run:

| Repository (commit) | Files selected / parsed | Rows | Written |
|---|---|---|---|
| llimllib/ckmeans (f773363) | 1 / 1 | 3 `auto` | 3 lines in 1 file (`np.float_`) |
| melvrl13/python-quality-threshold (6f6123e) | 1 / 1 | 1 `auto` | 1 line in 1 file (`np.cumproduct`) |
| CellProfiler/centrosome (bedc3d0) | 38 / 26 | 6 `auto` | 4 lines in 1 file (`np.product`, `np.cumproduct`, `np.NaN`, `np.Inf`, inside the `else:` of a NumPy version check) and two `numpy` lines in `setup.py` |
| jameshensman/pythonGPLVM (81a4ce9) | 10 / 4 | 1 `needs_review`, 2 `unsupported` | nothing: ruff fixed the one `np.NaN` of `GP.py`, but two Python 2 files (`input_does_not_parse`) hold the whole repository back (`repo_not_fully_migrated`) |
| shaypal5/skift (00b6728) | 9 / 4 | 3 `needs_review` | nothing: `setup.py` declares Python >=3.5, which NumPy 2 does not install on (`runtime_unsupported`), so the tool was not started |

The tool ran on one file in four of the five and on none in the fifth. Nothing was withheld by the
proof itself (no `external_fix_*` row) in these five, which says the five are easy cases and not
that the proof is idle: the fixtures and `tests/unit/test_external_fixer.py` have the cases that
withhold. One real `--apply` and `undo` ran over a copy of ckmeans: the file was written by the
tool's output and put back byte for byte. The centrosome case shows the pin line: `numpy>=1.18.2`
becomes `numpy>=2` in `install_requires`, which a library that supports NumPy 1 would not want, and
the pack's `limitations` say so. Nothing was added to BENCHMARK_RESULTS.md.

## Consequences

- A new kind of change reaches obelize's files through a program it does not control, so the
  threat model has a row (TM-15) and `KNOWN_ISSUES.md` a section: the tool is trusted as far as the
  user installed it, and contained only in what it reads and prints.
- `pack.schema.json` gains the kind and `run.schema.json` `packs[].fixers`; eight codes join the
  bail vocabulary and the bails an import row may carry, which the generated findings, plan and
  proposal schemas list. `spec_digest` and the scan of every pack that does not use the kind are
  what they were (the sha256 and the digest of the three older packs are unchanged).
- A repository that has no ruff of an accepted release can read the migration (the rows say what
  to install) and cannot get the 23 rewrites; the rest of the pack, and `flag_only` and the pin,
  behave as they would. `fix` stays offline.
- A second use of the kind is a row in `FIXERS`, an id in `FixerId`, a pack, and a measurement of
  the tool's releases over the pack's fixtures, plus a way for a pack to state a target release if
  the tool needs one (D7).
