# ADR-021: Dependency manifests and verdict

## Status

Accepted; amended by ADR-050 and ADR-053.

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
`include`, or when the user's `exclude` matches it, it is named as excluded and
blocks nothing. Neither is analysed.

### D4. Nothing migrated means nothing is added, and the pin is not touched

With nothing migrated the manifest is not edited. The legacy pin is withheld
with `repo_not_fully_migrated` while a file still imports it (D12 where one distribution holds
both APIs). Where nothing imports it, the pin is `manifest_code_mismatch`
(D5): the code has moved on and the manifest has not, and removing the pin
would edit a manifest for a migration this run did not make. It stays
`not_a_usage`, context only, where something else may still need it: a file the
user's `exclude` removed names the distribution, a module only it installs is
imported, or one distribution holds both APIs (a pin of it over new-SDK code is
`openai==0.28.1` beside 1.x code, which no row here can tell from a pin the code
still runs on).

### D5. `manifest_code_mismatch` is both directions, and it is a review item

A manifest that declares the new distribution and no legacy pin, while code
still imports the legacy one, is `manifest_code_mismatch`: `needs_review`,
never an edit, because the code is what must change. The "no legacy pin" clause
keeps the rule idempotent: F-2's own intermediate state declares both. A legacy
pin nothing imports (D4) is the same code for the opposite disagreement, and
also never an edit: a pin kept on purpose for another library reads this way
until it is removed.

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
(the pack's `match.transitive`) and no manifest of that file's app declares that module's
distribution: one in its directory or above it, a `requirements/` directory counting for the
directory it is in. Another app's manifest does not cover it, and a constraints file does not
declare: it bounds a version and installs nothing.

### D8. Lines, not a parse-and-serialise round trip — except for `setup.py`

A manifest is read as lines, and a finding records the line and the column the
name is written at, so the scan's address is the edit's. The dependency budget
([ADR-005](ADR-005-tech-stack.md)) has no TOML writer, and a round trip would
reformat the file. `setup.py` is parsed with libcst: a declaration is a string
literal inside `install_requires`, `setup_requires`, `tests_require` or
`extras_require`, and any other string is not one. A name there (`install_requires=REQS`, a list
element, an `extras_require` value) stands for the list, tuple or dict literal assigned to it
(`EXTRAS = {"ai": [...]}`), where one assignment binds the name, and the strings of that literal
are the declarations, edited where they are written; the names in it stand for theirs in turn. A
name bound twice, by an import, a parameter or an augmented assignment, or one given to a call
(`sorted(REQS)`), is not followed. A literal Python cannot evaluate (an invalid `\U` escape, a NUL)
declares nothing, and the rest of the file is read.

### D9. The comment rule is per layout, because the layouts do not agree

- Requirements files: a `#` at the start of a line or after a blank starts a comment, as pip reads
  it, so a `#egg=` fragment is part of its line. A line ending in a backslash goes on with the
  next (a comment line never does), and the options after a requirement (`--hash`) are cut
  before it is read. TOML: a `#` outside a quoted string.
- `setup.cfg`: a comment only when `#` begins the line, as `configparser` and
  setuptools read it; a requirement with a trailing comment is invalid, so it is known by its
  name alone (below).
- `setup.py`: no comment rule; D8 excludes every other string.

A requirement string PEP 508 refuses (`PyPDF2~=1`, `PyPDF2==1.*.*`, `PyPDF2 1.26`) is still a row,
for the name it starts with, with no pin and no version: the legacy version gate asks every row, and
a line it skipped could hide a pin below the floor. A line that starts with no name (`-e .`, a URL)
is no row, and neither is a Poetry or Pipenv table key that is no name.

A name is compared after `packaging.utils.canonicalize_name`, never as a
substring.

### D10. A lockfile is not a manifest in v0

v0 reads the five hand-written layouts plus the `requirements/<name>.txt`
directory form, and a requirements file is any `*requirement*.txt`. A constraints file and a
pip-tools input (`*requirements*.in`) are read for their declarations and never written: the
compiled file beside an input is what installs, and a declaration there has no pin, so the rule
refuses it with `manifest_pin_shape_unsupported`. A lockfile is generated, and a line edit would
break its hashes.

In `pyproject.toml` the arrays read are PEP 621's and PEP 735's, `[tool.uv] dev-dependencies`, every
group of `[tool.pdm.dev-dependencies]` and a Hatch environment's `dependencies` and
`extra-dependencies`; the tables are Poetry's and Pipenv's, whose value is a version string or an
inline table. A table that holds nothing but a `version` has its pin inside the quotes of that
string; with another key beside it (extras, a marker, a source) it has none, since those keys would
be carried to a distribution that may not have them, and the rule refuses it. A dependency given
as a table of its own (`[tool.poetry.dependencies.<name>]`) is named by its header and read for its
`version`, and never written: the name is on one line and the version on another, and an edit has
one line to a declaration, so the rule refuses it with `manifest_pin_shape_unsupported`.

### D11. An unread file is a limitation and not a blocker

A manifest is opened through `parse.contents`, with the source files' size limit
and `O_NOFOLLOW`; an unreadable one yields a `Limitation` row and no
declaration. An unreadable *source* file does not block the removal:
`repo_not_fully_migrated` claims a file imports the distribution, and an unread
file is the absence of that fact. A file read but not parsed does block (D3).

### D12. One distribution on both sides: any withheld row blocks

Where the new distribution is the legacy one (`manifests.coupled`), the survey is `paired`. No
import marks the old API, since `import openai` is in both, so a file blocks when it holds any
withheld row that is not `not_a_usage`, and D2's two edits are never two rows: a pin nothing blocks
is rewritten in place (`openai==0.28.1` to `openai>=1.109.1`), and one that is blocked is
`repo_not_fully_migrated`, or `transitive_dependency_in_use`, with no row to add, because the
declaration already names the new distribution. The driver then leaves every file as it was
([ADR-031](ADR-031-codemod-driver.md) D12). A declaration whose lowest admitted version is already in the new range has no row, and a legacy one
the rule cannot write in place is withheld by this plan, so the driver holds every file
([ADR-053](ADR-053-shared-module-migrations.md) D11 and D12). The reasons are in
[ADR-053](ADR-053-shared-module-migrations.md) D6.

## Consequences

- ADR-005's cache key covers findings only. The manifest pass grades one file's
  pin on every other file's plan and on `.obelize.yml`'s exclusions, so it runs
  after every file is scanned and is not cacheable on that key.
- A `setup.cfg` requirement with a trailing comment is not reported (D9), which
  errs toward "no legacy pin"; `COVERAGE.md` and a test pin it.
