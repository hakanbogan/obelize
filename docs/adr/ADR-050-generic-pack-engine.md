# ADR-050: Generic pack engine

## Status

Accepted; amended by [ADR-053](ADR-053-shared-module-migrations.md).

## Decision

The engine knows no SDK. What a pack may say, and what the core assumes of one, is fixed by this
decision and widened only by a rule kind or a pack field that a second, real migration needs.

### D1. A field no code reads is deleted

A pack states only what a rule reads, so each of these goes:

- `changes[].preconditions` and `changes[].replacement`: no rule read either, and a vocabulary
  PACK_SPEC listed but the code never enforced is a claim a pack author would trust.
- `generative_model_calls.default_model_name`: a bare constructor bails with
  `default_model_name_required` whatever the pack names.
- The `dual` import policy, `ImpactPolicy` and the `policy` parameter through the planner, the
  runner, the reach pass and the driver. No rule keeps both imports, so the driver refused `dual`,
  and the rule's repeat of a binding's scan code (ADR-028 D12) could run under nothing else.
- `registry.consumed`, which only a test called.
- The codes `file_object_fields_not_verified`, `tests_touched_by_migration` and
  `stale_mock_target`, which no rule raised.

### D2. A client is optional

A pack declares at most one `configure_to_client`, and one when a change rewrites calls onto the
client (`generative_model_calls`, and `rewrite_call` unless its `root` is `module`, ADR-053 D3).
`ScanSpec.client_symbol` is `None` for a library with none: no row waits for a client, and the
driver's check of a `configure` another module relies on (ADR-031 D11) is skipped.

### D3. `rename_import` maps names, not the `types` submodule

`symbol_map` keys a symbol as `Name`, one of the module's, or `<submodule>.Name`, one of a
submodule in `submodule_map`; `alias_fallbacks` names the alias a submodule takes when the file
already binds its own name. A read through the module is rewritten to the new module's alias, and
a `from <module> import <name>` whose names all map to themselves stays a `from` import of the new
module. Anything else on that line stays `from_import_unmigrated_symbol`. Gemini's `types`
spellings are `types.`-keyed entries.

### D4. A pack says which Pythons its target installs on

`to.requires_python` is required. A repository declaring a Python that set excludes is blocked
(`runtime_unsupported`), asked of 2.7 and 3.0 to 3.29 one by one, so `>=3.7,!=3.9.*` is judged as
the set it is. The check lives in `scan/runtime.py` and reads the pack through `ScanSpec`; no
version is written in the core.

### D5. A pack's `from` floor gates the legacy pin

When `from.version` names a floor, every manifest declaring the legacy distribution must declare
that floor or above, and a repository that uses the library must declare it at all. Otherwise it
is blocked (`legacy_version_unsupported`): the pack's rules were measured above the floor. Neither
`requires_python` nor the floor changes a finding, so `spec_digest` leaves both out and a Gate 1
measurement stays bound to the spec it was taken on.

## Consequences

- The Gemini pack's sha256 changes; no scan, plan or oracle row does.
- A run folder written by 0.1.0 names `import_policy` in its plans, which a later release no longer accepts.
- `scan.blocked` replaces `scan.runtime`: a repository status names its file, its declaration and
  the set it had to stay inside.
- A vocabulary or pack-field change still lands with its documentation and schema in one commit.
