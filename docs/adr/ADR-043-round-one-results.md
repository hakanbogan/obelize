# ADR-043: Round one results

## Status

Accepted.

## Decision

### D1 -- The work tree leaves the repository, and a guard keeps it out

Case checkouts live under `tempfile.gettempdir()/obelize-bench`, and a case errors with
`work_root_not_isolated` when any directory above its checkout holds a config a tool searches
upward for (`pyproject.toml`, `pytest.ini`, `.pytest.ini`, `tox.ini`, `setup.cfg`, `setup.py`,
`conftest.py`), because the suite would run under that configuration. The scan-only collectors
keep `bench/work/`.

### D2 -- A pytest run's exit code is read against pytest's table

For pytest, `0` is `pass`, `1` is `fail`, `2` is `fail` when the junit report counts a failure or
an error (an unimportable test module), and every other code is `inconclusive`. Other commands read
`0` as `pass` and the rest as `fail`; a timeout is `inconclusive`. So "the tests failed" stays apart
from "we never learned", as in `obelize verify`.

### D3 -- A published result carries no absolute path

Paths the harness chose become `<harness-python>`, `<case>`, `<logs>`, `<work>` or `<repo>` in the
recorded argv, in both the given and the resolved spelling, because results are public. A path a
repository wrote is data and stays.

### D4 -- The provenance records what the interpreter is, not only where it is

The provenance carries `python_executable` (elided) and `python_build` (`sys.version`, or `null`),
because only the build tells two machines' resolutions of one uv key apart. The result schema is
version 2; `bench/summarize.py` refuses any other.

### D5 -- A suite that ran nothing verifies nothing, and the skip count is published

Each test phase records `skipped`, and `verified_success` needs an after-run that executed a test
(a count above zero, or no junit report). Whether the covering test ran is still unchecked:
`tests/fixtures/scan/COVERAGE.md` gap 27.

### D6 -- The headline's second scope is reported per side too, and the case table totals

The headline is given over cases and unique `pattern_key`s, overall and per split, each with its
`n`; per-split pattern rows need not add up. The case table has a `Total` row, and a suite table
shows pass, fail and skip counts on both sides of the SDK swap.

### D7 -- A case definition is corrected only when the repository's own metadata says so

An install command gains only dependencies the repository itself declares, never one that merely
makes a suite pass, so the benchmark cannot be tuned per case.

### D8 -- The round is published whole, and the round that was thrown away is described rather than shipped

Every case and control is published, including those that produced nothing. An execution with
numbers known to be false is not committed beside its correction, only described: round one's
first execution ran inside this repository, where three suites took obelize's own pytest `addopts`,
collected nothing and were recorded as `fail`. D1 to D4 fix what it exposed.

## Consequences

- Logs are in `$TMPDIR/obelize-bench/<round>/<id>.logs/`, written `<logs>` in results.
- `bench/results/round-1/` is committed, so `bench/summarize.py --check` has data to check.
- A non-pytest suite gets only the `0`-or-not reading.
