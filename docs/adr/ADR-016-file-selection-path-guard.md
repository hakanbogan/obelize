# ADR-016: File selection and path guard

## Status

Accepted.

## Decision

**D1. The guard is `src/obelize/fsutil.py`, and it ships with T2.**
`refusal(root, candidate)` returns why a path must not be opened, or `None`.
The walker asks it before reading and `fsutil`'s writer before writing, so both
get one answer without `transforms/` importing the scanner.

**D2. git's listing is used only when `git rev-parse --show-toplevel` resolves
to the root itself.** Otherwise the fallback walk runs, so a directory inside
another checkout, such as a fixture tree, never gets that checkout's index and
`.gitignore`.

**D3. A user's `exclude` prunes no directory. Only the always-excluded set
does.** `exclude` filters files, even a list with no `!` pattern, because
ADR-010 F-2 names every excluded file that still imports the legacy
distribution, and a pruned directory cannot be named file by file.

**D4. Every refusal is a published reason.** `SCAN_VOCABULARY.md` §11's seven
values, closed and asserted against `obelize.models` both ways, so the evidence
writer invents none; `run.json`'s `limitations[].code` is a superset. A name
that is not valid UTF-8 is refused as `unusable_name`, never scanned mangled.

**D5. The walker opens nothing.** It lists, stats and matches; the prefilter,
`max_file_bytes` and the parse gates belong to the reader, so a file is read
once. `Walk.unincluded` names the paths `include` did not take that can hold
Python (`*.ipynb`, `*.pyi`, `*.pyw`): nothing analyses them, and F-2 prefilters
their bytes ([ADR-021](ADR-021-dependency-manifests-verdict.md)).

**D6. A listed path that is not on disk is `missing`, not an escape.** An
ordinary `rm` of a tracked file leaves its name in the index; calling it
`outside_root` would turn a security signal into noise.

**D7. A root that is not a readable directory exits `2`.** A missing root, a
file, or a directory that cannot be searched raises `ConfigError`, as an
unusable `.obelize.yml` does (ADR-015 D1): the root is part of how the command
was invoked. A root that can be searched but not listed is walked, and reported
`unreadable`.

## Consequences

- This is TM-2's read half: containment with both sides resolved, a separate
  symlink guard, `followlinks=False`, a mandatory `is_file()`, and submodules
  pruned and reported.
- The two listings disagree about gitignored files on purpose, and git is
  right; only the fallback walk prunes a directory holding `pyvenv.cfg`.
- Under the default `include` (`**/*.py`) the guard is never asked about a
  submodule or a linked directory; `include: "**/*"` hands both over.
- `tests/fixtures/walker/_build.py` builds the fixture tree and its answer key,
  since a nested `.git`, a symlink loop and an unreadable directory cannot be
  committed.
- Unmeasured: a tree where most files are rejected, where the guard's `resolve`
  runs and the parse does not.
