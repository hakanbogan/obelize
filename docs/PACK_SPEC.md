# MigrationPack specification

_The schema is `src/obelize/packs/schema.py`, and `src/obelize/schemas/pack.schema.json` is generated
from it; `tests/packs/` holds this document's vocabularies and refusals equal to it. Decisions:
ADR-006, [ADR-018](adr/ADR-018-pack-schema.md),
[ADR-053](adr/ADR-053-shared-module-migrations.md)._

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
3. **A symbol is fully qualified**, matching
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
| `provider` | string | yes | The vendor or maintaining project, e.g. `gemini` or `py-pdf`. |
| `language` | string | yes | `python`. |
| `source` | mapping | yes | See [Source provenance](#source-provenance). |
| `from` | mapping | yes | `package` (distribution name) and `version` (PEP 440 specifier, e.g. `"<1"`). `from.package` and `to.package` may be one distribution, as in `openai/openai-0-to-1`; their versions then tell the two sides apart and may not overlap. |
| `to` | mapping | yes | Same shape, e.g. `">=1"`, plus `requires_python` (required): the PEP 440 set of Pythons the new distribution installs on. A repository declaring support for one outside it is blocked (`runtime_unsupported`). |
| `match` | mapping | yes | `imports` (module paths, non-empty), `symbols` (qualified names), `prefilter_tokens` (a file with none is skipped unparsed), `transitive` (module to distribution, for modules only the legacy distribution installed: while a file imports one and no manifest declares its distribution, the legacy pin stays), `shared` (default `false`; the module is the new SDK's too, see [Shared modules](#shared-modules)). |
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
| `citation` | string | yes | The source guide section. |
| `fixtures` | list of paths | yes | See [Fixtures](#fixtures). |

## Rule kind registry

The six kinds are closed in `src/obelize/packs/schema.py`; a pack cannot add
one. All six are implemented: `registry.IMPLEMENTED`
(`src/obelize/transforms/registry.py`) equals the schema's set, and
`tests/packs/test_all_packs.py` reads the registry. A method listed in
`generative_model_calls.methods` but absent from `rewrites` is recognised, and
the group that calls it is withheld as `receiver_method_unmapped`.

| kind | pack parameters |
|---|---|
| `rename_import` | `from_module`, `to_module`, `default_alias`, `submodule_map` (`types` -> `google.genai.types`), `symbol_map` (`Name`, or `<submodule>.Name` for one in `submodule_map`, to the new name), `alias_fallbacks` (a submodule to the alias used when the file already binds its own name) |
| `configure_to_client` | `legacy_symbol`, `client_symbol` (fully qualified), `client_name` and `client_name_fallback` (tried in order), `allowed_kwargs`, `credential_kwarg` (validated by the new client at construction) and `credentials_object_kwarg` (an object where the legacy call also took a mapping) |
| `generative_model_calls` | `ctor_symbol`, `methods` map, `method_returns` map, `generation_config_keys`, `config_class`, `legacy_config_symbol`, `legacy_config_aliases`, `legacy_config_kwarg`, `ctor_order` (legacy signature order, **not** sorted), `ctor_model_kwarg`, `ctor_config_fields`, `ctor_afc_kwargs`, `model_kwarg`, `stream_kwarg`, `model_name_prefix`, `rewrites`, `response_attrs_now_none`, `response_legacy_error`, `legacy_error_modules`; `safety` (`legacy_kwarg`, `legacy_category_key`, `legacy_threshold_key`, `legacy_category_class`, `legacy_threshold_class`, `category_map`, `threshold_map`, `category_members`, `threshold_members`, `setting_class`, `category_class`, `threshold_class`, `category_kwarg`, `threshold_kwarg`, `config_field`) and `history` (`role_key`, `parts_key`, `text_key`, `roles`). A `rewrites` entry: `new_call`, `root`, `stream_call`, `positional_to_kw`, `arg_map`, `afc_kwargs`, `history_kwarg`, `contents_kwarg` (what the model is asked; a list of turns is reshaped), `coroutine`, `config_kwarg`, `semantic_kwargs` |
| `rewrite_call` | `legacy_symbol`, `new_call` (dotted path under the client, or after the root the author wrote when `root` is `module`), `root` (`client`, the default, or `module`), `arg_map`, `positional_to_kw`, `keywords`, `config_class`, `config_kwargs`, `config_kwarg`, `result_access_flags`, `result_attribute_flags` (fields the new result lacks; reading one is `attribute_removed`), `result_paths` (the reads of the result that carry), `legacy_error_modules`, `dispatch_prefixes` |
| `flag_only` | `symbols` / `patterns` / `attributes`, `message`, `suggestion` |
| `manifest_dependency` | `from_name`, `to_name` (both may name one distribution), `to_spec` |

**`legacy_error_modules`**: a rewritten call in a `try` whose handler names an
exception from one of these modules is refused as `error_class_changed`; the
new SDK never raises it, so the handler would never run.

**`rewrite_call` carries only what its three lists name.** `positional_to_kw` is
the legacy parameter order and the new call's own arguments; `keywords` names
more of the new call's arguments, carried only **when written as keywords**, so
a positional argument beyond `positional_to_kw` is still
`positional_arg_ambiguous`; `config_kwargs` go into `config_class`, passed as
`config_kwarg`. Any other keyword, and a `**` splat, is `unsupported_kwarg`. The
schema checks that no parameter is in two lists, every `arg_map` key is in one, no two parameters map to one keyword (the configuration object's own keyword, `config_kwarg`, counts: `arg_map` may not rename a parameter onto it), `keywords`, `config_kwargs` and `result_paths` are sorted and de-duplicated, and every `dispatch_prefixes` key is read by the rule. A list of `keywords` is an allowlist of what a measurement showed
the new call takes with the meaning the old one gave it, never a list of what
the old one accepted: 0.28.1's `create` sent an unknown keyword as the request
body and read others itself, and a name nobody measured must not carry.

**`root`** says where `new_call` is spelled. `client` (the default) spells it
under the client the pack's `configure_to_client` places. `module` spells it
after the root expression the author wrote, whatever the file bound the module
to: `oai.ChatCompletion.create(...)` becomes `oai.chat.completions.create(...)`. `new_call` names a
service and a method on it either way.
It builds no client and so needs no `configure_to_client`, which a pack with
only module-rooted rewrites does not declare. A call reached through
`from M import Name` has no root to keep and is `from_import_unmigrated_symbol`,
raised only by a module-rooted rule (`rewrite_call.MODULE_BAILS`).

**`result_paths`** lists the only reads of a call's result that carry, because a
result whose type changed is read correctly only along attributes both types
have. A path is dotted attribute names with `[]` after one that is indexed,
such as `choices[].message.content` or `usage.total_tokens`:

- `[]` stands for a subscript that is an integer literal (`choices[0]`,
  `choices[-1]`); a name or a string may select a key instead, and is not one.
- A path ends in an attribute, never in `[]`, and no path continues another:
  `choices[].message` beside `choices[].message.content` is refused, since a
  path ends where the read is trusted.
- Reads are followed off the call itself and off the one name it is assigned
  to, in that name's scope. Anything else is `response_shape_changed`: a string
  subscript, `.get`, a loop over the result, a read of a path that is not a
  prefix of a listed one, a method on a non-leaf, the result passed on or returned. A result nothing reads carries.
- A read the scope analysis links to no assignment (above it, in a loop's second pass) counts as
  a read of the result, and a result bound in a class body is `response_shape_changed`: `A.r` and
  `self.r` link to no scope.
- It excludes `result_access_flags`, which refuses every use of the result and
  would leave the paths unconsulted.

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
| `mock_patch_target` | A call argument that is exactly a legacy dotted path, as in `mock.patch("google.generativeai...")`. |
| `dynamic_access` | The legacy module reached through `getattr`, `importlib.import_module` or `__import__`. |
| `sys_modules_stub` | An assignment into `sys.modules` under the legacy module's name, which replaces the module for every later importer. |

The first two are also `confidence_reason` values
([SCAN_VOCABULARY.md](SCAN_VOCABULARY.md) §2); a test pins `sys_modules_stub`
as the only id that is not. On a shared module a string matches only when it names a legacy symbol or, for
`importlib.import_module`, `__import__` and `sys.modules`, the bare module. The `dynamic_access` id enables four shapes:
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
decides whether two names are one distribution. `from_name` and `to_name` may be one: `openai==0.28.1` becomes `openai>=1.109.1`, the two sides told apart by the pack's `from.version` and `to.version`. A declaration whose lowest admitted version `to.version` already admits (`openai==3.26.0`, `openai>=2`) has arrived: it is left as written, with no row, while one that admits the old API (`openai>=0.28.1,<3`) is rewritten. One distribution holds both APIs, so such
a pack is **coupled**: while any row of the pack is withheld, no file is written
and the pin stays (`repo_not_fully_migrated`,
[ADR-053](adr/ADR-053-shared-module-migrations.md) D6). A declaration whose rewrite
would drop or duplicate something (extras, a direct URL, a non-version table
value, a duplicated key or declaration) is `manifest_pin_shape_unsupported` and left alone. For a coupled pack the scan raises it too, once
anything migrated, for a declaration with no pin the rule can write (extras, a URL, a non-version
value), so the whole pack is withheld ([ADR-053](adr/ADR-053-shared-module-migrations.md) D12).

### Parameter constraints fixed by the Phase 0 spikes

Binding: each prevents code that imports cleanly and is silently
wrong.

**`generative_model_calls.method_returns`** maps a method to the legacy
receiver its result is (Gemini: `GenerativeModel.start_chat` to
`ChatSession`). `ChatSession` has no constructor, so without it
`chat.send_message(...)` resolves to nothing and the file reads as clean. Each
key must be a method of its receiver, each value must have its own method
list, and no method may return its own receiver.

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

**`symbol_map` must not identity-map Gemini's `types.GenerationConfig`**:
`generate_content` does not accept the new `types.GenerationConfig`, so the
identity rewrite imports and does nothing. The pack maps it, and
`genai.types.GenerationConfig(...)` calls, to `GenerateContentConfig`. A pack
test holds it.

**A name mapped to itself keeps its `from` import.** `from <module> import
<name>` stays a `from` import of the new module when every name on it is
mapped to itself; a name mapped to another one, or not mapped, is
`from_import_unmigrated_symbol`. A read through the module (`<module>.<name>`)
is rewritten to the new module's alias, and one through a submodule to the
submodule's.

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

## Shared modules

Some libraries keep the module name across a major version (`openai` 0 to 1).
Then `import openai` says nothing about which API a file was written for, and
`match.shared: true` changes what counts as legacy
([ADR-053](adr/ADR-053-shared-module-migrations.md)):

- Only the names `match.symbols` lists are legacy, by dotted segment:
  `openai.Image` covers `openai.Image.create` and not `openai.ImageX`, however
  the file reaches it (`import openai as oai` then `oai.Image`, or
  `from openai import Image`). `import openai`, `openai.OpenAI` and
  `openai.api_key` are no finding.
- `symbols` lists the **legacy** side and never the kept one. The old release is
  frozen and finite, and the new one grows with each release, so a list of the
  kept names is wrong the day one is added. The price is that a name the pack
  forgets is no finding at all, so the pack fails open there, and a test holds
  the list equal to a snapshot of the old release
  ([Pack test requirements](#pack-test-requirements)).
- The module used as a value (`client = openai`, `getattr(openai, "Image")`)
  escapes the scan as `module_alias_rebound`, since a name read through it can no longer be resolved, and so does a read of its `__dict__` or `__getattribute__`. The bare module fetched by its string (`importlib.import_module("openai")`, `__import__("openai")`, `sys.modules["openai"]`) is a `dynamic_access` row. A star import is a row only from the module itself or from a legacy symbol (`from openai.types import *` is not). A mention in prose and a `mock.patch` target count only when they name a legacy symbol.
- A read off a call's result (`f(...).choices[0].x`) belongs to the call's own
  row, and `result_paths` decides which reads carry. A pack that is not shared keeps such a read as a
  row of its own.
- The schema refuses a shared module with no `symbols`, a rule whose legacy
  symbol is under `match.imports` and not under `match.symbols` (a `generative_model_calls` safety
  enum class is read for a member and never found, so it needs no entry), and a `rename_import` change: the module is not renamed, and a shared module is
  rewritten at its calls with `root: module`.

An excerpt of `src/obelize/packs/openai/openai-0-to-1/pack.yaml`:

```yaml
from:
  package: openai
  version: ">=0.28.1,<1"
to:
  package: openai
  version: ">=1.109.1"
  requires_python: ">=3.8"

match:
  imports:
    - openai
  shared: true
  symbols:
    - openai.ChatCompletion
    - openai.Image
    - openai.api_base
  prefilter_tokens:
    - openai

changes:
  - id: chat-completion
    kind: rewrite_call
    citation: "openai-python v1.0.0 Migration Guide, 'Module-level client'"
    params:
      legacy_symbol: openai.ChatCompletion.create
      new_call: chat.completions.create
      root: module
      keywords:
        - messages
        - model
        - temperature
      result_paths:
        - choices[].message.content
        - usage.total_tokens
    fixtures:
      - fixtures/negative/module_client_new.py
      - fixtures/positive/chat_completion.before.py

  - id: dependency
    kind: manifest_dependency
    citation: "openai-python v1.0.0 Migration Guide, 'Installing'"
    params:
      from_name: openai
      to_name: openai
      to_spec: ">=1.109.1"
    fixtures:
      - fixtures/negative/requirements_already_new.txt
      - fixtures/positive/requirements.before.txt
```

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
  no finding; a shared module's negatives name the module, so they are scanned
  instead and yield nothing but `not_a_usage`;
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

A **shared** pack (`match.shared`) cannot install both sides in one environment,
so its two halves are held differently
([ADR-053](adr/ADR-053-shared-module-migrations.md) D8):

- The legacy side is a committed snapshot of the old release's public names
  (with their kinds), submodules and error classes. A test requires every name
  in it to be listed in `match.symbols` or in a short set of names the new
  release defines (with the meaning they had, or left unreported on purpose), and not both, so a legacy name the
  pack forgot fails the suite. A script that needs only the standard library
  compares the snapshot with the real old release on a schedule.
- The new side is read from the new release installed as a development
  dependency, and on a schedule from the floor of `to.version`: every
  `keywords` entry is a parameter of the method `new_call` names, every
  `result_paths` segment is a field of the model it returns, and
  `to.requires_python` covers the Pythons the release declares.
- Its negative fixtures are scanned, not prefiltered, since the module's name is
  the token of every file that already uses the new API.

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
- A `from`/`to` version, or a `to` with no `requires_python` or one that is not PEP 440, or
  ranges that overlap or contradict. Only ranges over one distribution are compared: a
  rename may keep the version.
- A duplicate `changes[].id`.
- An unknown `changes[].kind`.
- A missing `source.url` or `source.retrieved_at`.
- `language` other than `python`.
- An empty `match.imports` or `match.prefilter_tokens`, or `match.shared` with no
  `match.symbols`.
- A symbol that fails the regex.
- A `configure_to_client` whose `client_symbol` names no module, whose
  `client_name` equals `client_name_fallback`, or whose `credential_kwarg` or
  `credentials_object_kwarg` is not in `allowed_kwargs`.
- A `rename_import` whose `symbol_map` key is not `Name` or `<submodule>.Name`, names a
  submodule or a submodule absent from `submodule_map`, or whose `alias_fallbacks` names a
  submodule absent from it or repeats `default_alias`.
- A `rewrite_call` parameter in two of `positional_to_kw`, `keywords` and
  `config_kwargs`.
- A `rewrite_call` `keywords`, `config_kwargs` or `result_paths` list that is not sorted and
  de-duplicated, or a `positional_to_kw` that repeats an entry (it is in legacy order, so it is never
  sorted).
- A `rewrite_call` whose `positional_to_kw` and `keywords` entries, once `arg_map` renames them, land
  two on one keyword or one on `config_kwarg`, or whose `config_kwargs` land two on one field: the
  emitted call would name it twice.
- A `rewrite_call` `root` other than `client` or `module`, or a `new_call` that is one name: a call
  under the client or the module names a service and a method on it.
- A `result_paths` entry that is not dotted attribute names with `[]` after an indexed one (a leading digit, an empty segment or a space is not), ends in `[]`, or continues another entry; or `result_paths`
  beside `result_access_flags`.
- A `layout.line_length` outside 40-320.

Per document, seven incoherences that would otherwise scan as a clean repository:

- A rule's legacy symbol under no module in `match.imports`, or, for a shared module, under no entry of `match.symbols` (bar a `generative_model_calls` safety enum class).
- A module in `match.imports` containing no `prefilter_tokens`.
- More than one `configure_to_client` change (a module has one client source),
  or none while a change rewrites calls onto the client
  (`generative_model_calls`, and `rewrite_call` unless its `root` is `module`).
- A `rename_import` change in a shared pack.
- A symbol both rewritten (or mapped by `symbol_map`) and refused.
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
  requires_python: ">=3.10"

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
    params:
      from_module: google.generativeai
      to_module: google.genai
      default_alias: genai
      submodule_map:
        types: google.genai.types
      symbol_map:
        types.HarmCategory: HarmCategory
        types.HarmBlockThreshold: HarmBlockThreshold
        # Never an identity mapping: both SDKs have a `GenerationConfig`, and
        # the new one is not what `generate_content` accepts.
        types.GenerationConfig: GenerateContentConfig
      # Used when the module already binds the name `types` (stdlib shadow).
      alias_fallbacks:
        types: genai_types
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
