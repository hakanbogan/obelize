# Scan vocabulary

The closed sets of strings the scanner, planner, rewrite rules and fixture
ground truth use; an unlisted value is a bug. `tests/unit/test_models.py` fails
unless each section's values equal its `Literal` in `src/obelize/models.py`, so
a member is added to both in one commit; `tests/unit/test_fixture_vocabulary.py`
grades the fixtures against them. §6 and §7 derive from §1-§5.

## 1. `Finding.kind` — what was found (9 values)

| Value | Meaning |
|---|---|
| `import` | An import statement that binds a legacy name. Of a shared module only a name `match.symbols` lists is one: `import openai` is not. |
| `call` | A call whose callee resolves to a legacy qualified name (`genai.configure(...)`). Of a shared module, a read off its result (`f(...).choices[0].x`) is part of this row; of any other it stays a row of its own. |
| `attribute` | A legacy name read, not called: an annotation, an enum member. |
| `method_call` | A method call on a receiver resolving to a legacy object (`model.generate_content(...)`). |
| `dynamic` | A legacy name reached through `getattr`, `importlib.import_module` or `__import__`. Of a shared module, also the bare module fetched by its string. |
| `star_import` | `from google.generativeai import *`. Of a shared module, only one from the module itself or from a legacy symbol (`from openai.types import *` is not). Names it may bind are separate findings with `confidence_reason: star_import_candidate`. |
| `text_mention` | The prefilter token in a string, comment or docstring, on a line with no AST finding. |
| `manifest` | A dependency declaration in `requirements*.txt` (or `requirements/<name>.txt`), `pyproject.toml`, `Pipfile`, `setup.py` or `setup.cfg`. Lockfiles are not read: a line edit would break their hashes. |
| `parse_error` | libcst or `compile()` refused the file. Reported, never edited. |

## 2. `Finding.confidence_reason` — why we believe it (16 values)

| Value | Meaning |
|---|---|
| `direct_import_resolved` | `import google.generativeai`, no alias. |
| `alias_resolved` | `import google.generativeai as X`; used through `X`. |
| `from_import_resolved` | `from google.generativeai import Y [as Z]`; used through the bound name. |
| `conditional_binding` | Two or more `IMPORT` qualified names for one node (a `try`/`except` double import). |
| `module_alias_rebound` | The bound name was reassigned or aliased (`g = genai`); uses through the new name are not tracked. A shared module used as a value (`client = openai`) is the same, and so is a read of its `__dict__` or `__getattribute__`. |
| `receiver_bound_same_scope` | The receiver is a local bound in the same scope. |
| `receiver_bound_module_const` | The receiver is a module-level constant, used in a function or method of the same module. |
| `receiver_bound_self_attr` | The receiver is `self.<attr>`, matched on (enclosing `ClassDef`, first-parameter name, attribute name). |
| `receiver_unresolved` | The receiver has no resolvable binding. |
| `dynamic_access` | Reached by name at run time: `importlib.import_module("…")`, `__import__("…")`, a `sys.modules[…]` assignment. `getattr(<alias>, "X")` is `module_alias_rebound`. Of a shared module, the bare module fetched by its string counts too. |
| `star_import` | Bound by a star import; the names are unknown. |
| `star_import_candidate` | A bare name a star import in the same module may have bound. |
| `string_or_comment_mention` | Only in a string, comment or docstring. |
| `mock_patch_target` | A call argument that is exactly a legacy dotted path, as in `mock.patch("google.generativeai...")`. |
| `manifest_dependency` | A dependency declaration naming the legacy distribution. |
| `parse_error` | The file did not parse; coordinates come from the exception. |

## 3. Fixture `verdict` — what `obelize fix --apply` does (4 values)

The ground truth's grade. The runtime counterpart is `Edit.status` (§8).

| Value | Hunk in `patch.diff`? | Meaning |
|---|---|---|
| `auto` | **yes** | Rewritten. No `bail`. |
| `needs_review` | **no** | A bail fired; listed in REPORT.md with its code and a suggested diff. `bail` required. |
| `unsupported` | **no** | No expressible change and no suggestion. `bail` required. |
| `not_a_usage` | **no** | Context only: a `text_mention`, or a legacy pin nothing imports where nothing migrated. A manifest declaring the **new** distribution over legacy code is `manifest_code_mismatch` instead. |

