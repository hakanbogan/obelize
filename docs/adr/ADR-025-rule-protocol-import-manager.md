# ADR-025: Rule protocol and import manager

## Status

Accepted; amended by ADR-026 (D2, D8, D10, D12).

## Decision

### D1. A rule claims findings, and a file a run writes is one where every eligible finding is claimed

`Rule.claims(finding)` names the findings a rule rewrites. A file with an
eligible finding no running rule claims is not written, and the driver reports
the row `usage_unmapped` (ADR-031). This is ADR-010 F-1 from the rule's side,
and it keeps a partial set of rules safe.

### D2. A rule records what it decided; `finish()` writes it, in one pass

`Rule.apply(context)` returns edits and records its decisions in
`context.rewrites` (nodes) and `context.imports` (statements);
`transforms.base.finish(context)` writes both in one walk, because libcst
rebuilds every node it walks, so a record keyed on node identity matches
nothing in a second pass. A replacement built from the original nodes is
walked again, so another rule's swap inside it still applies.

### D3. The metadata wrapper never copies, and the test demonstrates the no-op rather than describing it

A rule context's `MetadataWrapper` is built only by `RuleContext.build`, with
`unsafe_skip_copy=True`. `tests/unit/test_transforms_base.py` asserts that,
asserts the default wrapper copies, and shows a copying wrapper reporting
`auto` edits over a file that comes back byte-identical, because a guard for a
silent failure has to be shown failing.

### D4. `rename_import` owns the import statements and the `types` reads, and not a call site

It rewrites every module-level spelling of the legacy import (dotted, aliased,
`from <package> import <module>`, a submodule, `from <module>.types import
<symbol>`) and every read of a name a `types` import bound, string annotations
included. It never touches a call site's prefix, because the rule that owns
that call replaces it whole and D1 withholds the file until one does.

### D5. A name the author wrote survives; a name that is the legacy module's own spelling does not

`import google.generativeai as gai` becomes `from google import genai as gai`;
`from google import generativeai` becomes `from google import genai`. An alias
is the author's name for their own file; the module's own spelling is the
pack's to change.

### D6. An answer key exists for exactly the fixtures a run can migrate, and that is measured

`tests/packs/test_all_packs.py` reads `transforms.registry.IMPLEMENTED`, and a
positive pack fixture owes a `<name>.after.py` exactly when the codemod driver
writes it. A key no code can produce is ADR-010 F-4's defect.

### D7. An import statement and the references to the names it bound are one group

When the statement bails, the reads bail with it under the statement's code,
because a read rewritten to a name nothing binds does not run. The fixture
`types_names_all_taken` pins it.

### D8. The transform corpus lives outside `tests/fixtures/scan/`, and `complete` is computed

Transform cases live in `tests/fixtures/transforms/<kind>/` with an
`answers.yaml`, because a rewrite-time bail is an answer no scan can give. Each
case declares `complete`, true exactly when the rules run claim every eligible
finding and none bails, so the key is what `obelize fix --apply` writes; the
test computes it, and a `false` file says so in its own docstring. The
`rename_import` corpus runs that rule alone.

### D9. The module import is emitted only when a legacy reference survives this rule

A file whose only legacy use is a `types` symbol gets
`from google.genai import types` and no unused `from google import genai`.
Survival is read off the tree, not the plan, because a reference with no
finding (`genai.__version__`) still needs the name.

### D10. A `from <module> import <symbol>` line bails rather than guessing

An entry with no rewrite, such as `GenerativeModel`, bails
`from_import_unmigrated_symbol`. An entry whose symbol a running rule consumes
is dropped instead, and the module import takes its place (ADR-026 D5).

### D11. The import manager owns three things, and applying is deferred

`transforms/imports.py` answers which names are taken (every name any scope in
the file binds, so a local cannot capture a rewritten call), hands out the
first free name of the pack's preferred-then-fallback pair, and holds anchored
replacements until `finish()`; what to import is the rule's. A replacement is
built from the statement it replaces, keeping its blank lines and comments,
and extra imports follow it. Only an import that runs is reused or anchored
to; one bound only under `if TYPE_CHECKING:` is refused
`types_import_typing_only`.

### D12. The layout rule is rewritten by the task whose output it decides, which is not this one

`basic/ground_truth.yaml` note 4's layout algorithm is ADR-026 D7, written
with the first rule that emits an argument; every statement `rename_import`
emits is one import on one line, so it needs only D11's placement.

## Consequences

- No two rules edit one node, so no conflict policy exists; the first pair
  that must is the reason to write one.
- `types_symbol_map` is tied to the `types` submodule by the schema; a pack
  with a second submodule carrying symbols needs it generalised first.
- `tests/unit/acme.py` reaches what the Gemini pack cannot: a `default_alias`
  that is not the module's last segment, and a second submodule.
