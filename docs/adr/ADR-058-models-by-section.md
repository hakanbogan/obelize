# ADR-058: Models by section

## Status

Accepted.

## Decision

`obelize.models` is a package of six modules, each importing only the ones before it in this
table, and its `__init__` re-exports every name they define. No import path and no committed JSON
Schema changed when `models.py` became this package.

| Module | Holds |
|---|---|
| `vocabulary.py` | Every closed vocabulary: the `Literal`s, the sets derived from them and the tables beside them |
| `fields.py` | The string types and validators the models share, and the frozen base they inherit |
| `scan.py` | `Finding`, `Binding`, `Edit`, `EditProposal`, the pack's `ScanSpec`, `ImpactPlan`, `ManifestPlan` and the findings document |
| `config.py` | `Config` and the verification and model settings under it |
| `verify.py` | A verification phase and the commands it ran |
| `run.py` | The plan, run, model, proposal and undo documents |

## Consequences

- `models.py` held 2,425 lines, which no reader could take in. A new vocabulary goes in
  `vocabulary.py`, a new document in `scan.py` or `run.py`, and a new module here needs its own
  ADR like any other.
- A private name lives with its only user (`_loopback` in `config.py`) or, shared, in `fields.py`.
- The vocabularies are still held equal to [SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md),
  [RUN_FOLDER.md](../RUN_FOLDER.md) and [CLI.md](../CLI.md) by `tests/unit/test_models.py` and the
  tests beside it, which import every name from `obelize.models`.
- `python src/obelize/schemas/generate.py` writes the same bytes as before the split.