Ground-truth rules (`tests/unit/test_fixture_vocabulary.py`):

- `bail:` (a §4 code) on every `needs_review` and `unsupported` finding, and on
  no other.
- `after_file_is:` is `fix_apply_output`, `human_answer_key` (what a person would
  write, not the tool) or `none` (no `.after.py`). Under `fix_apply_output`, a
  `<name>.py` with a `<name>.after.py` must come out of `obelize fix --apply` as
  that key and carry only `auto` findings; every other `.py` must come out
  unchanged.
- `warnings:` (§5) may accompany any verdict.
- `caused_by:` on every `file_not_fully_migrated` row and no other (§6).
- `must_not_report` rows are keyed by `file`, `line` **and** `symbol`: one line
  can hold a finding and a decoy.

## 4. Bail codes (`Edit.reason`)

A bail withholds its whole binding group; the group is atomic.

### Scanner and file handling

| Code | Raised when |
|---|---|
| `roundtrip_mismatch` | `cst.parse_module(data).bytes != data` on the input. |
| `input_does_not_parse` | libcst or `compile()` refused the input; `limitations[].detail` names which. Also a `pyproject.toml` or `setup.cfg` whose Python requirement is unreadable; that run is not blocked. |
| `output_does_not_parse` | The rewritten bytes fail `cst.parse_module` or `compile()`. The file is left alone. |
| `output_names_unresolved` | The rewritten bytes read a name the module does not bind and the input did not read (a `self` in a static method): a `NameError` `compile()` misses. The file is left alone. |
| `file_too_large` | Over `max_file_bytes`. |
| `runtime_unsupported` | The project declares a Python the new distribution does not install on (the pack's `to.requires_python`). |
| `legacy_version_unsupported` | The legacy distribution is declared with no version, or one below the floor of the pack's `from.version`, or not at all while the code uses it. |

### Resolution and bindings

| Code | Raised when |
|---|---|
| `conditional_binding` | Two or more `IMPORT` qualified names for one node. |
| `module_alias_rebound` | The legacy module alias was rebound, or aliased again (`g = genai`). |
| `model_object_escapes` | A bound name used other than as a supported method's receiver (argument, return, store, `del`, `global`, attribute read); a module constant in `__all__`; an instance attribute reached other than through its class's methods' first parameter; or, at fix time, a reference the rewrite would leave behind. |
| `model_object_read_elsewhere` | No escape in its own file, but another selected module imports the module constant (by name or `*`) or reads it or the instance attribute off the module; judged from imports and reads, never text. |
| `multiple_assignments` | The name is assigned more than once in its scope (`len(scope[name]) > 1`); an instance attribute counts every write in the class's methods. |
| `class_attr_binding` | The constructor is a class-body attribute. Out of scope in v0. |
| `receiver_unresolved` | A supported method on a receiver with no binding record, including an unbound constructor result. |
| `receiver_method_unmapped` | A supported method in the pack's `methods` with no `rewrites` entry; the whole group is withheld. |

### Client

| Code | Raised when |
|---|---|
| `multiple_configure_calls` | Two or more resolved `configure(...)` calls in one module; a `mock.patch` target does not count. |
| `client_source_unresolved` | No `configure(...)` in the module, so no client can be introduced. Withholds its call rewrites, not a type import or an identity-mapped enum member. |
| `client_name_collision` | `client` and `genai_client` are both bound (for an attribute client, `self.client` and `self.genai_client` are both used). |
| `client_placement_ambiguous` | The `configure(...)` is inside a function and the module's call rewrites are not, so no one client reaches them all. |
| `configure_kwargs_unsupported` | `configure(transport=…, client_options=…, client_info=…, default_metadata=…)`. |
| `credentials_shape_differs` | `configure(credentials=<dict literal>)`. |

### Imports and manifests

| Code | Raised when |
|---|---|
| `alias_collision` | The target alias is already bound to something else. |
| `type_symbol_unmapped` | A `from google.generativeai.types import X` whose `X` is not in `symbol_map`. |
| `from_import_unmigrated_symbol` | A `from … import` line whose symbols are not all rewritten; also a call a module-rooted `rewrite_call` reaches through such an import (`ChatCompletion.create` after `from openai import ChatCompletion`), which has no root to keep. |
| `local_import` | The legacy import is inside a function, method or class body. One under `if TYPE_CHECKING:` counts as module level. |
| `star_import` | `from google.generativeai import *`. |
| `file_not_fully_migrated` | **Import atomicity.** A resolved legacy usage in the file is not `auto`, so the file is left exactly as it was: every otherwise-`auto` finding in it carries this code. |
| `repo_not_fully_migrated` | **Manifest atomicity.** An in-scope file still imports the legacy distribution, so removing its pin is withheld. Adding the new pin is a separate `auto` edit once anything migrated. Where the new distribution is the legacy one (`openai`), any withheld row of the pack holds the one pin, and a `fix` run then leaves every file as it was, each row of another file that would have been `auto` naming this code too (the rows of the file that holds the cause read `file_not_fully_migrated`). A declaration already in the new range has no row. |
| `transitive_dependency_in_use` | Nothing imports the legacy distribution, but an in-scope file imports a module only it installed (the pack's `match.transitive`) that no manifest declares. Removing the pin is withheld; the files are listed in the manifest plan's `transitive`. |
| `manifest_code_mismatch` | The manifest declares the new distribution and **no** legacy pin, while an in-scope file imports the legacy one. Reported, never edited. The no-legacy-pin clause keeps a half-migrated manifest from matching. |
| `manifest_pin_shape_unsupported` | The legacy declaration or its line holds more than name and version: extras, a URL, a non-string table value, a shared key, a second declaration. The line is left alone. Fix time, except for a pack whose one distribution holds both APIs: its scan raises it for a declaration with extras, a URL or a non-string table value once anything migrated, and `fix` then leaves every file as it was. |

### Call rewrites

| Code | Raised when |
|---|---|
| `unknown_ctor_kwarg` | A `GenerativeModel(...)` keyword the rule does not know. |
| `ctor_argument_not_portable` | Folding the model's name or configuration into each call would change its meaning: it runs something (a call, an `await`, a comprehension), or a name in it is bound more than once or differently at the call. |
| `positional_arg_ambiguous` | A parameter given by position and by keyword, or more positional arguments than the signature has (a parameter the pack lists only under `keywords` is not carried by position). Already a `TypeError`; refusing keeps it from becoming a silently wrong model. |
| `default_model_name_required` | `GenerativeModel()` with no model name. |
| `generation_config_not_static` | `generation_config=` is a spread, a computed `dict(...)`, an unresolvable name, or has a key outside the legal 15; or a configuration object is not a constructor argument. |
| `safety_settings_not_static` | A category or threshold outside the closed tables, or a shape other than a category-to-threshold mapping or a list of one-row mappings. |
| `history_parts_shape_incompatible` | `start_chat(history=…)` outside the rewritable shape; also a model request that is a single turn, a name filled with a mapping, or any turn on a chat's `send_message`. A literal list of turns in a client call is reshaped instead. |
| `dynamic_stream_flag` | `stream=` is not a literal. |
| `async_stream_await_missing` | `async for` over `generate_content_async(..., stream=True)` with no `await`: already a `TypeError`, since the legacy method is a coroutine function. |
| `unsupported_kwarg` | `request_options=` and other kwargs with no counterpart, or in no list the rule carries; `stream=` where the new method cannot stream; a `**` splat. |
| `afc_semantics_differ` | `tools=`, `tool_config=`, or `enable_automatic_function_calling=`. |
| `response_shape_changed` | The pack says the new call returns a different shape. `result_access_flags`: the legacy result was a mapping; raised on a call whose result is used, or a stream read other than as a `for` iterable. `dispatch_prefixes`: the argument is not a literal under a prefix the new call reproduces (`get_model("tunedModels/…")` would silently return the wrong class). `result_paths`: a read of the result that is not along a listed path, written as attributes or as string keys (`response["choices"]` stopping short of a leaf, a key off the path, `.get`, a loop over it, a key read of a name that may hold something else, in a closure, or in a `try` that catches `KeyError`, the result passed on or returned). |
| `count_tokens_config_carries_semantics` | `count_tokens` on a constructor with `system_instruction=` or `tools=`, which change the count. |
| `attribute_removed` | An attribute only the legacy object has (`supported_generation_methods`) or that became a method (`chat.history` -> `chat.get_history()`); at fix time, a call result read for a field listed in `result_attribute_flags`. |
| `flag_only_surface` | The pack's `flag_only` rule matched: a `mock.patch` target, a dynamic import, a `sys.modules` stub, `protos`/`caching`, the PaLM-era surface. Reported with a suggestion, never rewritten. |
| `error_class_changed` | A rewritten call is in a `try` whose handler, in the same function, names an exception from the change's `legacy_error_modules` (`google.api_core.exceptions`). The new SDK raises `google.genai.errors`, so the handler would never run. |
| `types_import_typing_only` | The rewrite needs a submodule (Gemini's `types`) at run time and the file imports it only under `if TYPE_CHECKING:`, with no replaced statement that runs to anchor a fresh import. |

### The run

The codemod driver's own codes.

| Code | Raised when |
|---|---|
| `usage_unmapped` | A detected usage no change rewrites (a free function referenced, not called; a `methods` entry with no `rewrites`). Writing the file would strand it behind a rewritten import, so the file is left alone. |
| `configure_consumed_elsewhere` | Another in-scope module with no `configure` stays on the legacy SDK and relies on this file's process-wide default, which the rewrite would remove. The file is left alone; a `mock.patch` target does not count. |

## 5. Warning codes (`Edit.warnings[]`)

A warning never withholds an `auto` edit; it is printed with it and recorded in
REPORT.md.

| Code | Meaning |
|---|---|
| `client_constructed_eagerly` | `genai.Client(...)` validates the key when constructed, unlike `configure(...)`, so importing the rewritten module can raise `ValueError`. Fires when the new `Client(...)` is at module level and `api_key=` is not a non-empty string literal. |
| `model_name_looks_prefixed` | The model-name literal starts with `models/`. |
| `count_tokens_config_dropped` | The constructor's `generation_config` was not carried into `count_tokens`. |
| `positional_args_mapped_by_index` | A positional `GenerativeModel(...)` argument past index 0 was mapped by the legacy order `(model_name, safety_settings, generation_config, tools, tool_config, system_instruction)`; printed because `safety_settings` precedes `generation_config`. |
| `history_parts_rewritten` | Each string part of a `start_chat(history=...)` literal became `{"text": <the string>}`. |
| `async_stream_await_preserved` | An `await` before an async streaming call survived the rename; dropping it raises `TypeError`. |

## 6. Bail selection -- which code a withheld finding names

A finding names one `bail`: the **most specific rule that fired**. Atomicity comes last:
`file_not_fully_migrated` never displaces a code that names a defect. A file
gate stamps every finding in the file (`encoding/bare_cr.py`); atomicity leaves
the defect's code on its rows and `file_not_fully_migrated` on the rest
(`escapes/model_escapes.py`).

| Rung | What fired | Raised by |
|:---:|---|---|
| 1 | the pack refuses the surface outright (`flag_only_surface`, `attribute_removed`) | `scan/analysis.py` |
| 2 | a file-level gate (`input_does_not_parse`, `roundtrip_mismatch`, `output_does_not_parse`, `output_names_unresolved`) | `scan/parse.py`; the last two `transforms/codemod.py`, on the bytes a run would write |
| 3 | a whole-file resolution defect (`module_alias_rebound`, `conditional_binding`, `star_import`) or where an import statement sits (`local_import`) | `scan/analysis.py` |
| 4 | the module's client (`client_source_unresolved`, `multiple_configure_calls`) | `impact/planner.py` |
| 5 | the binding group (`receiver_unresolved`, `model_object_escapes`, `class_attr_binding`, `multiple_assignments`) | `receiver_unresolved` by `scan/analysis.py`, the rest by `impact/dataflow.py` |
| 6 | atomicity (`file_not_fully_migrated`, `repo_not_fully_migrated`, `transitive_dependency_in_use`) | `impact/planner.py`, `scan/manifests.py`; at fix time `transforms/codemod.py` also puts `repo_not_fully_migrated` on the source rows of a pack whose new distribution is its legacy one, import rows included |

Each module declares `BAILS`, and `RUNG` when laddered; `impact/planner.py`
merges them into `LADDER` and `ORDER` (most specific first), checked by
`tests/unit/test_planner.py`. `tests/oracle/test_scan_against_the_oracle.py`
checks that the raised codes equal the graded ones. A later pass may only move a
finding to a **more specific** code, never out of `needs_review`. Within a rung:
`impact/dataflow.py`'s `ORDER`, then `receiver_unresolved`, since the group
names a real binding.

Outside `LADDER`, since nothing on their row competes:

- `model_object_read_elsewhere` (`scan/reach.py`): asked last, lands only on a
  row nothing else fired on.
- `scan/manifests.py`'s codes: a manifest row names one declaration, so two
  never fire together. Rung 6 places `repo_not_fully_migrated` against the file codes. `manifest_pin_shape_unsupported` is the manifest rule's, and `scan/manifests.py` raises it too for a pack whose one distribution holds both APIs.
- `transforms/codemod.py`'s four (`usage_unmapped`, the two output gates,
  `configure_consumed_elsewhere`): fix-time, only on an `eligible` row. A pack
  that is its own target gets `repo_not_fully_migrated` on its source rows the
  same way (ADR-031 D12).
- Call-rewrite bails: fix-time, one per group.
  `transforms/kinds/generative_model_calls.py` declares its order: the client,
  then the group's shape, then the constructor.

### `caused_by`

On a `file_not_fully_migrated` finding, and no other, `caused_by` is
**exactly** the sorted, de-duplicated bails of the file's other findings, read
after every other rung, so the report says why and each code stays countable
(`tests/unit/test_fixture_vocabulary.py`). It comes from findings, never
`bindings`; a `bindings` row carries neither it nor `file_not_fully_migrated`.
`repo_not_fully_migrated` has none: its cause is files, which the report names.

### Bails an `import` finding may carry

An `import` or `star_import` finding is the statement itself, so only a bail
about the statement, the file, or atomicity fits; `models.Finding` refuses any
other.

| Code | Why an import finding may carry it |
|---|---|
| `roundtrip_mismatch` | File gate. |
| `output_does_not_parse` | File gate, after the rewrite. |
| `output_names_unresolved` | File gate, after the rewrite. |
| `flag_only_surface` | The imported surface is refused outright (`protos`, `caching`, the PaLM-era API). |
| `module_alias_rebound` | The name it binds is reassigned or re-aliased. |
| `conditional_binding` | It is one of two statements binding the same name. |
| `star_import` | It is the star import. |
| `local_import` | It is inside a function or method body. |
| `alias_collision` | Its new alias is already bound. |
| `type_symbol_unmapped` | A symbol on this `from ... .<submodule> import` line is not in `symbol_map`. |
| `from_import_unmigrated_symbol` | Not every symbol on this `from ... import` line is rewritten. |
| `file_not_fully_migrated` | Atomicity: the import resolved, something else did not. |
| `repo_not_fully_migrated` | Atomicity of a pack whose one distribution holds both APIs: the import is one the pack would rewrite, and a row elsewhere in the repository is withheld. |
| `usage_unmapped` | No rule of the pack rewrites this statement. |
| `runtime_unsupported` | A `fix` run withheld every row of a pack the repository's declared Python rules out. |
| `legacy_version_unsupported` | A `fix` run withheld every row of a pack the repository's legacy pin rules out. |

Absent: `input_does_not_parse` and `file_too_large` (a gated file yields one
`parse_error` finding and no analysis). `runtime_unsupported` and `legacy_version_unsupported`
are a repository status (a pack's `blocked` in `run.json`), and only a `fix` run puts them on a
row, after the scan graded it `eligible`. The scan fixtures carry six on an import row
(`roundtrip_mismatch`, `module_alias_rebound`, `conditional_binding`,
`star_import`, `local_import`, `file_not_fully_migrated`); the rest are derived
from the SDK surface and the pack spec.

## 7. Values that belong to more than one set

Five strings belong to more than one of §1-§5, deliberately;
`tests/unit/test_models.py` fails on any other overlap.

| Value | Sets | Why one word does both jobs |
|---|---|---|
| `star_import` | `kind`, `confidence_reason`, bail | One syntactic fact: the finding, the resolution and the refusal. |
| `parse_error` | `kind`, `confidence_reason` | An unparsable file yields one finding with nothing else to say. Its bail, `input_does_not_parse`, names the gate. |
| `conditional_binding` | `confidence_reason`, bail | The reason is the observation (two `IMPORT` names for one node), the bail its consequence (no automatic fix). |
| `module_alias_rebound` | `confidence_reason`, bail | Observation: the alias was reassigned. Consequence: uses through the new name are not tracked. |
| `receiver_unresolved` | `confidence_reason`, bail | Observation: no binding record. Consequence: the model name the new call needs is unknown. |

No warning code is in another set: a shared name would blur whether a hunk
exists. §8 and §10 reuse §3's `needs_review` and `unsupported` and are checked
against §3 directly; §9, §11 and §12 are checked disjoint from the finding sets,
except that §11 and §12 share five values (§12).

## 8. `Edit.status` — what a run recorded (4 values)

§3 grades a **fixture**; this grades a **run**.

| Value | Meaning | Fixture `verdict` |
|---|---|---|
| `auto` | The rule produced the edit; it is in `patch.diff`. | `auto` |
| `needs_review` | A bail fired; described in REPORT.md, not written. | `needs_review` |
| `unsupported` | No rule can express the change; no suggestion. | `unsupported` |
| `model_proposed` | A model's edit for a withheld row, passing every [ADR-003](adr/ADR-003-model-adapter.md) guard. Written **only** with `--apply` *and* `--accept-model`. | none, and never |

`not_a_usage` names no edit. `model_proposed` is no fixture verdict: a
hand-written key cannot grade a model's answer without assuming it.
`tests/unit/test_models.py` asserts `§3 - §8 == {not_a_usage}` and
`§8 - §3 == {model_proposed}`. The separate status keeps model edits out of the
model-free headline ([BENCHMARK.md](BENCHMARK.md)).

## 9. `Binding.kind` — how a legacy object was bound (4 values)

The closed-world table of [ADR-006](adr/ADR-006-pack-carries-no-code.md): a
method call is rewritten only when the receiver's whole world is visible.

| Value | Pattern | `scope` | v0 |
|---|---|---|---|
| `name` | `model = genai.GenerativeModel(...)`: one `Name` target, assigned once before use, used in the same scope. | `function:<name>` | automatic |
| `module_const` | A module-level assignment used in the same file's functions or methods, never reassigned in an inner scope. | `module` | automatic |
| `self_attr` | `self.model = genai.GenerativeModel(...)` in `__init__`, used as `self.model.<method>(...)` in the same class; matched on (enclosing `ClassDef`, first-parameter name, attribute name). | `class:<Name>` | automatic, with the closed-world guard |
| `class_attr` | An assignment in a class body. | `class:<Name>` | `needs_review` (`class_attr_binding`) |

`models.py` refuses a `scope` that contradicts the kind. Only `self_attr` has a
dotted `name` (`self.model`). Any use of a bound name other than as a supported
method's receiver withholds the whole group (`model_object_escapes`,
`multiple_assignments`): a new constructor with an old call site, or the
reverse, breaks working code.

## 10. `Finding.scan_status` — what a scan alone may say (4 values)

`obelize scan` applies no rule, so it cannot claim a fix-time status.

| Value | Meaning | Against §3 |
|---|---|---|
| `eligible` | No scan-time rule withholds it. | Necessary for `auto`, never sufficient. |
| `needs_review` | A scan-time bail fired; `bail` required. | Same. A transform bail can demote a finding into it, never out. |
| `unsupported` | No counterpart at all; `bail` required. | Same. |
| `not_a_usage` | Context only. | Same. |

The oracle reads a key's `auto` as `eligible` when grading a scan. A `scan`
run's [`counts`](RUN_FOLDER.md#counts) use this split; `plan` and `apply` use
§3's. `tests/unit/test_models.py` asserts `§3 - §10 == {auto}` and
`§10 - §3 == {eligible}`.

## 11. `Skipped.reason` — why a path was not looked at (7 values)

A path the walker did not hand on; closed because silently dropped files look
like an empty repository. `src/obelize/scan/walker.py` raises these;
`src/obelize/fsutil.py` decides the five shared with §12
([THREAT_MODEL.md](THREAT_MODEL.md) TM-2).

| Value | Raised when |
|---|---|
| `missing` | Listed, not on disk (a tracked file removed with `rm`). |
| `not_a_file` | Not a regular file: a gitlink (a submodule), a fifo, a device. |
| `outside_root` | Containment failed with **both** sides resolved, including under a linked directory, where `is_symlink()` is `False`. |
| `submodule` | A directory with its own `.git`, pruned by the fallback walk: this repository's diff cannot show its files. |
| `symlink` | A symbolic link, file or directory, or a Windows junction. Never followed. |
| `unreadable` | The filesystem would not answer (a directory would not list, permissions hide a path). A denial is a refusal, never a pass. |
| `unusable_name` | Not valid UTF-8, holds a backslash, or on Windows is a name it reserves: a device such as `aux.py`, a `:` stream, a trailing dot or space. It cannot be reported and read back as one path, so its `limitations[]` row has no `path` and the detail quotes the name. The fallback walk refuses a directory with such a name whole. |

`limitations[].code` adds the reader's `file_too_large` and
`input_does_not_parse` ([RUN_FOLDER.md](RUN_FOLDER.md#limitations)). The reader
raises `unreadable` too, for a selected file that will not open, including one
that became a symbolic link.

## 12. `WriteRefusal` — why a planned write did not happen (6 values)

What an apply declined to write; closed in `src/obelize/fsutil.py`.

| Value | Raised when |
|---|---|
| `file_changed_since_read` | The bytes on disk are not those the plan was built from. Refuses the **whole** apply: the plan is stale, and writing would destroy uncommitted work. |
| `missing` | The file is not there. A run never creates a file. |
| `not_a_file` | Not a regular file when written. |
| `outside_root` | Containment failed with both sides resolved, or the path is absolute or has a `..` component. |
| `symlink` | A symbolic link: `rename` would replace it, and an author's link is not turned into a file. |
| `unreadable` | The filesystem would not answer: the staleness read, the descent, or the rename. |

Five are §11's words (`models.PathRefusal`): one question, one word. A refused
write is reported in `run.json`'s `refused[]` (§13), not in `limitations[]`.

## 13. `RefusalCode` — what `run.json`'s `refused[]` may say (8 values)

§12 plus two refusals about the repository. Declared in `src/obelize/models.py`
as that union, since `obelize.fsutil` imports `models`;
`tests/unit/test_models.py` asserts the union.

| Value | Raised when |
|---|---|
| `file_changed_since_read` | §12. |
| `missing` | §12. |
| `not_a_file` | §12. |
| `outside_root` | §12. |
| `symlink` | §12. |
| `tree_dirty` | Uncommitted changes to a tracked file anywhere in the tree, or a file on the plan that git does not track, refused the whole apply before any file was opened: a clean tree makes `git diff` the migration and nothing else. |
| `tree_unknown` | git could not say whether the tree is clean (a timeout, a failure, a refused directory), so the apply was refused. `--allow-dirty` skips the question. |
| `unreadable` | §12. |

Only `tree_dirty` and `tree_unknown` have no path. `tree_dirty`'s `detail` counts
the outstanding paths and never names them: they are the user's own work.
