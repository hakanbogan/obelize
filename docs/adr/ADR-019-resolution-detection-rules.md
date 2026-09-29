# ADR-019: Resolution and detection rules

## Status

Accepted; amended by [ADR-020](ADR-020-impact-plan-ladder.md) (D8).

## Decision

### D1 — Analysis resolves; the planner decides. `BAILS` is the seam.

`scan/analysis.py` emits `Finding` rows and `Receiver` records and never
decides whether a file may be rewritten. `analysis.BAILS` holds the eight codes
a scan can see (§6's rungs 1 to 3 and `receiver_unresolved`), ranked by
`analysis.RUNG`; `impact/` raises the client rung and atomicity, which close
over verdicts not yet known. `tests/oracle/test_scan_against_the_oracle.py`
holds raised and graded codes, and each row's status and bail, equal.

### D2 — One finding per resolution *site*, and the arguments are still walked.

A site resolves to a legacy `IMPORT` name and its parent is neither a legacy
`Attribute` it links into nor the `Call` it is the callee of. Arguments are
still walked, so `basic/app.py:9` reports the constructor and the
`GenerationConfig` inside it. A `Call` site is `kind: call`, any other
`kind: attribute`.

### D3 — A mention is anchored to the line it occurs on, and no tokenizer reads it.

The sweep walks `Comment`, `SimpleString` and `FormattedString` nodes and
reports each match at the node's start line plus the newlines before it, since
`tokenize` cannot read the latin-1 and bare-CR fixtures. A line with another
finding carries no mention (§1).

### D4 — The hyphenated distribution name is never a source finding.

A mention is a dotted run that starts at a legacy module after a non-word,
non-dot character and continues in identifiers: `google-generativeai` is no
importable path, and a non-identifier segment would fail `Finding.symbol`.

### D5 — An unresolvable receiver is reported only where the file builds a legacy object.

`<expr>.<method>(...)` is `receiver_unresolved` when `<method>` is the supported
method of exactly one receiver in the spec, `<expr>` resolves to no legacy
binding, and at least one call in the file resolves to a constructor symbol.
Otherwise there is no symbol to name, as with a method two receivers share.

### D6 — A patch target is a legacy path that *is* a call argument, whole.

`mock_patch_target` fires on a string literal in argument position whose whole
value is a legacy-prefixed qualified name. Argument position, because a list of
patch callees would be behaviour a pack must carry (ADR-006); whole, because a
log message that starts with the prefix is prose.

### D7 — The pattern id covers four shapes; the confidence reason covers three.

The `dynamic_access` pattern id enables all four shapes that reach the module
without a resolvable import; the `dynamic_access` reason covers the three that
reach it by name (`importlib.import_module`, `__import__`, an assignment into
`sys.modules`). `getattr(<alias>, "X")` goes through a resolved name, so its
reason and bail are `module_alias_rebound` and the whole file is rebound.

### D8 — `method_returns` joins the pack, and a receiver nothing produces is a sixth incoherence.

`generative_model_calls.params.method_returns` maps a supported method to the
receiver it returns, because `ChatSession` has no constructor and only
`GenerativeModel.start_chat(...)` produces one. Each key must be a method of its
receiver, each value must have its own method list, no method may return its
own receiver, and every receiver in `methods` must be the `ctor_symbol` or a
`method_returns` value (ADR-018 D4); `ScanSpec` re-checks all but the third.

### D9 — A comparison operand is not an escape; everything else that is not a receiver is.

An escape lets the object reach code the rewrite cannot see: stored, returned,
passed, exported, or read for an attribute that is not a supported method. A
comparison operand captures nothing, so the scan grades its group eligible; a
bare truth test is an escape. Because the comparison outlives a deleted
constructor, `generative_model_calls` refuses the group as
`model_object_escapes` when a use line has fewer rewritten uses than references.

### D10 — A use's confidence reason follows the import form, by spelling.

The first segment as written decides: an alias bound with `as` is
`alias_resolved`, a name a `from` statement bound (`from google import
generativeai` too) is `from_import_resolved`, and anything else is
`direct_import_resolved`. It is total, and right in a file with two spellings.

### D11 — `conditional_binding` is a property of the import statement.

It fires on an import whose bound name has more than one `ImportAssignment` in
its scope, the try/except double import. When the second binding is an
ordinary assignment elsewhere, the import resolved and stays `alias_resolved`,
and the file takes the file-wide code instead. An import under
`if TYPE_CHECKING:` binds once and is ordinary.

### D12 — A conditional constructor still binds; a comprehension scope does not.

The assigned value is unwrapped through `IfExp` and `BooleanOperation`, since
`X = genai.GenerativeModel(...) if flag else None` still holds a model. A
`ComprehensionScope` binds nothing, as `Binding.scope` cannot spell one; its
constructor call is still reported.

### D13 — The corpus exclusions live beside the harness, never in the answer key.

`tests/oracle/harness.yaml` excludes every `*.after.*` answer key and
`encoding/_build.py`, whose byte literals hold the legacy import, with one `why`
each and a test that each matches a file, because a case that could exclude its
own files could pass by grading less. The harness also unquotes a mock target's
`symbol`, ignores `symbol` on a `parse_error`, and reads `verdict: auto` as
`scan_status: eligible`.

## Consequences

- Analysis has no dataflow through returns, by design, so D5 can report a false
  positive (`Anything().run(x)` beside a legacy constructor), as `needs_review`
  and never an edit.
- D5 covers method calls, not attribute reads (`COVERAGE.md` gap 20).
- D6 reports a patch target passed through a variable only as a mention (gap 17).
- D8's field defaults to empty; chaining deeper than one level is unexercised.
