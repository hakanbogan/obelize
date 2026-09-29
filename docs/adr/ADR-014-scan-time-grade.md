# ADR-014: The scan-time grade

## Status

Accepted.

## Decision

### D1. Each vocabulary is a `Literal` with a `frozenset` derived from it, and the document is asserted against the code in both directions

Each closed vocabulary is a `Literal` in `src/obelize/models.py` with its set derived by
`frozenset(get_args(...))`, so the two cannot disagree; not an `Enum` or `StrEnum`, because
each is a wire format of plain strings. `tests/unit/test_models.py` asserts that every
[SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) table, and its heading's member count, matches its
`Literal`; the fixture tests import the sets from the code.

### D2. A scan publishes `Finding.scan_status` (§10), never a verdict

A scan grades `eligible`, `needs_review`, `unsupported` or `not_a_usage`. `eligible` says only
that no scan-time rule withheld the finding; a fix-time rule may still refuse it, so `auto` at
scan time would promise a hunk. `run.json`'s `counts` split by §10 in `scan` mode and by §3 in
`plan` and `apply`, and a scan record carries no warnings: a warning accompanies an edit.

### D3. `Binding.kind` is §9, and its `scope` column is a contract

`name`, `module_const`, `self_attr` and `class_attr` are §9, each with its scope, and a binding
whose kind and scope disagree is refused: they are two spellings of one fact. §9 shares no
value with a finding vocabulary, and a test says so.

### D4. `symbol` is a resolved name and never a source excerpt; a `parse_error` carries none

A `manifest` finding's `symbol` is a PEP 503 distribution name, any other a qualified name,
and a `parse_error` has none, because it resolved nothing and ADR-008 bars source excerpts
from evidence. The model enforces both, so no harness normalises them.

### D5. The models refuse; they do not repair

`caused_by`, `warnings`, `use_lines` and every list in `ScanSpec` must arrive sorted and
de-duplicated, because sorting them on the way in would hide a determinism bug (C-11).

### D6. `model_proposed` is the one written edit that names a bail

ADR-010 F-5 holds for `ScanStatus` and `EditStatus`, except that `model_proposed` keeps the
bail the rules refused with and has no `rule_id`, so [ADR-003](ADR-003-model-adapter.md)'s
two benchmark arms stay apart. An `auto` edit requires `rule_id`, which traces it to the pack.

### D7. `findings.schema.json` is the first generated schema, and the only one this task emits

A JSON Schema is generated only from a model in the code, never from prose, as a row in
`src/obelize/schemas/generate.py`'s `SCHEMAS`. `findings.json`, also `obelize scan --json`'s
output, carries nothing time-derived, keeps its findings in document order and recomputes its
counts from them.

### D8. `ImpactPolicy.import_policy` exists from today, and its default does not move

`import_policy` is `atomic` (the default, ADR-010 F-1) or `dual`. The planner grades `dual`
for measurement and the codemod driver refuses it, as no rule implements it. It is not a
`ScanSpec` field: it is not the pack's, and [ADR-005](ADR-005-tech-stack.md)'s cache key
hashes only the pack and the file.

## Consequences

- `ci / schema-drift` runs unguarded: a missing generator fails the build.
- A test holds that importing `obelize.cli` loads neither pydantic, libcst, pyyaml nor
  `obelize.models`, so `--help` stays fast.
- Open: a second pack is the first test of whether `ScanSpec` is the right seam.
