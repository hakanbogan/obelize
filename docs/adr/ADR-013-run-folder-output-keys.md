# ADR-013: Run folder output keys

## Status

Accepted; amended by ADR-023 (D1) and ADR-032 (D1).

## Decision

### D1 -- `docs/RUN_FOLDER.md` specifies the run folder, and a test keeps it honest

[RUN_FOLDER.md](../RUN_FOLDER.md) is the contract for `.obelize/`, the `latest` pointer, the
run id and every `run.json` field; `tests/unit/test_run_folder_contract.py` holds it, the
models and `e2e.yml` equal in both directions. Its fixed choices: the run id
(`^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$`) sorts chronologically and is a legal Windows filename;
`latest` is a regular file written last, so it always names a complete run; `mode` is `scan`,
`plan` or `apply`; `file_edits` is what was written, never what was planned; `git_dirty` is
`false` outside git and `null` when git could not say (ADR-032 D11); no interpreter path is
recorded, because run folders get attached to issues, and no `--pack` path, which can lie
outside the repository; `limitations[].code` is closed as `models.LimitationCode`.

### D2 -- `model_proposed` stays, and the two vocabularies are declared different

`Edit.status` (§8) and the fixture `verdict` (§3) differ by exactly `not_a_usage`, which is
not an edit, and `model_proposed`, which no answer key may hold because the oracle is what a
proposal is measured against; a test asserts both. A case with `llm_tokens_in > 0` is a
separate benchmark arm, never in the model-free headline.

### D3 -- `after_file_is: fix_apply_output` is a per-file promise, and `encoding/` gets four keys

Every `<name>.py` with a `<name>.after.py` beside it must come out as that key byte for byte
and carries only `auto` findings; every other `.py` in the case must come out byte-identical,
so an `auto` finding in a file with no key fails the build. `encoding/_build.py` generates the
four keys from byte literals and asserts terminator, PEP 263 cookie, BOM and final newline,
input against output, from the bytes rather than through libcst, the thing under test.

### D4 -- the three dead surfaces are closed, each in the way that fits it

`--no-color` and `NO_COLOR` also silence typer's help and usage errors, decided in `main()`
before `app()`. `NO_COLOR` follows <https://no-color.org> (any non-empty value, even `0`), and
only the leading options are read, so a `--no-color` inside `--verify` is another tool's. A
pytest marker is declared only once a test wears it, and `--strict-markers` rejects any other.
Coverage is a 100% gate in `addopts`; an unreachable line carries `# pragma: no cover` with its
reason.

### D5 -- when `client_constructed_eagerly` fires, stated so it is countable

The warning fires when the rewritten `Client(...)` is at module level and its credential
keyword is not set to a non-empty string literal; that literal is the only exemption.
`tests/unit/test_fixture_vocabulary.py` reads "module level" off the fixture's own bytes (a
line not starting with whitespace), so a new fixture cannot opt out by omission.

## Consequences

- Every row in every oracle case must point at a line its file has, so a `must_not_report`
  row cannot slide onto another line unnoticed.
- The four keys fall under `.gitattributes`' `tests/fixtures/scan/encoding/*.py` glob, so
  their bytes survive a checkout.
