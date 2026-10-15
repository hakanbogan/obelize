# ADR-056: The newest legacy release

## Status

Accepted.

## Decision

A pack may name the newest release of the distribution it migrates from. A declaration that names no
version, or one whose range reaches below the floor but admits that release, is then taken as that
release, unless the repository shows another one. This widens the legacy version gate of ADR-050 D5 for the one pack that names it,
`py-pdf/pypdf2-to-pypdf`, and for nothing else.

The gate stops a repository that declares the legacy distribution with no version, or with no lower
bound, because the pack's rules were measured above the floor. For PyPDF2 that stopped the
repositories whose install is exactly the release the rules were measured on: PyPI's last PyPDF2
release is 3.0.1 (2022-12-31), and a clean `pip install PyPDF2` resolves to it. It was the largest
single stop for the pack in the benchmark frame ([BENCHMARK_RESULTS.md](../BENCHMARK_RESULTS.md)).

### D1. Two optional fields on `from`

- `newest`: a final release (a post release is allowed; a pre-release, a dev release and a local
  version are not), spelled as PEP 440 normalises it, that `from.version` admits. `from.version` must
  have a floor: with none, no release is out of range and the field would say nothing.
- `lacks`: the qualified names that release no longer defines, sorted and de-duplicated, and only
  with `newest`. Each is a name in `symbols` of a `flag_only` change, so the scan reports it. The
  pypdf pack lists `PdfFileMerger`, `PdfFileReader` and `PdfFileWriter`, which have raised
  `DeprecationError` since 3.0.0.

`to` has neither: the schema refuses an unknown key there. Both reach the scan as
`ScanSpec.legacy_newest` and `legacy_lacks`, which are gates like `legacy_floor`, so `spec_digest`
does not move and a Gate 1 measurement stays bound to the spec it was taken on.

### D2. A declaration that installs the newest release passes, unless the repository says otherwise

The gate still asks every declaration of the legacy distribution, one at a time. One that fails the
floor passes now when it installs the newest release: a requirement the edit can rewrite as a whole
(no extras, no URL, no hash, on one line, not editable), with no environment marker that may switch
it off, that no part of which allows a pre-release, and some alternative of which contains
`newest`. `PyPDF2`, `PyPDF2>=2.10`, `PyPDF2<4` and `PyPDF2===3.0.1` install it; `PyPDF2<3`,
`PyPDF2~=2.12`, `PyPDF2!=3.0.1`, `PyPDF2>=3.0.0rc1`, a requirement with a marker, a hash-pinned
one, `-e git+...#egg=PyPDF2`, a wheel's file name and one the scan cannot read do not.

Only then is the repository asked whether anything else decides the release
(`scan/installed.py`, `contrary`). The first path that says it does is the evidence, and the run is
blocked as before, naming that path. The checks run in this order, and each fails closed (a manifest
it cannot read is evidence), except that a listed file that cannot be read, or is over 32 MiB, is not
searched for a version.

1. Code. A finding that is not `not_a_usage` for a name in `lacks`: that code cannot run on the
   newest release, so an older one is in use.
