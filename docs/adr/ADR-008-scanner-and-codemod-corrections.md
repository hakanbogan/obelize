# ADR-008: Scanner and codemod corrections

## Status

Accepted; amended by ADR-010 (F-1, F-4, F-6, F-7, F-8), ADR-012 (D6), ADR-017 (D1, D2),
ADR-019 (D1), ADR-022 and ADR-050.

## Decision

These rules hold for `libcst` 1.9.0 (1.8.6 on an Intel Mac), `google-genai` 2.23.0 and
`google-generativeai` 0.8.6 as installed, where a design read off their
documentation needed 57 corrections, and are re-checked when any version changes.
Each names its entry in *Spike corrections*, which lists every correction the
repository cites. The closed vocabularies they use live in
[docs/SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) (ADR-010 F-4).

### Resolving a legacy usage

- **Collect the whole qualified-name set, then branch.** Exactly one name with
  the `google.generativeai` prefix and `source == IMPORT` -> resolved; two or
  more -> `conditional_binding`; any `LOCAL` name alongside -> rebound, never
  auto-fix (C-04).
- **Flag module-alias escapes.** An `Access` of a legacy `ImportAssignment`
  whose parent is *not* an `Attribute` makes the whole file `needs_review` (C-05).
- **Detect star imports through the scope, not the provider.** With a legacy
  `ImportStar` in the module, a candidate is a name in `scope.accesses` with no
  assignment record anywhere in the scope chain (C-06).
- **String annotations are real findings** (`kind=attribute`,
  `from_import_resolved`), never `string_or_comment_mention`; `mock_patch_target`
  is string matching (C-26).
- **`module_alias_rebound`** is the `confidence_reason` for both C-04's rebinding
  and C-05's alias escape (C-43).

### Reading and writing files

- **Bytes in, bytes out.** `Path.read_bytes()` -> `cst.parse_module(bytes)` ->
  write `module.bytes` -> `compile(module.bytes, path, "exec")`; never
  `read_text()` or `parse_module(str)` (C-10).
- **Gate every file on a byte round-trip before any edit.** A file where
  `cst.parse_module(data).bytes != data` is analysed and reported but never
  written: **`roundtrip_mismatch`** (C-09, C-43). The gates run libcst, then
  `compile()`, then the round-trip (ADR-017 D1).
- **Run `compile()` on the input as well as the output.** A file libcst parses
  but `compile()` rejects is a `parse_error` and never edited (C-08).
- **`cst.ParserSyntaxError` is not a `SyntaxError` subclass.** The libcst gate
  catches `(cst.ParserSyntaxError, SyntaxError, ValueError)` and the `compile()`
  gate `SyntaxError` (ADR-017 D2); coordinates come from `.raw_line` (1-based)
  and `.raw_column` (0-based), or `.lineno`. No source excerpt goes into
  evidence: `.context` is one (C-08).

### Selecting files

- **Resolve both sides of the containment check**:
  `candidate.resolve(strict=True).is_relative_to(root.resolve(strict=True))`
  inside `except (OSError, RuntimeError): return False`, plus the separate
  `is_symlink()` guard (C-13).
- **`Path.is_file()` is mandatory, not defensive**: it drops a gitlink (C-14).
- **Prune nested `.git` entries in the `os.walk` fallback**; the
  `git ls-files -z --cached --others --exclude-standard` primary path stays
  (C-14).
- Findings are ordered by the total key below before anything is hashed or written.

### Determinism

- **Sort every libcst set by source position before consuming it**:
  `sorted(..., key=lambda x: position_provider[x.node].start)`, before any id is
  hashed or any finding is emitted (C-11).
- **Make the output sort key total: `(file path bytes, sha256 of content)`** (C-12).

### Transforming

- **`MetadataWrapper(module, unsafe_skip_copy=True)` is load-bearing**, since the
  default copy makes a transform a silent no-op; a unit test asserts
  `MetadataWrapper(m, unsafe_skip_copy=True).module is m`. Transforms run through
  `wrapper.visit(transformer)` and declare `METADATA_DEPENDENCIES` (C-07).
- **Promote a positional argument to a keyword (`contents=`) before prepending
  `model=`**, and **convert `cst.CSTValidationError` into `BailError` inside the
  rule**, so the group becomes `needs_review` and the file's other groups still
  apply (C-25).

### Bindings and the client

- **D1 -- parent lookup uses libcst's `ParentNodeProvider`, not a hand-rolled parent stack.**
  The alias-escape rule and the walk from `Assignment.node` to the constructor
  `Call` need it, and its cost falls only on prefilter survivors (C-35). The
  providers resolve in one `resolve_many`, `ScopeProvider` free. Analysis
  resolves and records, `impact/planner.py` decides, and `analysis.BAILS` is the
  seam (ADR-019 D1).
- **D2 -- `self_attr` bindings ship in v0, not v0.2**, because two of the three
  corpus repositories need them. Match on **(enclosing `ClassDef` node,
  first-parameter name, attribute name)**, never on the qualified-name string.
