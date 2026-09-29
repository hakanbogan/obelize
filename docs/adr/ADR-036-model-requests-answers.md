# ADR-036: Model requests and answers

## Status

Accepted; amended by ADR-039 (D6, D8).

## Decision

### D1. Three questions, in this order, and every withheld row gets an answer

A withheld row is consulted only if it passes all three, and the first failure
is its recorded `ConsultSkip`:

1. **Is it `needs_review`?** Else `not_needs_review`: an `unsupported` surface
   has no target to propose an edit into.
2. **Is it a source file this run could write** (the driver produced bytes and
   they parsed)? Else `not_a_source_file`, which covers manifests.
3. **Could a model repair its bail?** Three bails are exceptions, and every
   other `needs_review` bail is consulted: `file_not_fully_migrated` is
   `atomicity_only` (its `caused_by` rows are asked instead),
   `flag_only_surface` is `pack_refused` (the pack's decision, kept in data by
   ADR-006), `configure_consumed_elsewhere` is `consumed_elsewhere` (the defect
   is in the module still using it).

`ConsultSkip` has six words, these five and D3's `context_too_large`. Every
withheld row ends in a consultation or a skip, so the selection can be audited
by what it left out.

### D2. The context is the smallest scope that holds the whole binding group

For a finding at line *L*, the group is *L* plus the constructor and every use
of each `Binding` whose `ctor_line` is *L* or whose `use_lines` contain *L*. The
range is the smallest `FunctionDef` or `ClassDef` containing the whole group;
when none does, the group's span widened by `CONTEXT_MARGIN = 20` lines either
side, clipped to the file. Because a binding group is atomic, and half of one
cannot be answered.

### D3. One budget, and no truncation

`CONTEXT_LINE_LIMIT = 80` bounds both arms: a scope over it falls back to the
window, and when neither fits, **nothing** is sent and the row is skipped
`context_too_large`. Because a truncated range lets the guard's range check pass
a proposal written against text the model never saw.

### D4. One request per finding

Two findings in one group are asked separately, with the same context. Because
the `Edit` row, the report line and the guard's symbol check are all per finding.

### D5. A proposal is parsed for shape and trusted for nothing

`EditProposal.path` and `symbol` are plain `str` and `replacement` is any
text. Only the shape is validated: lines at least 1, the end not before the
start, and `path`, `symbol` and `rationale` not blank. Everything else is the
guard's (ADR-037). A reply that fails even this is unanswered, not refused.
Because a proposal naming `../../.bashrc` must be representable to be refused
by name.

### D6. `propose` is one call, and a provider that fails is not a run that fails

`ModelProvider.propose(Consultation) -> Reply` returns a proposal or `None` and
the endpoint's token counts; `request` returns the bytes it would send. No
session, state or batching: `consult` owns the loop, order and selection. A
`ProviderError` ends that consultation only; the row stays `needs_review`, the
failure is recorded, and the next row is asked.

### D7. `ModelProvider` is the protocol, and the configuration value is renamed

`ModelProvider` is ADR-003's protocol; the value of `model.provider` is
`ProviderName` (`PROVIDER_NAMES`). Because one name for two things is a defect.

### D8. Nothing calls `consult` yet

Superseded by ADR-039: `obelize fix` consults through `providers/proposals.py`.

## Consequences

- The context builder parses a file a second time, only when a row in it is asked about or shown by `--show-context`.
- A binding group spread too wide for either arm is a blind spot by construction (`tests/fixtures/providers/deep/long.py`); raising `CONTEXT_LINE_LIMIT` is one line.
- Open: one request per binding group would stop repeating a context per member, at the cost of every per-finding contract.
