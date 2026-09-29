# ADR-005: Technical stack

## Status

Accepted; amended by ADR-021 and ADR-022.

## Decision

- **Packaging:** `pyproject.toml` with **hatchling** as the build backend; the
  version is single-sourced from `src/obelize/__init__.py`.
- **Environments and locking:** **uv** (`uv sync`, `uv lock --check` in CI,
  `uv build` for releases).
- **CLI:** **Typer**, with heavy modules (libcst above all) imported lazily inside
  command bodies so that `obelize --help` stays under 300 ms.
- **Data models:** **pydantic v2**, every model with `extra="forbid"`. Packs,
  config, findings, plans, run records and the JSON schemas are all pydantic
  models; the JSON Schema files in `src/obelize/schemas/` are generated from them and
  a `schema-drift` CI job fails if they are stale.
- **Source analysis and rewriting:** **libcst**, for both scanning and the
  codemod.
- **Git access:** **subprocess `git`**, no GitPython.
- **Tests:** **pytest**.
- **Lint and format:** **ruff** (check and format).
- **Types:** **mypy** in `strict` mode with the pydantic plugin.
- **Python:** **3.12-3.14** for obelize itself. A *migrated repository* may
  target Python >= 3.10, the floor of `google-genai` (ADR-001); verification runs
  that repository's own interpreter, not obelize's.
- **Runtime dependencies: at most seven, and that is a budget, not a coincidence.**
  Each floor is the exact version the lockfile tested when the floor was set:

  | Dependency | Why |
  |---|---|
  | `typer>=0.27.2` | CLI surface |
  | `pydantic>=2.13.5` | closed-world models and schema generation |
  | `libcst>=1.9.0`; `>=1.8.6,<1.9` on an Intel Mac, which 1.9 has no wheel for | format-preserving parse, metadata, transform |
  | `pyyaml>=6.0.3` | pack and config parsing, `safe_load` only |
  | `packaging>=26.3` | PEP 440 / requirement-line parsing for manifests |
  | `pathspec>=1.1.1` | `exclude` patterns, with git's own semantics (`GitIgnoreSpec`) |

  The model adapter (ADR-003) uses stdlib `urllib`, and every supported
  interpreter has `tomllib`. A new runtime dependency needs an ADR, because the
  list must stay small enough to audit by hand (threat model TM-7).

### Why libcst

- **Format-preserving CST.** A rewritten file differs from the original only
  where a rule changed something, bytes in and bytes out, so a reviewer can read
  the diff; an `ast` rewrite reformats the whole file.
- **Resolution by metadata.** `QualifiedNameProvider` resolves import origins
  ([ADR-008](ADR-008-scanner-and-codemod-corrections.md) has the rules),
  `ScopeProvider` backs the closed-world binding analysis (ADR-006) and
  `PositionProvider` the coordinates findings are keyed on. Analysis and
  transform share one `MetadataWrapper(module, unsafe_skip_copy=True)`, so node
  identity holds between them; skipping the copy is safe because the analysed
  tree is never mutated in place.
- **No `FullRepoManager`.** Analysis is per file: scanning runs in a
  `ProcessPoolExecutor` (`spawn`, workers exchanging plain dicts and never CST
  nodes, `min(8, cpu_count - 1)` workers:
  [ADR-022](ADR-022-runner-result-order.md)), within roughly
  2 s wall for up to 100 matching files on 8 cores: cost follows *matching* files
  and metadata resolution, since the byte prefilter eliminates 97.81% of `.py`
  files. A file's scan is a pure function of
  `(file bytes sha256, pack sha256, obelize version, python major.minor)`, so a
  cache can be added without touching the analysis. **That key holds for
  findings only**: the manifest verdict depends on every other file and on the
  `.obelize.yml` exclusions, so `scan/manifests.py` is a repository-level pass
  after every file is scanned
  ([ADR-021](ADR-021-dependency-manifests-verdict.md)).

## Consequences

- Cross-module re-export cannot be resolved; it is a documented v0 limitation.
- Repositories pinned below Python 3.10 are reported `blocked: runtime_unsupported`.
- Windows is untested: the verify runner relies on POSIX process groups for timeouts.
