# MigrationPack specification

_The schema is `src/obelize/packs/schema.py`, and `src/obelize/schemas/pack.schema.json` is generated
from it; `tests/packs/` holds this document's vocabularies and refusals equal to it. Decisions:
ADR-006, [ADR-018](adr/ADR-018-pack-schema.md)._

A MigrationPack declares one migration between two versions of one SDK: which
symbols to find and which rule kind handles each. How a rewrite is done lives in
Python, in a fixed registry of rule kinds. A pack is **untrusted data**
(boundary B1 in [THREAT_MODEL.md](THREAT_MODEL.md)), parsed by a closed
pydantic model (`extra="forbid"`) and never executed, templated or run as a
command.

## Hard rules

Breaking one rejects the pack.

1. **No executable content**: no shell, Python, expressions, templates or
   fetched URLs. Every value is a literal, a fully-qualified symbol or a member
   of a fixed vocabulary.
2. **`verification.suggestions` is display-only**, never run
   ([CLI.md](CLI.md#trust-rules-for-verification-commands)).
3. **A replacement symbol is fully qualified**, matching
   `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$`.
4. **Validation errors are field-level**, naming the key's YAML path and what
   was expected.
5. **The pack is evidence**: `pack.yaml` is copied into the run folder and its
   sha256 written to `pack.sha256` and `run.json`.

## Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | `<provider>/<from>-to-<to>`, e.g. `gemini/google-generativeai-to-google-genai`; what `--pack` takes. |
| `pack_version` | string (semver) | yes | See [pack_version semantics](#pack_version-semantics). |
| `provider` | string | yes | E.g. `gemini`. |
| `language` | string | yes | `python`. |
| `source` | mapping | yes | See [Source provenance](#source-provenance). |
| `from` | mapping | yes | `package` (distribution name) and `version` (PEP 440 specifier, e.g. `"<1"`). |
| `to` | mapping | yes | Same shape, e.g. `">=1"`. |
| `match` | mapping | yes | `imports` (module paths, non-empty), `symbols` (qualified names), `prefilter_tokens` (a file with none is skipped unparsed), `transitive` (module to distribution, for modules only the legacy distribution installed: while a file imports one and no manifest declares its distribution, the legacy pin stays). |
| `changes` | list | yes | See [Change entries](#change-entries). |
| `layout` | mapping | no | `line_length` (40-320, default `100`). See [Layout](#layout). |
| `verification` | mapping | no | `suggestions`: displayed, never run. |
| `limitations` | list of strings | yes | What the pack knowingly does not handle; copied into the report. |

### Source provenance

```yaml
source:
  type: official_guide
  url: https://ai.google.dev/gemini-api/docs/migrate
  retrieved_at: 2026-09-16
  sha256: "<sha256 of the retrieved page>"
```

- `url` (**https**, with a host and no credential, since the host goes into the
  report) and `retrieved_at` are required. The URL is never requested.
- `type` is `official_guide` or `sdk_reference`, the sources pack review
  admits.
- `sha256`, optional, hashes the page as retrieved so a reviewer can see it
  change. An absent hash beats a fabricated one.
- The pack's `SOURCES.md` has **one section per `changes[].id`** (both
  directions checked by `tests/packs/test_all_packs.py`) giving the URL,
  `retrieved_at`, page hash and a short quotation, never the whole page. *What
  moved* is cited to the guide; *which names, keys or orders are legal* to a
  measurement against both installed SDKs, because a refusal needs a closed set
  and the guide gives examples.

### Layout

```yaml
layout:
  line_length: 100
```

The rewrite's wrap width, set to the migrated repository's formatter limit so
the formatter does not rewrite the diff. One number per pack, never per change.
[`src/obelize/transforms/layout.py`](../src/obelize/transforms/layout.py) owns
the layout: a rewritten call goes multi-line when the source call was, when an
argument is, or when the whole line (indent and trailing comment included)
would exceed the width; then one argument per line, one indent unit (the
file's own) past the statement, with a trailing comma.

### Change entries

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique in the pack; appears as `Edit.rule_id`. |
| `kind` | enum | yes | A rule kind below. |
| `params` | mapping | yes | That kind's parameters, validated per kind with `extra="forbid"`. |
| `preconditions` | list of enum | no | Informational; the rule enforces them. |
| `citation` | string | yes | The source guide section. |
| `fixtures` | list of paths | yes | See [Fixtures](#fixtures). |
| `replacement` | string | no | One fully-qualified replacement symbol, for kinds that take one. |

## Rule kind registry

The six kinds are closed in `src/obelize/packs/schema.py`; a pack cannot add
one. All six are implemented: `registry.IMPLEMENTED`
(`src/obelize/transforms/registry.py`) equals the schema's set, and
`tests/packs/test_all_packs.py` reads the registry. A method listed in
`generative_model_calls.methods` but absent from `rewrites` is recognised, and
the group that calls it is withheld as `receiver_method_unmapped`.

| kind | pack parameters |
|---|---|
| `rename_import` | `from_module`, `to_module`, `default_alias`, `submodule_map` (`types` -> `google.genai.types`), `types_symbol_map`, `types_alias_fallback` |
| `configure_to_client` | `legacy_symbol`, `client_symbol` (fully qualified), `client_name` and `client_name_fallback` (tried in order), `allowed_kwargs`, `credential_kwarg` (validated by the new client at construction) and `credentials_object_kwarg` (an object where the legacy call also took a mapping) |
| `generative_model_calls` | `ctor_symbol`, `methods` map, `method_returns` map, `generation_config_keys`, `config_class`, `default_model_name` (**required**), `legacy_config_symbol`, `legacy_config_aliases`, `legacy_config_kwarg`, `ctor_order` (legacy signature order, **not** sorted), `ctor_model_kwarg`, `ctor_config_fields`, `ctor_afc_kwargs`, `model_kwarg`, `stream_kwarg`, `model_name_prefix`, `rewrites`, `response_attrs_now_none`, `response_legacy_error`, `legacy_error_modules`; `safety` (`legacy_kwarg`, `legacy_category_key`, `legacy_threshold_key`, `legacy_category_class`, `legacy_threshold_class`, `category_map`, `threshold_map`, `category_members`, `threshold_members`, `setting_class`, `category_class`, `threshold_class`, `category_kwarg`, `threshold_kwarg`, `config_field`) and `history` (`role_key`, `parts_key`, `text_key`, `roles`). A `rewrites` entry: `new_call`, `root`, `stream_call`, `positional_to_kw`, `arg_map`, `afc_kwargs`, `history_kwarg`, `contents_kwarg` (what the model is asked; a list of turns is reshaped), `coroutine`, `config_kwarg`, `semantic_kwargs` |
| `rewrite_call` | `legacy_symbol`, `new_call` (dotted path under the client), `arg_map`, `positional_to_kw`, `config_class`, `config_kwargs`, `config_kwarg`, `result_access_flags`, `result_attribute_flags` (fields the new result lacks; reading one is `attribute_removed`), `legacy_error_modules`, `dispatch_prefixes` |
| `flag_only` | `symbols` / `patterns` / `attributes`, `message`, `suggestion` |
| `manifest_dependency` | `from_name`, `to_name`, `to_spec` |

**`legacy_error_modules`**: a rewritten call in a `try` whose handler names an
exception from one of these modules is refused as `error_class_changed`; the
new SDK never raises it, so the handler would never run.

**`rewrite_call` carries only what its two lists name.** `positional_to_kw` is
the legacy parameter order and the new call's own arguments; `config_kwargs`
go into `config_class`, passed as `config_kwarg`. Any other keyword is
`unsupported_kwarg`. The schema checks that no parameter is in both lists,
every `arg_map` key is in one, no two parameters map to one keyword, and every
`dispatch_prefixes` key is read by the rule.

**`dispatch_prefixes`** is for a legacy call whose return type depended on its
argument: `google.generativeai.get_model` returned different dataclasses for
`models/...` and `tunedModels/...`, while `client.models.get` always returns a
`Model`. It lists **literal prefixes** (never patterns) whose result the new
call reproduces; any other argument is `response_shape_changed`. With
`result_access_flags` (the result's type changed: `embed_content` returned a
mapping, now an object), any use of the result is `response_shape_changed`, so
the call is rewritten only where its result is discarded; the flags record the
reads the legacy result allowed.

**`flag_only`** never edits code: it reports a finding with a message and a
suggestion, for anything that is not 1:1. Its channels:

| Channel | Names | Bail it produces |
|---|---|---|
| `symbols` | A qualified legacy symbol. | `flag_only_surface` |
| `patterns` | A *shape* that is not a name at all, such as a string handed to `mock.patch`. | `flag_only_surface` |
| `attributes` | A dotted attribute path the new object does not have. | `attribute_removed` |

`flag_only.patterns` holds shape ids, **never regular expressions** (hard rule
1). The set is declared in `src/obelize/models.py`; `tests/unit/test_models.py`
holds this table equal to it.

| Pattern id | Matches |
|---|---|
| `mock_patch_target` | A `mock.patch("google.generativeai...")` target string. |
| `dynamic_access` | The legacy module reached through `getattr`, `importlib.import_module` or `__import__`. |
| `sys_modules_stub` | An assignment into `sys.modules` under the legacy module's name, which replaces the module for every later importer. |

The first two are also `confidence_reason` values
([SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §2); a test pins `sys_modules_stub`
as the only id that is not. The `dynamic_access` id enables four shapes:
`importlib.import_module("...")`, `__import__("...")` and assignment into
`sys.modules[...]` get reason `dynamic_access`, while `getattr(<alias>, "X")`
goes through a resolvable name, so it is `module_alias_rebound` and marks the
whole file rebound, graded by
`tests/fixtures/scan/escapes/dynamic.py`.

The scanner reads the union of all `flag_only` channels, so each refused row
gets an edit whose `rule_id` names the refusing change: the only link from a
report line to its message and suggestion. A resolved name is
claimed by `symbols` or `attributes`, a `dynamic` or `text_mention` finding by
`patterns`, so no refusal is reported twice.

**`manifest_dependency.to_name` is written verbatim**; PEP 503 folding only
decides whether two names are one distribution. A declaration whose rewrite
would drop or duplicate something (extras, a direct URL, a non-version table
value, a duplicated key or declaration) is `manifest_pin_shape_unsupported`
and left alone.

### Parameter constraints fixed by the Phase 0 spikes

Binding: each prevents code that imports cleanly and is silently
wrong.

**`generative_model_calls.method_returns`** maps a method to the legacy
receiver its result is (Gemini: `GenerativeModel.start_chat` to
`ChatSession`). `ChatSession` has no constructor, so without it
`chat.send_message(...)` resolves to nothing and the file reads as clean. Each
key must be a method of its receiver, each value must have its own method
list, and no method may return its own receiver.

**`generative_model_calls.default_model_name` is required**: legacy
`GenerativeModel()` defaulted to `gemini-1.5-flash-002`, and the new call
requires `model=`. That model is retired, so a bare `GenerativeModel()` is
`needs_review`, never silently filled in.

**`generation_config_keys` is exactly the 15 `protos.GenerationConfig`
fields**, all verbatim on `google.genai.types.GenerateContentConfig`:

```
temperature, top_p, top_k, max_output_tokens, stop_sequences, candidate_count,
response_mime_type, response_schema, presence_penalty, frequency_penalty,
enable_enhanced_civic_answers, logprobs, response_logprobs, response_modalities,
speech_config
```

`seed` is **not** one: it is no legacy field (`genai.GenerationConfig(seed=7)`
raises `TypeError`, and the server rejected it in a dict), so a `seed` key
makes the group `needs_review`; mapping it would change behaviour.

**`safety.category_map` and `safety.threshold_map` are closed.** The legacy
lookup was `value.lower()` into a fixed dictionary, so keys match
case-insensitively, nothing outside them was ever accepted, and canonical long
forms need rows of their own.

| `safety.category_map` key (any case) | Value (`types.HarmCategory` member) |
|---|---|
| `HARM_CATEGORY_UNSPECIFIED`, `unspecified` | `HARM_CATEGORY_UNSPECIFIED` |
| `HARM_CATEGORY_HARASSMENT`, `harassment` | `HARM_CATEGORY_HARASSMENT` |
| `HARM_CATEGORY_HATE_SPEECH`, `hate_speech`, `hate` | `HARM_CATEGORY_HATE_SPEECH` |
| `HARM_CATEGORY_SEXUALLY_EXPLICIT`, `harm_category_sexual`, `sexually_explicit`, `sexual`, `sex` | `HARM_CATEGORY_SEXUALLY_EXPLICIT` |
| `HARM_CATEGORY_DANGEROUS_CONTENT`, `harm_category_dangerous`, `dangerous`, `danger` | `HARM_CATEGORY_DANGEROUS_CONTENT` |

`DANGEROUS_CONTENT` is **not** a key (legacy raised
`KeyError: 'dangerous_content'`); `HARM_CATEGORY_HATE` is in neither SDK and is
never emitted.

| `safety.threshold_map` key (any case) | Value (`types.HarmBlockThreshold` member) |
|---|---|
| `block_low_and_above`, `low` | `BLOCK_LOW_AND_ABOVE` |
| `block_medium_and_above`, `medium`, `med` | `BLOCK_MEDIUM_AND_ABOVE` |
| `block_only_high`, `high` | `BLOCK_ONLY_HIGH` |
| `block_none` | `BLOCK_NONE` |
| `unspecified`, `block_threshold_unspecified`, `harm_block_threshold_unspecified` | `HARM_BLOCK_THRESHOLD_UNSPECIFIED` |

`off` and `none` are not keys. Enum *members* carry over by name,
`HarmBlockThreshold.OFF` included, so `safety.category_members` and
`safety.threshold_members` are listed separately, and every map value must be
one of them. The legacy enums (`safety.legacy_category_class`,
`safety.legacy_threshold_class`) stay out of `match.symbols`: the rule reads
only the member name, so a finding would be a row no rule claims.
A pack writes each key once, in lower case; the schema refuses any other.

**No rule for the PaLM-era surface**: `google.generativeai.generate_text` and
`google.generativeai.chat` are absent from 0.8.6; `limitations` says so.

**`types_symbol_map` must never identity-map `GenerationConfig`**:
`generate_content` does not accept the new `types.GenerationConfig`, so the
identity rewrite imports and does nothing. The pack maps it, and
`genai.types.GenerationConfig(...)` calls, to `GenerateContentConfig`.

**Chat history is rewritten, never passed through** (`google.genai` rejects the
legacy shape with a `ValidationError`). A list literal of dict literals with
string-literal parts and literal `user` or `model` roles has each part
rewritten to `{"text": <the string>}`; anything else is
`history_parts_shape_incompatible`.

**One `configure(...)` per module, anywhere in it, is the client source.** Two
or more is `multiple_configure_calls`; none is `client_source_unresolved`,
making that module `needs_review` while the module with the `configure` still
migrates. No development-corpus repository calls `configure()` at module level
or directly in `__init__`, so anything narrower migrates nothing.

**Tools/AFC, `embed_content`, files and models rules ship in v0** with
verified mappings; their `limitations` entries must say the development corpus
never exercised them.

**The tools surface is named by its `types` classes and not by constructor
keywords.** `google.generativeai.GenerativeModel.tools` is not a name (`tools=`
is a constructor keyword). The legacy `types` module has `Tool`,
`FunctionDeclaration`, `CallableFunctionDeclaration` and `FunctionLibrary`;
`types.ToolConfig` does not exist. The flipped automatic-function-calling
default is a `limitations` line plus a bail in `generative_model_calls`.

## Precondition vocabulary

Closed; enforced by the rule. One that does not hold is a bail, and the edit
group becomes `needs_review`.

| Precondition | Holds when |
|---|---|
| `import_resolved` | The symbol's qualified name resolves to the legacy module through a real import, not through an alias of something else. |
| `receiver_resolved` | The receiver of a method call resolves to a known binding. |
| `closed_world_binding` | Every reference to the bound name is visible in this file and none of them escapes. |
| `client_available` | A client object can be introduced in this file, or one already exists. |
| `static_kwargs` | The keyword arguments involved are static literals, not a spread or a computed value. |
| `literal_stream_flag` | `stream=` is a literal `True`/`False`, not an expression. |
| `no_unknown_kwargs` | The call has no keyword argument outside the set the rule knows. |

## Bail and confidence vocabulary additions

Defined in [SCAN_VOCABULARY.md](SCAN_VOCABULARY.md); a pack's fixtures and
`limitations` must cover them.

| Code | Kind | Raised when |
|---|---|---|
| `roundtrip_mismatch` | bail | `cst.parse_module(data).bytes != data`; the file is reported, never edited. |
| `history_parts_shape_incompatible` | bail | `start_chat(history=...)` outside the rewritable shape. |
| `multiple_configure_calls` | bail | Two or more `configure(...)` in one module. |
| `credentials_shape_differs` | bail | `configure(credentials=<dict literal>)`; `Client.credentials` takes only `google.auth.credentials.Credentials`. |
| `module_alias_rebound` | confidence_reason | The legacy import's name was reassigned or aliased (`g = genai`); the file is `needs_review`. |

## Fixtures

`tests/packs/test_all_packs.py` checks, per bundled pack:

- the pack validates;
- each change has a positive and a negative fixture;
- the declared fixtures are exactly the files under `fixtures/`, and each
  answer key sits beside its input;
- every `.py` fixture parses, round-trips and compiles;
- positives contain a prefilter token and negatives none, so a negative yields
  no finding;
- **a `<name>.after.<ext>` exists for exactly the positives a run migrates
  whole** (nothing withheld, every finding claimed), computed from a scan;
  the manifest fixture's test sets up that case itself, its
  verdict being repository-wide;
- applying the pack turns each `.before.` into its `.after.` byte for byte, a
  second application changes nothing, and two runs give identical output.

Layout: `fixtures/positive/<name>.before.<ext>`, optional
`<name>.after.<ext>`, and `fixtures/negative/<name>.<ext>`, beside `pack.yaml`
and `SOURCES.md`; the extension is the fixture's own (`requirements.txt` for
the manifest rule). Changes may share a fixture. The Gemini negatives cover
already-migrated code under the same `genai` alias, `GenerativeModel` from
`vertexai.generative_models` and `vertexai.preview.generative_models`, and a
local `genai` package.

### Pack test requirements

Enum maps are asserted against the installed SDK's `__members__`
(`google.genai.types.HarmCategory.__members__`,
`types.HarmBlockThreshold.__members__`), **never** by construction:
`CaseInSensitiveEnum._missing_` fabricates unknown members with only a warning,
so `types.SafetySetting(category="HARM_CATEGORY_HATE", threshold="BLOCK_EVERYTHING")`
constructs while `"HARM_CATEGORY_HATE" in types.HarmCategory.__members__` is
`False`. The test runs that construction as a **control**. Hence
**`google-genai` is a development dependency**; the wheel never imports it,
and skipping the check without it would let a wrong name through CI.

## `pack_version` semantics

Semver over the pack's content (rules, parameters, citations), independent of
obelize's version. `+build` metadata is refused: comparisons ignore it.

- MAJOR: changes what is rewritten automatically, or moves an edit between
  automatic and refused.
- MINOR: new changes, symbols or limitations.
- PATCH: citations, messages, suggestions, fixtures, wording.

Every run records the pack id, `pack_version` and sha256.

## Validation errors

Per field:

- An unknown field anywhere.
- A `from`/`to` version that is not PEP 440, or ranges that overlap or
  contradict. Only ranges over one distribution are compared: a rename may keep
  the version.
- A duplicate `changes[].id`.
- An unknown `changes[].kind`.
- An unknown entry in `changes[].preconditions`.
- A missing `source.url` or `source.retrieved_at`.
- `language` other than `python`.
- An empty `match.imports` or `match.prefilter_tokens`.
- A replacement symbol that fails the regex.
- A `configure_to_client` whose `client_symbol` names no module, whose
  `client_name` equals `client_name_fallback`, or whose `credential_kwarg` or
  `credentials_object_kwarg` is not in `allowed_kwargs`.
- A `layout.line_length` outside 40-320.

Per document, six incoherences that would otherwise scan as a clean repository:

- A rule's legacy symbol under no module in `match.imports`.
- A module in `match.imports` containing no `prefilter_tokens`.
- Other than exactly one `configure_to_client` change (a module has one client
  source).
- A symbol both rewritten and refused.
- A `manifest_dependency` naming a distribution the pack does not migrate.
- A receiver in `methods` that is neither `ctor_symbol` nor a `method_returns`
  value.

And prose: `message`, `suggestion`, `citation` and `limitations` may not
contain Unicode categories `Cc`, `Cf` or `Cs`, which can rewrite the display
(`ESC`, `\r`, `U+202E`). They are refused, not stripped, so the shown text is
the hashed text.

`tests/packs/_negative/_build.py` generates one negative pack per refusal from
one valid document, each differing in one way; its header names the field path
and expected wording, which the test checks. A rejected pack exits `7`
([CLI.md](CLI.md#exit-codes)).

## Example

Illustrative, not the real pack
(`src/obelize/packs/gemini/google-generativeai-to-google-genai/pack.yaml`,
sixteen changes). The second change shows the **wrong** tools form:
`GenerativeModel.tools` is a constructor keyword, not a symbol.

```yaml
# A migration pack -- declarative only. No code, no shell, no templates.

# Pack identity. This is also the value accepted by `obelize fix --pack <id>`.
id: gemini/google-generativeai-to-google-genai

# Version of this pack's content (semver), independent of the obelize version.
pack_version: 0.1.0

provider: gemini
language: python

# Where the migration information came from, and when it was read.
# `sha256` is the hash of the retrieved page, so a reviewer can tell whether
# the guide changed after this pack was written. See SOURCES.md next to this
# file for the quoted passages.
source:
  type: official_guide
  url: https://ai.google.dev/gemini-api/docs/migrate
  retrieved_at: 2026-09-16
  sha256: "0000000000000000000000000000000000000000000000000000000000000000"

# PEP 440 specifiers. Overlapping or contradictory ranges are a field error.
from:
  package: google-generativeai
  version: "<1"
to:
  package: google-genai
  version: ">=1"

match:
  # At least one import is required.
  imports:
    - google.generativeai
  symbols:
    - google.generativeai.configure
    - google.generativeai.GenerativeModel
  # Byte tokens: a file that contains none of these is skipped without parsing.
  prefilter_tokens:
    - generativeai

changes:
  # --- 1. Import rewrite -------------------------------------------------
  - id: rename-import
    kind: rename_import
    citation: "Migration guide, 'Install the SDK' / 'Imports'"
    preconditions:
      - import_resolved
    params:
      from_module: google.generativeai
      to_module: google.genai
      default_alias: genai
      submodule_map:
        types: google.genai.types
      types_symbol_map:
        HarmCategory: HarmCategory
        HarmBlockThreshold: HarmBlockThreshold
        # Never an identity mapping: both SDKs have a `GenerationConfig`, and
        # the new one is not what `generate_content` accepts.
        GenerationConfig: GenerateContentConfig
      # Used when the module already binds the name `types` (stdlib shadow).
      types_alias_fallback: genai_types
    fixtures:
      - fixtures/positive/import_alias
      - fixtures/negative/vertexai_generative_model.py

  # --- 2. Anything whose semantics are not 1:1 ---------------------------
  # `flag_only` never edits code. It reports and suggests.
  - id: flag-tools-and-tool-config
    kind: flag_only
    citation: "Migration guide, 'Function calling'"
    params:
      symbols:
        - google.generativeai.GenerativeModel.tools
        - google.generativeai.GenerativeModel.tool_config
      message: >-
        Automatic function calling behaves differently in google-genai; this is
        not a 1:1 rewrite.
      suggestion: >-
        Review the call against the 'Function calling' section of the guide and
        set the tool configuration explicitly.
    fixtures:
      - fixtures/positive/tools_flagged
      - fixtures/negative/no_tools.py

# Displayed as "suggested, not run". Obelize never executes these.
verification:
  suggestions:
    - "pytest -q"

# Copied verbatim into the run report.
limitations:
  - "Automatic function calling defaults differ between the two SDKs."
  - "Safety setting enum names are mapped from a fixed table; unmapped names are refused. The names are validated statically because google-genai fabricates unknown enum members with only a warning."
  - "Cross-module client setup (`configure()` in another module) is reported, not rewritten."
  - "Dynamic access and star imports are reported, never rewritten."
  - "Caching, protos and tuning surfaces are out of scope."
  - "The rules for tools/automatic function calling, `embed_content`, the files surface and the models surface ship in v0, but the development corpus never exercised them: their mappings are verified against the installed SDKs, not against real migrated repositories."
  - "Chat history is rewritten only when it is a list literal of dict literals with string-literal parts and `user`/`model` roles; every other shape is refused."
  - "A file whose round-trip through libcst is not byte-identical (for example, bare-CR line endings) is reported and never edited."
```

## Governance

- In v0 packs ship inside the wheel; `--pack` and `obelize pack validate` take
  a bundled id or a file path. A bundled id is its directory
  (`src/obelize/packs/<provider>/<slug>/pack.yaml`), and ids admit no dot, so
  the path cannot escape. No remote download, no registry.
- A pack pull request is reviewed for: an official source domain, a
  `retrieved_at` date, fully-qualified symbols, both SDK versions installable,
  negative fixtures (alias collision, `vertexai`, already-migrated code), no
  executable content, `limitations` listing non-1:1 semantics, DCO sign-off,
  CODEOWNERS approval, and `pull_request` (never `pull_request_target`)
  workflows.
- A separate `obelize-packs` repository is considered only with at least 3
  providers, 5 packs and 2 external contributors, or when packs need releasing
  independently.