- **D3 -- `ClientSource` is module-wide.** Exactly one `configure(...)` anywhere
  in a module -- module level, a method or a plain function -- is its client
  source. Two or more bail (`multiple_configure_calls`); zero is
  `client_source_unresolved` -> `needs_review` for that module's call rewrites.
  A module whose `configure` another in-scope module without one still relies on
  is withheld whole, under `configure_consumed_elsewhere`
  ([ADR-031](ADR-031-codemod-driver.md) D11) (C-30).

### Pack rule corrections

- **`GenerationConfig` must map to `GenerateContentConfig`, never identity-map**,
  `genai.types.GenerationConfig(...)` call sites included (C-03).
- **Safety names are validated against `__members__`, in tests, never by
  construction**, and the pack's `limitations` say so (C-02).
- **The safety maps are the legacy lookup's closed table**, keyed by
  `value.lower()` (the pack's `safety.category_map` and `safety.threshold_map`),
  with identity rows for the canonical long forms; `dangerous_content`, `off`
  and `none` are never keys (C-16, C-32).
- **`send_message(content=X)` becomes `send_message(message=X)`** (C-17).
- **Async streaming preserves its `await`**:
  `async for x in await model.generate_content_async(p, stream=True)` becomes
  `async for x in await client.aio.models.generate_content_stream(...)`, `auto`
  with `async_stream_await_preserved`; the `await`-less form bails
  `async_stream_await_missing` (ADR-010 F-8) (C-18).
- **The legacy constructor's positional order is
  `(model_name, safety_settings, generation_config, tools, tool_config, system_instruction)`**;
  positionals are mapped by index, with `positional_args_mapped_by_index`
  (ADR-010 F-7) (C-22).
- **The legal `generation_config` key set is exactly the 15 `protos.GenerationConfig` fields**;
  anything else, `seed` included, is an unknown key -> `needs_review` (C-23).
- **`configure`'s unsupported kwargs are `transport`, `client_options`,
  `client_info`, `default_metadata`**; a dict-literal `credentials=` bails
  `credentials_shape_differs` (C-19).
- **The API-key environment precedence is inverted between the SDKs**, and
  `Client()` raises at construction when the key is absent or empty. The
  `configure()` -> `Client()` rewrite stays `auto`, with both as limitations and
  the warning `client_constructed_eagerly` (ADR-010 F-6) (C-20).
- **A bare `GenerativeModel()` is `needs_review` (`default_model_name_required`)**: the
  legacy default model is retired, so none is substituted (C-21).
- **D4 -- chat history is rewritten only in the fully literal case.** A list
  literal of dict literals with string-literal `parts` and roles `user` or
  `model` has each part rewritten to `{"text": <the string>}`; everything else
  bails **`history_parts_shape_incompatible`**, because pass-through imports and
  then throws, the worst outcome available (C-01).

### Benchmark integrity

- **Version pinning is mandatory and asserted after install**: `bench/cases.yaml`
  pins `to_version`, and a case whose installed version differs fails (C-15).
- **`bench/cases.yaml`'s `python` field carries a full uv interpreter key**, e.g.
  `cpython-3.12.9-macos-aarch64-none`; provenance records the interpreter path
  and `platform.machine()` (C-15).
- **Blocklist a second Vertex origin: `vertexai.preview.generative_models`**;
  negative controls import `GenerativeModel` from both origins (C-24).

### Deferred

- **D5 -- the process-pool threshold** -- settled by
  [ADR-022](ADR-022-runner-result-order.md): 32 candidate
  files, with a default of `min(8, cpu_count - 1)` workers (C-33).
- **D6 -- pack rules 7-10 (tools/AFC, `embed_content`, files, models) ship in v0**,
  their mappings verified against the installed packages; the pack's
  `limitations` say the development corpus never exercised them, each occurring
  **zero** times in its three repositories (C-45).

## Spike corrections

| Id | Correction |
|---|---|
| C-01 | Legacy chat history's bare string parts and non-`user`/`model` roles fail the new SDK's validation, so only the fully literal shape is rewritten. |
| C-02 | The new SDK's `HarmCategory` and `HarmBlockThreshold` fabricate any member named, with only a warning, so a wrong safety name never raises. |
| C-03 | `types.GenerationConfig` exists in both SDKs, and an identity rewrite imports cleanly and does nothing. |
| C-04 | `QualifiedNameProvider` is flow-insensitive and multi-valued: `genai = None` after the import still yields the IMPORT name. |
| C-05 | After `g = genai`, `g.GenerativeModel("m")` resolves only to `LOCAL`, so the prefix rule never fires. |
| C-06 | Star-imported names resolve to an empty set in the provider but appear in `scope.accesses`. |
| C-07 | Without `unsafe_skip_copy=True` the wrapper deep-copies the module and every transform silently changes nothing. |
| C-08 | libcst accepts some code CPython refuses, and `cst.ParserSyntaxError` is not a `SyntaxError`. |
| C-09 | A file whose only line terminator is a bare CR loses its last byte through libcst and still compiles. |
| C-10 | `parse_module(str)` ignores the PEP 263 cookie and a BOM breaks `compile()` on a `str`, so files are handled as bytes. |
| C-11 | `scope[name]` and `Assignment.references` iterate in heap order, which differs between processes. |
| C-12 | Paths repeat across roots, so a sort by path alone leaks input order when `bench/run.py` aggregates many. |
| C-13 | On macOS `/tmp` is a symlink, so resolving only the candidate puts every file outside the root. |
| C-14 | `git ls-files` lists a submodule as an ordinary path, and the `os.walk` fallback descends into it. |
| C-15 | An unpinned install on Python 3.9 silently resolves `google-genai==1.47.0`, and a bare `--python` version can pick another interpreter. |
| C-16 | The legacy safety lookup is a closed lower-cased table; canonical long forms need identity rows, and `DANGEROUS_CONTENT` was never a key. |
| C-17 | Legacy `send_message` takes `content`, the new one `message`, so the keyword form is a `TypeError` unless renamed. |
| C-18 | Both async streaming calls are coroutine functions, so real legacy code already has the `await` the new call needs. |
| C-19 | `configure` accepts `transport`, `client_options`, `client_info` and `default_metadata`, which `Client` lacks, and a plain-dict `credentials`. |
| C-20 | The SDKs read `GEMINI_API_KEY` and `GOOGLE_API_KEY` in opposite order, and `Client()` raises `ValueError` at construction without a key. |
| C-21 | Legacy `GenerativeModel()` defaults to `"gemini-1.5-flash-002"`, a retired model, while the new call requires `model=`. |
| C-22 | The legacy constructor puts `safety_settings` before `generation_config`, and every parameter is positional-or-keyword. |
| C-23 | `seed` is in neither the legacy dataclass nor the protos, so it reaches obelize only through an unvalidated dict. |
| C-24 | `vertexai.preview.generative_models` exports a second live `GenerativeModel` that only its origin tells apart. |
| C-25 | libcst raises `CSTValidationError` when a keyword is prepended before a positional argument. |
| C-26 | A string annotation resolves to its legacy qualified name even under `if TYPE_CHECKING:`; a `mock.patch` string resolves to nothing. |
| C-27 | `from google import generativeai` becomes `from google import genai`, every `generativeai.Y` becomes `genai.Y`, and the `alias_collision` bail applies. |
| C-28 | `match.imports` is a dotted-prefix match on `google.generativeai`, not a list of names. |
| C-29 | The manifest reader includes `tool.poetry.group.<name>.dependencies`. |
| C-30 | Corpus code calls `configure()` inside functions and helper methods, so the client source is module-wide. |
| C-31 | A `generation_config` that is a name assigned once in reach should resolve like a literal instead of bailing `generation_config_not_static`; open as COVERAGE gap 29. |
| C-32 | The only static `safety_settings` in the corpus writes the canonical long forms, which is why the identity rows are required. |
| C-33 | The pool pays from 32 candidate files once the default worker count leaves the parent a core. |
| C-35 | `ParentNodeProvider` adds 17-30% to metadata resolution, paid only by the 2.19% of files that survive the byte prefilter. |
| C-37 | The Python floor behind `blocked: runtime_unsupported` comes from the manifest, never from the parser. |
| C-43 | The closed vocabularies gain exactly two members: `module_alias_rebound` and `roundtrip_mismatch`. |
| C-45 | Tools and AFC, `embed_content`, the files calls and the models calls occur zero times in the three-repository corpus: absent there, not shown rare. |
| C-46 | Every legacy file in the three-repository corpus bails somewhere, so it yields "plausibly imports and little else"; that is a corpus problem as much as a rules problem. |
| C-47 | A `resumable=` upload has no counterpart and is refused as an unsupported keyword (ADR-029 D8); `client.files.delete` returns a `DeleteFileResponse` where legacy `delete_file` returned `None`. |
| C-48 | `base_model_id` and `supported_generation_methods` are gone from the new `types.Model`, and `get_model` is rewritten only for a `models/` literal, since legacy returned another class for a `tunedModels/` name. |
| C-56 | The new `response.text` returns `None` where the legacy one raised `ValueError`, so code catching that error is reported, not rewritten, and the pack's `limitations` say so. |
| C-57 | A test that patches through the application's own module path never names the SDK, so a per-file scan misses it; the pool threshold counts candidate files. |

## Consequences

- **The honest one.** Every legacy file in the three development-corpus repositories
  carries a bailing usage, so under ADR-010 F-1 their automatic edit count is zero; over
  eighty repositories from GitHub code search, 57 have a file where nothing bails
  ([ADR-024](ADR-024-gate-1-measurement.md)).
- A module-wide `ClientSource` (D3) asserts that one `configure` governs its whole module.
