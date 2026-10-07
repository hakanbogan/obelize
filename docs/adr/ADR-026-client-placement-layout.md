# ADR-026: Client placement and layout

## Status

Accepted; amended by ADR-050.

## Decision

### D1. The pack names the client class and both rungs of the naming ladder

`ConfigureToClientParams` carries `client_symbol` (`google.genai.Client`),
`client_name` (`client`) and `client_name_fallback` (`genai_client`), because
a rule that knew the target class or invented a name would carry the migration
in code ([ADR-006](ADR-006-pack-carries-no-code.md)). The whole path is
declared; only the leaf is emitted, through the name `rename_import` bound.

### D2. Two keyword *roles* are pack data too

`credential_kwarg` (`api_key`) is the keyword the new client validates at
construction, which D4 turns on; `credentials_object_kwarg` (`credentials`)
takes only an object, so a dict literal bails `credentials_shape_differs`. They
are one SDK's spellings, not facts about clients. The schema requires both in
`allowed_kwargs`; any other keyword, a positional or a splat bails
`configure_kwargs_unsupported`.

### D3. The client placement table

The rows are decided by where the module's client readers are: every call
rewrite `impact.planner.needs_client` picks, and every free function a running
rule writes as a call on the client (`Rule.client_readers`).

| The `configure(...)` is | Its module's call rewrites are | The client is | Name |
|---|---|---|---|
| a statement directly in the module body | anywhere except at module level above it | a module-level assignment where the `configure` was | `client` → `genai_client` → bail |
| a statement directly in a function's or method's body | all inside that same scope | a local where the `configure` was | the same ladder, against every name any scope in the file binds |
| a statement directly in an undecorated instance method's body | in other undecorated methods of that class, on the same first parameter | `self.client`, with `self` read off *that method's* first parameter | the same ladder, against every attribute the class already uses on that receiver, every name its body binds, and the same for its bases in this module; a class keyword or a base defined anywhere else takes both names |
| anywhere else | spanning scopes no single placement reaches | not written | `client_placement_ambiguous` |

"Directly" excludes an `if`, `try`, `with` or loop, where a reader could meet
an unbound name. Row 3 exists because a local in one method is invisible in
the others. Row 4 refuses rather than moving the author's setup, because
relocated code cannot be reviewed line by line; it also covers a `configure`
whose result is used or that sits inside another expression.

### D4. The warning is ADR-013 D5 read literally, on an applied edit

`client_constructed_eagerly` fires when the client is at module level and the
credential keyword is absent or not a non-empty string literal, because
`Client(api_key="")` raises where `configure(api_key="")` returned (ADR-010
F-6). It rides an `auto` edit: the rewrite is right and the runtime behaviour
changed anyway.

### D5. A rule says what it *consumes*; the context collects it

`Rule.consumes` is the set of legacy symbols a rule replaces whole, and
`RuleContext.build` unions it over the rules that will run, so `rename_import`
drops a consumed `from <module> import <name>` entry instead of bailing, and a
rule that will not run cannot make another drop an import. A statement whose
entries are all consumed becomes the module import, because the consuming rule
writes a call against the new module.

### D6. The rules run in the order the pack declares them, and now that matters

`registry.rules(pack)` returns the pack's declared order and a run uses it
(ADR-031 D1): `rename_import` first, because this rule emits `<alias>.Client(...)`
with the alias it bound. With no binding this rule bails `alias_collision`, the
import rule's code, so a pack that inverts the order refuses the file rather
than writing a wrong one.

### D7. Note 4 becomes an algorithm, and it gains the clause it never had

`src/obelize/transforms/layout.py` is `basic/ground_truth.yaml` note 4 as code:

1. A rewritten call is emitted multi-line when the source call was multi-line,
   when one of its arguments is, **or when the line it would make is wider than
   the pack's `layout.line_length`**.
2. Multi-line is one argument per line, one indent unit past the statement's
   own indent, with a trailing comma and the closing parenthesis back on the
   statement's indent. The unit is the file's own, which libcst infers.
3. The indent is recursive: a nested call that goes multi-line indents one unit
   past the line its own opening parenthesis is on.

Width is the whole emitted line, indent and trailing comment included, as a
formatter counts; for a call rewritten in place the rest of the line is read
off its source line (ADR-027 D10). Wrapping only adds breaks. A moved argument
keeps its value, keyword and inner comments, not its separators; a generated
one is written `k=v` (`layout.keyword()`). `tests/unit/test_layout.py` asserts
every answer key fits the width.

### D8. The gate-1 staleness guard moves from the pack's bytes to the projection

`bench/results/gate1/scan.json` records `spec_sha256`, the digest of the
`ScanSpec` projection without the pack's identity fields, and ADR-024's
`tests/unit/test_gate1.py` compares it with the shipped pack's, because a scan
reads only the projection and a rewrite-only pack edit cannot move a finding.
`pack_sha256` stays, naming the document measured.
`test_the_projection_digest_ignores_the_pack_identity_and_nothing_else` in
`tests/packs/test_pack_schema.py` shows every other projection field moves the
digest.

### D9. `layout.line_length` is one number, at the pack level, and it is 100

One number, because two rules disagreeing about one file's width would produce
a file no formatter agrees with. 100 is the width the hand-written answer keys
were measured at. It is pack data, not a constant, because the width belongs to
the user's repository.

### D10. The corpus runs both rules, and `complete` gets stronger

`tests/fixtures/transforms/configure_to_client/` is graded by running every
rule of the pack in order, because this rule emits a name the import rule
chose. `complete` therefore means every eligible finding is claimed by a rule
that exists, and the `.after.py` is what `obelize fix --apply` writes. The
`rename_import` corpus keeps grading one rule, so its refusals stay readable.

### D11. Two calls that start in the same column: the innermost wins

`configure(k)(x)` is two `Call` nodes at one position; the rule keeps the one
that ends first, compared on the whole end position, so the choice never
depends on dictionary order. That is the call the scanner found, and its parent
is a call rather than a statement, so D3's fourth row refuses it.

### D12. What this rule does not own

Not the call sites: the rules that replace them own them (ADR-025 D4). Not a
second `configure` in a module, or a module with none: those are
`multiple_configure_calls` and `client_source_unresolved`, withheld by the
planner before any rule is built.

## Consequences

- `client_placement_ambiguous` is a fix-time member of
  [docs/SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) section 4.
- A pack declares at most one `configure_to_client` change; a pack with two
  clients needs that relaxed and D3 extended to say which client a call reaches.
- Nothing reads the width from the user's repository (`.obelize.yml` or
  `ruff.toml`); that waits until somebody asks.