2. A manifest the scan reads: every `*requirement*.txt` (`dev-requirements.txt` too),
   `requirements/*.txt`, and, for their declarations only, `*requirements*.in` and
   `*constraints*.txt`, which no rule writes (their declarations carry no pin, and a bare name in
   one is not read). One that cannot be read whole, or holds a NUL byte (a UTF-16
   `pip freeze`); one with a line that names the distribution where no declaration was read, once
   comments are cut (a bare name in an input or constraints file); in `pyproject.toml` and a
   `Pipfile` the names are counted instead, against the rows read: a key or a string where a
   dependency can be declared (PEP 621's and 735's, the tables of uv, Poetry, PDM, Hatch, Pixi and
   Rye, and a Pipfile's packages), so a `[tool.uv.sources]` key, a constraint or an override counts,
   and `known_third_party` under `[tool.isort]`, a Ruff or mypy list, a project's `description` and
   a URL do not; in a requirements, input or constraints file, a pip option that can
   move the release, which is every option but `-r` or `-c` to a manifest the scan reads, `-e` to
   a local directory, `--extra-index-url` and `--trusted-host`. A hash on a continued line is such
   an option. A line that is read and names a release (`PyPDF2<3` in a constraints file) is judged
   like any declaration, by the floor and by item 5; a file that names nothing about the
   distribution is no evidence for being there. A manifest the user's `exclude` removed is judged
   by its pip options and, in item 3, its resolver settings, and by nothing else: no row is read
   from it, and a version it names is judged by item 5 like any listed file. A path no report can
   spell, a link or a file the path guard refuses is skipped, and so is one that cannot be read.
3. Resolver settings in `pyproject.toml` and `Pipfile`: `tool.uv.exclude-newer`, `resolution`,
   `index-url`, `find-links`, `no-index` or a `pip` table, a `tool.uv.index` that is not `explicit`,
   `tool.poetry.source`, `tool.pdm.source`, a Pipfile `[[source]]` that is not PyPI, or a TOML file
   this Python cannot parse (nested too deep for the parser included).
4. A file git lists that can pin or constrain a release without being a manifest the scan reads:
   `poetry.lock`, `Pipfile.lock`, `uv.lock`, `pdm.lock`, `pixi.lock`, `conda-lock.yml`,
   `pylock.toml` and `pylock.*.toml`, `environment.yml` and `.yaml`, `pip.conf`, `uv.toml` and
   `requirements*.lock`. `LOCKS` and `LOCK_GLOBS` in `scan/manifests.py` are the list. So is a file
   name no report can spell (a control, format or backslash character), which the walk skips: what
   is under it is unseen.
5. A version written anywhere else, in the name or the bytes of any file git lists, a dot-directory
   and a file the user's `exclude` removed included: `PyPDF2 <op> <version>` that does not admit
   the newest release or that cannot be read, or `PyPDF2-<version>` of another release (a
   Dockerfile, a CI file, a `tox.ini`, a notebook's `!pip install`, a committed environment's
   `dist-info`). A UTF-16 file is read after its byte-order mark. A file over `max_file_bytes` is
   searched too, in windows of 1 MiB that repeat the last 4 KiB of the one before, so that no more
   than a window is held and a mention is whole in one of them; a UTF-16 one is read as bytes, and a
   file over 32 MiB is not searched. A mention cut by a window's edge reads as another release, which
   is evidence.
6. What git ignores, found with `scandir` and never read: a lock, a constraints file or a
   `*requirements*.in` beside the repository root or a manifest that declares the distribution, and
   a `.venv`, `venv` or `env` in the root or beside any listed file, found with one `lstat` per
   name, whose `site-packages` holds a `dist-info` or `egg-info` of another release.

Nothing is taken from a directory that is not the top of a git repository: the fallback walk skips
dot-directories, so a pin in `.github/workflows` would never be seen. A declaration that would have
installed the newest release is then blocked as an unpinned one is, and its message says that
obelize lists every file only at the top of a git repository, so that the way to lift the block is to
run it there, with the pin the other (`runtime.Blocked.unlisted`).

When nothing is found, the run says what it took: `Scan.assumed` is the (distribution, release)
pair, `packs[].assumed` in `run.json` is the release, and the terminal and `REPORT.md` say that the
distribution is declared with no version that rules the release out and is taken as it. A blocked
run's message names the evidence and still says what to pin.

### D3. One consumer is enough

ADR-050 widens the format only for a field a second, real migration needs. That migration is PyPDF2
(ADR-051), and the field is for it: it is the only pack whose newest release is inside the range its
rules were measured on. openai's newest release is outside `>=0.27.0,<1`, and the Gemini pack's
`from` has no floor, so neither names a `newest` and neither changes: the packs' scans, findings and
digests are what they were, and a test runs both through the same gate to show it. A pack that cannot
name an index's last release gets no inference, which is the right default.

### D4. Checked weekly

`newest` is a claim about an index that keeps changing. The weekly end-to-end run reads PyPI's
release list for PyPDF2 and fails when a final release that is not yanked is newer than the pack's
`from.newest`, or when the list no longer holds `newest`. A pack whose claim has lapsed would take a
declaration that installs something else for the release the rules were measured on. The step reads
the number from the pack, and a test holds the set of packs that name a `newest` to the one the step
checks, so a second pack cannot name one without a check.

## Consequences

- A repository that declares PyPDF2 with no version, or with a range that reaches below 3 but admits
  3.0.1 (`PyPDF2>=2.10`), can now be migrated, and a model the user configured can then be asked about its rows, so source reaches the
  endpoint that the earlier stop kept it from. The run says what it assumed, and `--verify` finds
  what the names do not.
- The gate reads more of a repository on this path: every listed file, once, and only when some
  declaration passes through `newest`, a file over `max_file_bytes` up to 32 MiB of it in windows.
  Elsewhere the walk still opens nothing it did not.
- `run.json` gains `packs[].assumed`; the formats stay unstable through 0.x ([ADR-048](ADR-048-accepted-gaps-in-0-1-0.md)).
  The pypdf pack is 0.3.0: a pack field it now fills is a minor bump.
- The inference is a claim about an install nobody ran. It cannot see the environment outside the
  repository, a release another package requires, a submodule's files, a gitignored file the last
  check does not look for, a Python declared only in a `Pipfile` or `setup.py`, or an index the
  machine rewrites. [KNOWN_ISSUES.md](../KNOWN_ISSUES.md) lists them.
- The installer's settings outside the repository are not read, on purpose: not a `PIP_*` variable
  (`PIP_INDEX_URL`, `PIP_CONSTRAINT`, `PIP_FIND_LINKS`, `PIP_NO_INDEX`), not a `pip.conf` in the home
  directory. The machine that scans is not the one that installs (in CI it is another), and reading
  its state would make a finding depend on it, where the scan is deterministic
  (`tests/oracle/test_scan_determinism.py`). A repository that depends on such a setting pins the
  release in a manifest the scan reads.
- The holes the gate had are closed. A requirement line PEP 508 refuses (`PyPDF2~=1`) is a row for
  its name with no version, and a local build (`==3.0.1+corp`) names no floor, since it is not the
  release the rules were measured on: both block like a pin nobody can read, whatever another
  declaration says. A pin of `pypdf` that admits no release at or above `to.version` (`pypdf==3.0.0`,
  `pypdf<6`), in any manifest the scan reads, blocks as `new_version_unsupported` and names its
  path ([ADR-050](ADR-050-generic-pack-engine.md) D5): before, the same repository was rewritten to
  `pypdf>=6.19` in one file and left a pin that cannot resolve in another.
