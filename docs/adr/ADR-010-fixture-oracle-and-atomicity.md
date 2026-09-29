# ADR-010: Fixture oracle and atomicity

## Status

Accepted; amended by ADR-012 (F-1), ADR-013 (F-5, F-6) and ADR-014 (F-4, F-5).

## Decision

The fixture ground truth is written by hand before the code it grades, never recorded from it.

### F-1 — Import atomicity: a file is migrated completely or not at all

If any finding in a file is withheld, every otherwise-`auto` one is withheld too, with bail
`file_not_fully_migrated` and a `caused_by` naming the bails that fired
([ADR-012](ADR-012-file-atomicity.md)), and the file is left exactly as it was.
`google.genai` has none of the legacy top-level names, so a renamed import beside one
surviving legacy call imports cleanly and raises `AttributeError` on first use.

### F-2 — The manifest gains the new pin as soon as anything migrates, and loses the old one only when nothing needs it

`manifest_dependency` is two edits on one legacy declaration, graded repository-wide. Adding
`google-genai` is `auto` once any in-scope file migrates, because a partial migration needs
both distributions. Removing the legacy pin waits, with both pins kept and the files named,
while a file imports the legacy SDK (`repo_not_fully_migrated`) or imports an undeclared
distribution only the legacy SDK installed (`transitive_dependency_in_use`), because
un-pinning would break the install. A file matching the byte prefilter that the user's
`exclude` or a narrowed `include` removed is named and does not block; one the default
`include` leaves out blocks.

### F-3 — `count_tokens` may drop the sampling config, and must not drop the rest

The constructor's sampling parameters are dropped from `count_tokens` with the warning
`count_tokens_config_dropped`: a token count does not depend on sampling.
`system_instruction=` is counted, so it refuses the group as
`count_tokens_config_carries_semantics`; a constructor's `tools=` refuses it earlier, whatever
the call, as `afc_semantics_differ`.

### F-4 — The closed vocabularies live in the repository

`Finding.kind`, `Finding.confidence_reason`, the fixture `verdict`, and the bail and warning
codes are written out in [docs/SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) and held equal to
`models.py`, because three fixture defects were members invented where no list could be read.
The attested member is `manifest_dependency`, not `manifest_declaration`, and `not_a_usage`
is a `verdict`: a prose mention is neither an edit nor a review item.

### F-5 — `needs_review` never emits a hunk, so `.after.py` needs a label

A withheld finding (`needs_review`, `unsupported`) names a bail and emits no hunk; any other
names none (ADR-014 D6 exempts `model_proposed`). Every ground-truth file declares
`after_file_is`: `fix_apply_output` (each `.after.py` is byte-for-byte what `fix --apply`
writes; ADR-013 D3), `human_answer_key` (what a person would write, beyond the tool) or
`none`, so no harness infers whether a hunk is due.

### F-6 — `configure` → `Client` stays automatic and carries a warning

The rewrite is `auto`, but `Client(...)` validates the key at construction where `configure`
did not, so a module-level client whose credential keyword is not set to a non-empty string
literal carries `client_constructed_eagerly` (ADR-013 D5). Refusing every non-literal key would make
the one rule every repository needs manual.

### F-7 — C-22's positional arguments are mapped by index, not bailed

Positional constructor arguments are mapped against the legacy order `(model_name,
safety_settings, generation_config, tools, tool_config, system_instruction)` of 0.8.6, with the
warning `positional_args_mapped_by_index`; with the order known, a bail would gain nothing.

### F-8 — C-18's `await` is preserved, not inserted, and the branch is automatic

The legacy `generate_content_async` and the new `generate_content_stream` are coroutine
functions, so runnable legacy code reads
`async for x in await model.generate_content_async(p, stream=True)`; the rewrite keeps the
`await`, is `auto` and warns `async_stream_await_preserved`. Without the `await` the loop
already raises `TypeError`, and bails `async_stream_await_missing`.

## Consequences

- A partial migration whose tests pass is `partial` in [BENCHMARK.md](../BENCHMARK.md), never
  `verified_success`.
- [COVERAGE.md](../../tests/fixtures/scan/COVERAGE.md) records what the fixtures do not cover.
- The encoding fixtures are `-text -diff`; `tests/unit/test_fixture_encoding.py` fails on drift.
- Open: the `dual` import policy, keeping both imports instead of F-1, has no rule behind it.
