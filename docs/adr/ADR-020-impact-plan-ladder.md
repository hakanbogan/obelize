# ADR-020: Impact plan and ladder

## Status

Accepted; amended by
[ADR-021](ADR-021-dependency-manifests-verdict.md) (D9, D11) and
[ADR-031](ADR-031-codemod-driver.md) (D10) and ADR-050.

## Decision

### D1. `impact/dataflow.py` decides the group; `impact/planner.py` decides the file

`dataflow.py` derives a binding group's code from one `Receiver` record (binding
kind, `assignments`, `escape_lines`) and takes no `ScanSpec`. `planner.py` adds
the client rung and atomicity, which need a whole file's findings and the pack.
A group code that needed the pack would be a rule about the surface, not the
binding.

### D2. The client rung applies to a module's *call rewrites*, not to its findings

`client_source_unresolved` withholds only what the new SDK routes through a
client: the `configure` call, a constructor, and a read of a declared receiver.
A type import, an annotation through it and an identity-mapped enum member need
no client, so a type-only module with no `configure` stays `eligible`. The rule
is public as `planner.needs_client(finding, spec)`, because two of its answers
cannot be observed through a plan.

### D3. The module's client is counted over resolved `call` findings

A `configure` counts only when the finding's `kind` is `call` **and** its
symbol is the pack's `client_symbol`; a pack with none (a library with no client) counts no
`configure`, so no row waits for one. A `mock.patch("google.generativeai.configure")`
target is a string and introduces no client; counting it would give a test file
a client and a real module a spurious `multiple_configure_calls`.

### D4. A binding row names the group's own defect; a finding row names the ladder's

A withheld finding names [SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) §6's most
specific code. A `bindings` row is the record of the group: it names the
group's own code where it has one, and otherwise whatever withheld the group's
own lines. It never names `file_not_fully_migrated` (`Binding` refuses it), so
a closed-world group in a file withheld only by atomicity is `eligible`.

### D5. The three group codes have a declared order, and the oracle pins none of it

`class_attr_binding`, then `multiple_assignments`, then `model_object_escapes`,
because each makes the next moot: a constructor site v0 does not rewrite, then
an unknown referent (so the escape set is unknowable), then an escape, which
presupposes a resolved group. No fixture carries two, and the order changes no
outcome: all three are rung 5 and `needs_review`.

### D6. Atomicity reaches every otherwise-eligible row, and its causes are the graded ones

`file_not_fully_migrated` lands on every row that would otherwise be eligible,
not only the import, because
[ADR-010](ADR-010-fixture-oracle-and-atomicity.md) F-1 leaves the file exactly
as it was. `caused_by` is read off the **graded** findings after every other
rung has run, never off the binding table, so it names only rules that withheld
something.

### D7. A group claims its constructor and its uses, and never a line-mate

A finding belongs to a group when its line is the constructor's or a use's
**and** its symbol is the group's receiver or a member of it; a line match
alone would withhold a line-mate such as the `GenerationConfig(...)` handed to
the constructor. Where two calls of one method share a line, one through the
bound name and one through a function result, `ORDER` prefers the group's code
over `receiver_unresolved`; both are rung 5 and `needs_review`.

### D8. `local_import` is `scan/analysis.py`'s, at rung 3, and the row is one word wider

`local_import` fires when a legacy import is not a module-level statement,
class bodies included, and is raised by `analysis.py` (`analysis.BAILS`, rung
3), which holds the scope mapping. An import under `if TYPE_CHECKING:` is in
module scope (C-26) and does not fire. `multiple_assignments` is `dataflow.py`'s
and is `len(scope[name]) > 1` exactly, never a count of legacy constructors,
because a use of a name assigned twice may refer to neither.

### D9. `ImpactPlan` refuses a plan F-1 would leave half-applied

`ImpactPlan` refuses an eligible row beside a withheld one; the error names the
lines. A plan is one file's: every row names that file, findings are in document
order and bindings in constructor order. A `manifest` row is refused, because a
manifest legitimately carries an applied edit beside a withheld one; it belongs
to `ManifestPlan` (ADR-021 D6).

### D10. §6's ladder is one total order, in the module that compares them

`planner.ORDER` is the ladder most specific first, and `planner.LADDER` gives
each code's rung, reproducing `analysis.RUNG`, `dataflow.RUNG` and
`planner.RUNG`; a test asserts that `ORDER` covers exactly `LADDER` with rungs
that never decrease. `input_does_not_parse` is ranked here because
`scan/parse.py` compares no codes. Only scan-time codes are ranked: §4's
rewrite-time bails get no rung, and neither does `output_does_not_parse`, whose
gate is asked only of a file nothing else withheld (ADR-031 D5).

### D11. `tests/oracle/` asserts equality, and the deferred table is down to one row

The oracle asserts status, bail and `caused_by` (in order) for equality on every
graded row, and grades the binding table: kind, name, scope, constructor line,
use lines, verdict and bail. It has no ladder tolerance and no deferral table,
so a row moving to another code must change the answer key.

## Consequences

- A report that prints bindings beside findings must say that D4's two codes
  answer different questions; `REPORT.md` has no binding table yet, so the
  sentence is owed when one appears.
- Two same-method calls on one line are told apart by neither line nor symbol,
  so the group's code wins (D7).
