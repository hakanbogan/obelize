# Sources for `gemini/google-generativeai-to-google-genai`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The two retrieved pages

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| Migration guide (the pack's `source`) | <https://ai.google.dev/gemini-api/docs/migrate> | 2026-09-17 | `e07ee83c407fd0e47c0541b1c3f2b855eab96feec8a9f2a82f4f45c34ef5d300` |
| Models reference | <https://ai.google.dev/api/models> | 2026-09-17 | `fc0942e156d49965d2fcd110bd584c9b1b69ee3b1d7e8f5a796630075a734294` |

Hashes are of the page body as served. obelize never requests either URL.

## The measurement, and why it outranks the page

"Measured" means checked against **google-generativeai 0.8.6** and
**google-genai 2.24.0** installed side by side on CPython 3.12. Where it
disagrees with the guide, the pack follows the measurement: a mapping read off
the guide alone needed 57 corrections.

---

## rename-import

- Guide, *Installation*: `pip install -U -q "google-generativeai"` becomes
  `pip install -U -q "google-genai"`.
- Guide, *API access*: "Now, you interact through a central `Client` object.
  This `Client` object acts as a single entry point for various API services
  (e.g., `models`, `chats`, `files`, `tunings`)".
- Measured: five import spellings in real code resolve to
  `google.generativeai`: dotted, `as` alias, `from google import
  generativeai`, `from google.generativeai import X` (in no guide example) and
  the `types` submodule.
- Measured: `google.genai.types.GenerationConfig` exists, but
  `"generation_config" in types.GenerateContentConfig.model_fields` is `False`
  and `generate_content` does not accept one.
- Measured: `File`, `Model`, `HarmCategory` and `HarmBlockThreshold` exist
  under `types` in both SDKs.

## configure-to-client

- Guide, *Authentication*: "Both legacy and new libraries authenticate using API
  keys." Before: `genai.configure(api_key=...)`; after: a client.
- Measured: the legacy signature is
  `configure(*, api_key, credentials, transport, client_options, client_info, default_metadata)`.
  `transport` has no equivalent (the new SDK is HTTP-only), `client_options`
  and `default_metadata` map only roughly onto `types.HttpOptions`, and
  `client_info` has none; hence two `allowed_kwargs`.
- Measured: legacy `credentials` accepts a plain `dict`; `Client.credentials`
  only a credentials object.
- Measured, for two `limitations`: environment-variable precedence is inverted,
  and `Client(api_key="")` raises `ValueError` at construction where
  `configure()` failed at the first call.

## generative-model-calls

- Guide, *Generate content*, *Configuration*, *Safety settings*, *Chat* and
  *Count tokens*: before-and-after examples for the constructor, configuration,
  safety mapping, `start_chat` and `count_tokens`.
- Guide, *Safety settings*: the before example
  `safety_settings={'HATE': 'BLOCK_ONLY_HIGH', ...}` is why `hate` is a key.
- Measured: legacy `GenerativeModel.__init__` declares
  `model_name: str = 'gemini-1.5-flash-002'`; the new SDK requires `model=`.
- Measured: all fifteen legacy `protos.GenerationConfig` fields exist verbatim
  in `types.GenerateContentConfig.model_fields`; `seed` exists only on the new
  one.
- Measured: the legacy safety lookup is `value.lower()` into a closed
  dictionary; `dangerous_content` raised `KeyError`.
  `"HARM_CATEGORY_HATE" in types.HarmCategory.__members__` is `False`, yet
  `types.SafetySetting(category="HARM_CATEGORY_HATE", threshold="BLOCK_EVERYTHING")`
  **constructs**, with two warnings.
- Measured: `google.genai.chats.Chat`'s public surface is exactly
  `get_history`, `record_history`, `send_message` and `send_message_stream`.
- Measured: google-genai calls raise `google.genai.errors.APIError` or its
  subclasses `ClientError` and `ServerError`, status on `.code`, no class per
  status; `google-api-core` is not a requirement.
- google-generativeai 0.8.6 (not installed here, so not re-measured) depends
  on `google-api-core` and raises `google.api_core.exceptions`, one class per
  status (`ResourceExhausted`, `InvalidArgument`, `DeadlineExceeded`, ...). A
  handler naming one never runs after the rewrite, so every call rule lists
  that module in `legacy_error_modules`.

## embed-content, embed-content-async

- Guide, *Embed content*: "Generate content embeddings." Before:
  `genai.embed_content(model=..., content='Hello world')`.
- Measured: `client.models.embed_content(model=, contents=, config=)`,
  keyword-only; `task_type`, `title` and `output_dimensionality` are fields of
  `types.EmbedContentConfig`.
- Measured: the legacy result was read as `response["embedding"]`, the new as
  `response.embeddings[0].values`.
- Unverified, so a limitation: `output_dimensionality` truncation, which needs a
  live call.

## upload-file, get-file, delete-file, list-files

- Guide, *Files* / *Upload* ("Upload a file:"), *List and get* ("List uploaded
  files and get an uploaded file with a filename:") and *Delete* ("Delete a
  file:").
- Measured: `client.files.upload(file=, config=types.UploadFileConfig(...))`
  with `mime_type`, `display_name` and `name` in that config; `page_size` is a
  field of `types.ListFilesConfig`.
- Measured: legacy `upload_file(path, ...)` and `get_file(name)` take the first
  argument positionally; the new methods are keyword-only.
- Unverified, so a limitation: `File.sha256_hash`, proto `bytes` in the legacy
  SDK and `Optional[str]` in the new; confirming needs an upload.

## list-models, get-model

- Models reference (above). **The migration guide has no models section**, as
  both `citation` values say.
- Measured: `genai.list_models()` becomes `client.models.list()`, both
  iterable; `genai.get_model("models/x")` becomes
  `client.models.get(model="models/x")`, prefix unchanged.
- Measured: legacy `get_model` returned different dataclasses for `models/` and
  `tunedModels/` names, so a non-literal argument is reported.
- Measured: `google.genai.types.Model` lacks `supported_generation_methods` and
  `base_model_id` (not in `model_fields`, `hasattr` `False`) but has `name`,
  `display_name` and `input_token_limit`. Reading either raises
  `AttributeError`, and `getattr(m, "...", [])` silently returns the default,
  so `result_attribute_flags` names both.

## flag-function-calling-types

- Guide, *Function calling* / *Automatic function calling*: "The old SDK only
  supports automatic function calling in chat. In the new SDK this is the
  default behavior in `generate_content`."
- The default is inverted while the declarations barely change, so a
  mechanical rewrite would start calling the user's functions: `flag_only`.
- Measured: `types.Tool`, `types.FunctionDeclaration`,
  `types.CallableFunctionDeclaration` and `types.FunctionLibrary` exist in the
  legacy `types` module; `types.ToolConfig` does **not**.

## flag-removed-object-attributes

- Guide, *Chat*, whose after example reads the history through a method.
- Measured: legacy `ChatSession.history` and `ChatSession.last` exist;
  `hasattr(google.genai.chats.Chat, "history")` is `False`; the equivalent is
  `get_history(curated=False)`.
- Measured: `supported_generation_methods` and `base_model_id` are legacy
  `types.Model` fields, absent from `google.genai.types.Model`. The nearest,
  `supported_actions`, has an unverified vocabulary (a limitation).

## flag-legacy-module-reached-indirectly

- Guide, *Installation*, for the module path; the guide is silent on patch
  targets.
- Measured in the development corpus: `mock.patch("google.generativeai…")` is
  the **most frequent** pattern, ten occurrences in three files, against two
  for `generate_content`.
- A limitation: a file reaching the legacy module only through a patch target
  without the token `generativeai` is not found; a wider prefilter would flag
  the Vertex SDK.

## flag-out-of-scope-surfaces

- Guide, *Context caching*: "Context caching allows the user to pass the content
  to the model once, cache the input tokens, and then refer to the cached tokens
  in subsequent calls to lower the cost." The new equivalent is a client
  service with differently shaped arguments.
- Measured: `google.genai.protos` does not exist; legacy `protos` is
  proto-plus, the new `types` pydantic, with overlapping names and different
  construction.
- Measured: `answer`, `caching`, `notebook`, `operations`, `permission`,
  `protos` and `retriever` are submodules of `google.generativeai` 0.8.6, and
  `create_tuned_model` and `get_operation` top-level functions.
- Measured: the PaLM-era `generate_text` and `chat` are absent from 0.8.6.
- Measured: `ChatSession.rewind` (a method) and
  `GenerativeModel.from_cached_content` (a constructor) have no counterpart.

## manifest-dependency

- Guide, *Installation*: `google-generativeai` becomes `google-genai`.
- Measured, for `match.transitive`: google-genai 2.24.0 requires anyio,
  distro, google-auth, httpx, pydantic, requests, sniffio, tenacity,
  typing-extensions and websockets, and none of google-ai-generativelanguage,
  google-api-core, proto-plus, protobuf or grpcio. google-generativeai 0.8.6
  pins google-ai-generativelanguage, and the side-by-side environment had
  google-api-core, proto-plus, protobuf and grpcio installed with it.
- Measured: `google-genai` is GA on 2.x and requires Python 3.10+, so `>=1` is
  a floor, not a pin.
