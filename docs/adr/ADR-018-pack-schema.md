# ADR-018: Pack schema

## Status

Accepted; amended by [ADR-019](ADR-019-resolution-detection-rules.md) (D8) and
[ADR-025](ADR-025-rule-protocol-import-manager.md) (D6), ADR-050, ADR-051 and ADR-053.

## Decision

### D1. The pack declares every v0 surface now, because `changes[]` is what the *scanner* reads

`packs/loader.to_scan_spec()` projects the scanner's inputs (client symbol,
constructors, methods, removed attributes, flag-only symbols and patterns) out
of `changes[]`, so it describes everything the migration touches; whether a kind
can be applied is `transforms.registry`'s to say.

### D2. A positive fixture ships its input; the answer key arrives with the kind that produces it

A positive fixture owes a `<name>.after.<ext>` exactly when obelize's own
driver, run on that fixture alone, migrates it whole (a manifest's key comes
with its rule). `tests/packs/test_all_packs.py` computes this from a run, not a
list, because a key no code can produce is a claim no test can check. It also
holds the declared fixtures equal to the files on disk, every `.py` fixture
through the input gates, and a prefilter token in every positive fixture and no
negative one.

### D3. A fixture path's shape is validated when a pack is read; its existence is a review gate

The shape (relative, forward slashes, under `fixtures/`, no `..`) is a
path-traversal question (TM-1). Existence is checked by `tests/packs/` for this
repository's packs only, so a working local pack is never refused;
`obelize pack validate` says which half it checked.

### D4. Coherence is refused, not assumed

Six cross-field rules, because each defect would otherwise be a scan that finds
nothing and reads like a clean repository:

| Rule | The defect it turns into a field error |
|---|---|
| Every legacy symbol a rule names is under some `match.imports` module, or under a `match.symbols` entry when `match.shared` says the module is the new SDK's too | A typo makes the rule unreachable |
| Every `match.imports` module contains some `prefilter_token` | A prefilter that drops every file the pack is about |
| At most one `configure_to_client` change, and one when a change rewrites calls onto the client | `ScanSpec.client_symbol` is one module-wide answer, absent for a library with no client |
| A symbol is rewritten or refused, never both | List order, which no reader sees, would decide |
| A `manifest_dependency` rule names the two distributions the pack migrates | A third distribution is not this migration |
| Every receiver in `methods` is the `ctor_symbol` or the value of a `method_returns` entry (ADR-019 D8) | Methods on a receiver nothing produces never resolve |

Inside one change, a `symbol_map` may not map a symbol a `flag_only`
rule refuses, and `config_kwargs` needs a `config_class` to carry it. A shared
module needs `symbols` and has no `rename_import` change, a `rewrite_call`
parameter has one destination among `positional_to_kw`, `keywords` and
`config_kwargs`, and `result_paths` excludes `result_access_flags` and lets no path continue another, and `arg_map` may not rename a parameter onto `config_kwarg` ([ADR-053](ADR-053-shared-module-migrations.md)).

### D5. Version ranges are compared only where they are comparable

Only when `from.package` and `to.package` canonicalise to one distribution (a
pack may name the same one on both sides, as `openai/openai-0-to-1` does): a
version either side names that both admit is an overlap, and a target ceiling at
or below the source floor is backwards. Across two distributions a rename may
keep its version. Neither test is a full specifier intersection, which `!=` and
`~=` make disproportionate, and a wildcard such as `1.*` names no version and is
skipped.

### D6. A pack's prose is display text, and that is a security property

`message`, `suggestion`, `citation` and every `limitations` entry are
`DisplayText`: at most 500 characters and no `Cc`, `Cf` or `Cs` character, so an
ANSI escape, a `\r` or a `U+202E` cannot make a displayed command read as
another. They are refused, not stripped, so the text shown is the text the
evidence's sha256 attests. `verification.suggestions` never runs, so it is not
validated as a command.

### D7. One primary source, a per-claim `SOURCES.md`, and the measurement outranks the page

`source` is one mapping whose `type` is `official_guide` or `sdk_reference`;
its `sha256` is optional, as a fabricated hash is worse than none. `SOURCES.md`
has one section per `changes[].id`, asserted both ways. What moved is cited to
the guide, which exact names are legal to a measurement; where they disagree,
the pack carries the measurement and `SOURCES.md` says so.

### D8. Five amendments to PACK_SPEC, each with a measurement behind it

Measured on google-generativeai 0.8.6 and google-genai 2.24.0:

1. `flag_only` has a third channel, `attributes`, whose bail is
   `attribute_removed` rather than `flag_only_surface`.
2. `GenerativeModel.tools` and `.tool_config` are not flag-only symbols, as
   `tools=` is a constructor keyword; the pack flags the four function-calling
   `types` classes that exist, `generative_model_calls` bails on a constructor
   passing either keyword, and a limitation records the flipped
   automatic-calling default.
3. The PaLM-era surface (`generate_text`, `chat`) has no rule: it is already
   absent from 0.8.6, which a limitation records.
4. Safety-table keys are lower case, one spelling per key, as the legacy lookup
   lowered its input.
5. A fixture is `<name>.before.<ext>`, because the manifest rule's fixture is a
   `requirements.txt`.

### D9. The SDKs a pack names are development dependencies, so the fact checks are never skipped

The Gemini safety tables are asserted against the `HarmCategory` and
`HarmBlockThreshold` `__members__`, never by construction, which accepts a wrong
name with a `UserWarning` (the test runs it as a control), and the PyPDF2 pack's names are read
from both installed modules (ADR-051 D2). The wheel gains nothing.

### D10. `obelize pack validate` ships here, with T6, and takes an id or a path

It takes `<id|path>`, like every other `--pack`. It exits `2` when there is
nothing to read, `7` for a pack read and rejected, and `1` for a bundled pack
that fails, which is a defect in obelize.

## Consequences

- The Gemini pack declares sixteen changes, and the registry implements every
  kind they use.
- `tests/packs/_negative/` holds one generated pack per documented refusal,
  each one edit from a valid document.
- `pack.schema.json` lets a pack be checked without installing obelize, and
  `ci / schema-drift` keeps it equal to the model.
- Open: a second primary source makes `source` a list; remote packs need
  signing and a trust policy (ADR-006).
