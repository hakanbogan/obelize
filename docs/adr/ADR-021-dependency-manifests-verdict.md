# ADR-021: Dependency manifests and verdict

## Status

Accepted.

## Decision

### D1. A manifest is selected by name, outside `include` and inside everything else

`scan/manifests.py` publishes the closed set of manifest names, and
`config.Selection.selects_manifest` applies the always-excluded set and the
user's `exclude`, but not `include`, which picks source files. The walker lists
them as `Walk.manifests` beside `Walk.files`, on the same traversal and behind
the same path guard. `setup.py` is in both: the code pass finds nothing in it,
the manifest pass reads it. An excluded manifest is neither read nor written.

### D2. The row count is the edit count: F-2's two edits collapse when neither is blocked

When nothing blocks the removal,
[ADR-010](ADR-010-fixture-oracle-and-atomicity.md) F-2's add and remove are one
rewrite of the legacy line (`google-generativeai==0.8.6` -> `google-genai>=1`)
and one row. When the removal is blocked they are two rows: the add is eligible
(unless that manifest already declares the new distribution) and the legacy pin
is withheld. Both sit on the declaration's line, the address the edit uses.

### D3. Migrated means eligible; blocking means a row that still brings the distribution in

A file has *migrated* when its plan holds an eligible finding. A file *blocks*
the removal when a non-eligible row still loads the distribution: `import`,
`star_import`, `dynamic`, `parse_error` (fail-closed), or a `mock_patch_target`,
which imports the module when the patch is entered; a prose mention does not.
A file the default `include` leaves out (a notebook, a stub, a windowed script)
that matches the byte prefilter blocks as an import does; under a narrowed
`include` it is named as excluded. Neither is analysed.

### D4. Nothing migrated means nothing is added, and the pin is not touched

With nothing migrated the manifest is not edited. The legacy pin is withheld
with `repo_not_fully_migrated` while a file still imports it, and otherwise
graded `not_a_usage` ([SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) §3's line
that "merely disagrees with the code"), because removing it would edit a
manifest for a migration this run did not make.

### D5. `manifest_code_mismatch` is the other direction, and it is a review item

A manifest that declares the new distribution and no legacy pin, while code
still imports the legacy one, is `manifest_code_mismatch`: `needs_review`,
never an edit, because the code is what must change. The "no legacy pin" clause
keeps the rule idempotent: F-2's own intermediate state declares both.

### D6. Manifest rows get their own plan, and `ImpactPlan`'s refusal stands

`ImpactPlan` refuses `manifest` rows, and `ManifestPlan` is the
repository-wide plan, because a manifest declaring both distributions keeps a
partial migration installable where a half-rewritten file breaks. It carries
the findings and the `blocking`, `excluded` and `transitive` files, and refuses
a non-`manifest` row, `file_not_fully_migrated`, and `repo_not_fully_migrated`
or `transitive_dependency_in_use` with no file named behind it: each code
claims an in-scope file.

### D7. The two manifest codes are outside §6's ladder

A manifest row names one declaration, so `manifest_code_mismatch` never meets
`repo_not_fully_migrated` on a row. `scan/manifests.py` publishes `BAILS` and
no `RUNG`, and `tests/oracle/` lists `manifest_code_mismatch` as unranked.
`repo_not_fully_migrated` and `transitive_dependency_in_use` sit at §6's rung
6: like `file_not_fully_migrated` they name no concrete defect, so they never
displace one that does. The latter withholds the pin while nothing imports the
legacy distribution but an in-scope file imports a module only it installed
(the pack's `match.transitive`) and no manifest declares that module's
distribution.

### D8. Lines, not a parse-and-serialise round trip — except for `setup.py`

A manifest is read as lines, and a finding records the line and the column the
name is written at, so the scan's address is the edit's. The dependency budget
([ADR-005](ADR-005-tech-stack.md)) has no TOML writer, and a round trip would
reformat the file. `setup.py` is parsed with libcst: a declaration is a string
literal inside `install_requires`, `setup_requires`, `tests_require` or
`extras_require`, and any other string is not one.

### D9. The comment rule is per layout, because the layouts do not agree

- `requirements*.txt` and TOML: a `#` outside a quoted string starts a comment.
- `setup.cfg`: a comment only when `#` begins the line, as `configparser` and
  setuptools read it; a requirement with a trailing comment is invalid and is
  not read.
- `setup.py`: no comment rule; D8 excludes every other string.

A name is compared after `packaging.utils.canonicalize_name`, never as a
substring.

### D10. A lockfile is not a manifest in v0

v0 reads the five hand-written layouts plus the `requirements/<name>.txt`
directory form. A lockfile is generated, and a line edit would break its
hashes; `constraints.txt` declares no dependency.

### D11. An unread file is a limitation and not a blocker

A manifest is opened through `parse.contents`, with the source files' size limit
and `O_NOFOLLOW`; an unreadable one yields a `Limitation` row and no
declaration. An unreadable *source* file does not block the removal:
`repo_not_fully_migrated` claims a file imports the distribution, and an unread
file is the absence of that fact. A file read but not parsed does block (D3).

## Consequences

- ADR-005's cache key covers findings only. The manifest pass grades one file's
  pin on every other file's plan and on `.obelize.yml`'s exclusions, so it runs
  after every file is scanned and is not cacheable on that key.
- A `setup.cfg` requirement with a trailing comment is not reported (D9), which
  errs toward "no legacy pin"; `COVERAGE.md` and a test pin it.
- Under `dual` both imports stay, so "still imports" stops tracking what was
  rewritten; `survey` does not know the policy, and no fixture exercises it.
