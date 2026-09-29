# ADR-024: Gate 1 measurement

## Status

Accepted; amended by ADR-026 (D9).

## Decision

### D1. The gate measurement is not a benchmark round, and it says so in the file it shares

The scan measurement has its own frame and keys (`bench/gate1/`), collector
(`bench/gate1_collect.py`), scorer (`bench/gate1_score.py`) and records
(`bench/results/gate1/scan.json`), and needs no SDK install or test run. Its
numbers live in the generated `gate1` block of
[BENCHMARK_RESULTS.md](../BENCHMARK_RESULTS.md#scan-precision-and-recall-gate-1),
under its own heading, because "how good is it" belongs in one file.

### D2. The answer keys are written before the scan, and committed

Every key under `bench/gate1/labels/` is written from the repository's source
before any `obelize scan` output for it exists, because a key written after the
output transcribes it. Only what
[BENCHMARK.md](../BENCHMARK.md#licensing-and-publication-rules) allows is
committed (URL, SHA, license, line references, notes), and the collector drops
`Finding.evidence`, so no source is vendored.

### D3. A row is its path, its line, its kind **and** its symbol

A finding on the right line naming the wrong symbol is one false positive and
one miss, because `obelize scan` prints the symbol. Rows compare as multisets,
so two findings sharing all four fields are two rows.

### D4. The rate is computed over four kinds, and the other five are published beside it

Precision and recall count `import`, `call`, `method_call` and `attribute`.
`text_mention`, `manifest`, `dynamic`, `star_import` and `parse_error` are
not call sites, so they are tabled apart against the count each key predicted.
Each key also lists `must_not_report` positions, where nothing may be reported.

### D5. Precision over zero findings is undefined, and is printed as `--`

`0 / 0` is not 1: a scanner that reported nothing would otherwise post perfect
precision.

### D6. A zero-bail file needs an actionable eligible finding and no withheld finding

Both halves are ADR-010 F-1 read back: one bail leaves the whole file
untouched, and an eligible `text_mention` qualifies nothing because no rule
acts on it. The count of repositories with at least one zero-bail file is what
decided Phase 2's scope.

### D7. Gate 1's three clauses are replaced by value sets, in the document

`docs/BENCHMARK.md` defines the rate's denominator, the two `confidence_reason`
sets that mean "cannot be resolved statically", and says the prefilter's
file-level precision (42.9%) is not a false-positive rate. A test asserts the
sets are disjoint vocabulary members that leave out exactly the four reasons
that are not a usage. `PRODUCT.md` keeps the gate's wording, because a change
to a gate is written where its readers are.

### D8. The frame is stratified on file size, and the drawn list is committed rather than the query

GitHub code search is relevance-ordered and favours short, simpler files, so
the draw is split into four file-size bands, allocated by population and
sampled systematically within each. The index changes daily, so
`bench/gate1/sample.yaml` commits the drawn list, the band populations and
every rejection; the development-corpus owners are excluded.

### D9. The scorer is offline, and a test recomputes what the document says

`bench/gate1_score.py` reads only committed files, so `tests/unit/test_gate1.py`
recomputes the published block on every CI run. It binds the records to the
shipped pack's `spec_sha256`, the digest of what a scan reads, and not to the
pack file's sha256, which a rewrite-only parameter moves. The scorer is under
the 100% branch gate; the collector clones repositories and is omitted from
coverage in `pyproject.toml`.

## Consequences

- Gate 1 is met, neither its `scan` fallback nor Phase 2's pre-registered
  narrowing fires, and the numbers are only in the generated block.
- `bench/` is under `mypy --strict`, and its pure half under the branch gate.
- A scanner change leaves the records describing an older scanner and no test
  notices; re-running `bench/gate1_collect.py scan` is manual.
- The one miss is open as `tests/fixtures/scan/COVERAGE.md` gap 20.
