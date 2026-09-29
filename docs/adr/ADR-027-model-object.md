# ADR-027: The model object

## Status

Accepted.

## Decision

### D1. The pack says which methods this rule rewrites, and one it does not name is not a bail

`params.methods` lists the methods the scan recognises on a model;
`params.rewrites`, keyed by legacy method, says where each went (service,
streaming form, arguments, configuration keyword). A method in `methods` and
not in `rewrites` is written by no rule: its finding is claimed by nobody and
ADR-010 F-1 leaves the file as it was. No bail code means "not written yet",
because the vocabulary describes the user's code. A `stream=` that is not a
literal `True` or `False` is `dynamic_stream_flag`: the two call different
methods.

### D2. The constructor is deleted and what it held is copied into every call

The constructor statement goes with the blank line above it; the model name is
folded into each call as `model=` and the configuration is rebuilt at each call
site. A copy must mean the same at the call: nothing in it may run (a call, an
`await`, a comprehension) and each name in it must have exactly one
assignment, the same one at both places; otherwise the group is
`ctor_argument_not_portable`. A shared configuration is not hoisted, because
that invents a name and a scope no pack parameter gives (ADR-006). A
constructor with no model name is `default_model_name_required`, because the
legacy default names a retired model (C-21).

### D3. Positional arguments are mapped by index, and an explicit `None` is not given

Positional constructor arguments map through the pack's `ctor_order`, the
legacy order in which `safety_settings` precedes `generation_config` (ADR-010
F-7, C-22), and one past index zero warns `positional_args_mapped_by_index`. A
literal `None` counts as not given, because every legacy parameter defaults to
`None` and it is how a caller reaches a later positional. More positionals
than the order names, or one parameter given twice, is
`positional_arg_ambiguous`: already a `TypeError`, which a mapping would turn
into a silently wrong model.

### D4. Two shapes go in, one class comes out, and the field order is the destinations'

The configuration is read from the legacy configuration class (by
`legacy_config_symbol`, which this rule claims, or through `types` by
`legacy_config_aliases`, which the import rule renames) or from a mapping
literal. A key outside the fifteen in `generation_config_keys`, and any other
shape (a name, a computed call, a splat, a non-literal key), is
`generation_config_not_static`, because the unvalidated mapping is how `seed`
reached the server (C-23). Fields are emitted as the constructor parameters in
legacy order, then the configuration's keys as written (then the safety table,
ADR-028 D6). A call's configuration merges over the constructor's key by key, as
the legacy SDK did.

### D5. The token count drops the configuration, and the one keyword that stops it

`count_tokens` drops the constructor's configuration and warns
`count_tokens_config_dropped`, because `types.CountTokensConfig` has no field
the legacy `generation_config` maps onto and sampling does not change a count
(ADR-010 F-3). A keyword in the method's `semantic_kwargs`
(`system_instruction`, which is counted) refuses the group
`count_tokens_config_carries_semantics` instead.

### D6. A rule may ask the import manager for a module, and the manager decides the name

The rule that owns the import statements calls `offer(module, prefer,
fallback)` for every submodule its pack maps, whether or not it emits one; any
rule that needs a name calls `require(module)`, which returns the bound name or
introduces the import, anchored to the legacy statement that caused it. So one
pack fact lives in one place. When `require` gives no name the caller raises
the manager's reason: `alias_collision` when no candidate name is free.

### D7. A group whose uses are not all rewritable is refused whole

A binding group is atomic (ADR-006): a model also read through a method with no
rewrite refuses the whole group `receiver_method_unmapped`, and a reference to
it that no rewritten call replaces (such as a comparison with `None`) refuses it
`model_object_escapes`, because deleting the constructor would leave that use
reading a name that no longer exists. Declaring a method without a rewrite is
how a pack says "recognise this, do not touch it", so the code is permanent.

### D8. The client is a property of the file, recorded by whichever rule introduces it

`configure_to_client` records on a `RuleContext` slot the client expression it
bound (`client`, `genai_client`, `self.client`), so no rule imports another.
When the client could not be introduced, the slot carries that rule's code and
this rule re-raises it, because one defect gets one name
([ADR-012](ADR-012-file-atomicity.md)).

### D9. Nothing is recorded until nothing can refuse

Every refusal of a group is asked before any replacement is written into the
context, because recording as it went would leave a half-rewritten group (D7).
`imports.require` comes after every other refusal and before the first record:
it reserves a name, and earlier it would leave an unused import in a refused
file.

### D10. The width a call is measured at is read off its source line

ADR-026 D7 measures the emitted line. This rule replaces an expression inside
the author's statement (`for chunk in model.generate_content(...)`,
`return model.count_tokens(p).total_tokens`), so everything on the source line
that is neither the call nor the indent is counted as it stands; for a call the
author already split across lines that rest counts zero, since it wraps anyway.

### D11. A comment above a deleted statement moves to the statement that now comes first

A comment above the constructor is the author's prose and has nowhere else to
go. The next statement keeps its own blank lines and gains the comment alone; at
the end of a block the comment keeps the blank lines above it too and goes
before the block's own footer. A commented constructor is not refused, because a
comment above a model constant is ordinary.

### D12. C-56 is a refusal about the answer, not about the call

`response.text` raised `ValueError` with no parts and now returns `None`, so a
handler for it never runs. The group is `response_shape_changed` when an
attribute in `response_attrs_now_none` is read, on the call's result or a name
it was assigned to, inside a `try` whose handler names `response_legacy_error`.
A bare `except:` does not count: it is no evidence anyone relied on the
exception. The schema requires both fields or neither.

### D13. A fix-time bail's order is the rule's, and it is not on the scan's ladder

The merged ladder in `impact/planner.py` exists so two scan-time passes cannot
disagree about one finding; a transform rule raises one code per group and
compares none. It declares its own order where it raises them: the client, the
group's shape, the constructor, each call in closure order, the response reads,
then the copied expressions. The client is a rung above the group, and a group
nothing can rewrite makes its constructor's arguments moot.

## Consequences

- `tests/fixtures/scan/basic/app.after.py` and the four
  `tests/fixtures/scan/encoding/` answer keys are produced by rule, byte for byte.
- `tests/unit/test_generative_model_calls.py` runs the rule against an invented
  SDK that spells every pack parameter differently.
- The rule reads the names the import rule reserves and the client the client
  rule places, so it runs after both (ADR-031 D1).
- Open: D2's copies stand until a measurement shows how often one model is read
  from many call sites; `positional_arg_ambiguous` may go if the benchmark never
  sees it.
