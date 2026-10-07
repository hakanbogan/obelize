# ADR-029: Free functions

## Status

Accepted; amended by [ADR-053](ADR-053-shared-module-migrations.md).

## Decision

### D1. The unit is one call, and a refusal is local to it

A free function holds no state, so `rewrite_call` has no group: each call it
claims is decided alone, and the other calls in the file are still rewritten
around one that refuses. ADR-010 F-1 withholds a file whose usages are not all
`auto`, so the mixed output never reaches a user's disk.

### D2. `positional_to_kw` is the legacy signature's parameters, and therefore the new call's arguments

Its order is the legacy positional order, so a positional argument is lifted
onto the name at its index; its membership is the set of arguments the new call
takes. `config_kwargs` is the other destination, and a keyword (or splat) in
neither is `unsupported_kwarg`: passing an unknown keyword through would be a
`TypeError` at the call under an `auto` report. A pack that omits a parameter
therefore refuses the calls that pass it. `keywords` is a third destination, for parameters carried
only when written as keywords: a positional argument beyond `positional_to_kw` stays
`positional_arg_ambiguous` (ADR-053 D4).

### D3. A configuration object arrives under a name the pack gives it

`config_kwarg` is the keyword the new call takes the configuration object
under. The schema requires `config_class`, `config_kwargs` and `config_kwarg`
together or not at all, since none can be emitted without the others. A call
that carries no configuration field gets no configuration object, which
nobody wrote.

### D4. Four coherence rules over the parameter lists, because a pack with no field evidence is checked by its schema

| Rule | What it would otherwise produce |
|---|---|
| A parameter is in one of `positional_to_kw`, `keywords` and `config_kwargs`, never two | A destination decided by the order of the rule's own tests |
| Every `arg_map` key is in one of those lists | A rename that never fires: the call is refused as an unsupported keyword first |
| No two parameters land on one keyword once `arg_map` is applied | A call naming one keyword twice, which Python refuses at compile time |
| Every `dispatch_prefixes` key is in one of those lists, and no list is empty | A guard nothing consults, or one that refuses every call |

### D5. A call whose answer is not the new call's answer is refused, and the pack states how it knows

`response_shape_changed`, stated three ways. Under `result_access_flags`
(`embed_content` returned a mapping; the new object's right reading depends on
the runtime type of `content=`) a call is written only where its result is
discarded. Under `dispatch_prefixes` (legacy `get_model` returned another class
for `tunedModels/...`; the new call returns `types.Model` for both) an argument
that is not a literal under a listed prefix is refused. Under `result_paths`
(a 0.28.1 result was a dictionary and a new one is not) a call is written only
where every read of its result is a listed attribute path (ADR-053 D5). A field
in `result_attribute_flags`, which the new result lacks, read off the result,
off the `for` or comprehension target or one name it feeds, or by `getattr`, is
`attribute_removed`.

### D6. The client bail is borrowed, and the scan's blind spot is written down rather than fixed here

A module with no client has nothing to make these calls on, and this rule
re-raises the client rule's code or the planner's `client_source_unresolved`
rather than name one defect twice. The client's placement counts every free
function a rule writes on the client (`client_readers`). The scan's
`needs_client` does not, so `obelize scan` over-states how migratable a
client-less module is; fixing it changes `spec_digest` and so waits for the
next re-run of the ADR-024 measurement (`COVERAGE.md` gap 21). A rule rooted on
the module has no client to place and raises neither (ADR-053 D3).

### D7. `positional_arg_ambiguous` covers both shapes of "which parameter is this"

More positional arguments than `positional_to_kw` names, and one parameter
given twice, are both `positional_arg_ambiguous`. Both are already a
`TypeError`, and mapping an argument onto a parameter the pack never named
would turn a loud failure into a silent one (ADR-027 D3).

### D8. `unsupported_kwarg` covers `resumable=` too, and C-47's proposed code is declined

`upload_file(..., resumable=True)` is `unsupported_kwarg`, like any keyword
with no counterpart; C-47's `upload_resumable_unsupported` is declined, because
the report already names the line and the keyword.

### D9. The layout algorithm is unchanged, and the configuration object has no source

The configuration object this rule emits has `source` `None`, since nothing
earlier laid its fields out ([ADR-026](ADR-026-client-placement-layout.md)
D7). Its indent is the one the outer call wraps to, and the outer call wraps
whenever the object does (`width_trigger.before.py`).

### D10. The pack's own answer keys are compared, not merely counted

`tests/packs/test_all_packs.py` runs the rules over every positive pack
fixture and compares each `<name>.after.py` byte for byte, which is
[PACK_SPEC](../PACK_SPEC.md)'s fixture contract; a key exists for exactly the
fixtures a run migrates whole.

## Consequences

- The development corpus used these four surfaces zero times (ADR-008 D6):
  their mappings are verified against the two installed SDKs only, and the
  pack's `limitations` says so.
- `get_file` and `delete_file` carry a `types.File` handle as well as a name; a
  handle of any other shape raises `ValueError`, which `limitations` records.
- The scan reports a subscript of a legacy name
  (`genai.embed_content(...)["embedding"]`) once, at the node inside it.
- Open: gap 21 (D6); whether `output_dimensionality` truncates as the legacy
  SDK did (the pack carries it as an ordinary configuration key); and the call
  the `files_surface.before.py` answer key wraps inside a comprehension, where
  `ruff format` would break the brackets.
