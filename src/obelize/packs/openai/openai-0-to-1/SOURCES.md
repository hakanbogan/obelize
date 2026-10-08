# Sources for `openai/openai-0-to-1`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The retrieved page

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| v1.0.0 Migration Guide (the pack's `source`) | <https://github.com/openai/openai-python/discussions/742> | 2026-10-07 | `01b9c5d6dee28dfe95e8f8844fbddc3064e92941ab18bfed921e4e13cc294830` |

The hash is of the discussion body as the GitHub API returns it (11,004
characters, last updated 2024-02-11), since the rendered page changes with every
request. obelize never requests the URL.

## The measurement, and why it outranks the page

"Measured" means checked against **openai 0.28.1** (on CPython 3.12, 3.13 and
3.14) and against **1.109.1**, **2.0.0**, **2.34.0**, **2.54.0**, **3.0.0** and
**3.26.0** (on 3.12; 3.26.0 also imported on 3.13 and 3.14), with no call to the
API: the calls went to a local mock, and the facts about names, parameters and
result fields were read from the modules. The guide is two years stale (it
lists `client.edits` and `client.fine_tunes`, which 1.7.2 removed, and lists
`api_type` and `OpenAIError` as removed, which 3.26.0 defines), so the pack
follows the measurement. Releases 1.0.0 to 1.50.0 were not measured as targets:
on the httpx a fresh install resolves they fail at the first client
(`TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`),
which is why `to.version` starts at 1.109.1.

Facts about the old release are held in `tests/packs/openai_legacy_surface.json`
and compared to the real 0.28.1 weekly by `tests/packs/openai_legacy_check.py`;
facts about the new one are checked by `tests/packs/test_openai_facts.py` on
the pinned 3.26.0 and, weekly, on 1.109.1.

The claim that matters, that the migrated call does what the old one did, is
measured too: `tests/packs/openai_behaviour_check.py` runs the fixtures that
migrate (chat completion, text completion, embedding, an aliased import, dictionary-style reads, an
image, a moderation and an audio call) against a local server, the `.before.py` files on 0.28.1 and
the `.after.py` answer keys on 1.109.1, 2.0.0, 2.54.0, 3.0.0, 3.26.0 and 3.26.1, and the printed
results were identical. The weekly job repeats it on 0.28.1, 1.109.1 and the newest release.

---

## chat-completion, completion, embedding

- Guide: `openai.ChatCompletion.create` becomes `client.chat.completions.create`,
  `Completion.create` becomes `client.completions.create` and `Embedding.create`
  becomes `client.embeddings.create`; the guide also describes a module-level
  client (`openai.chat.completions.create`) that takes the same arguments, for
  code that does not build one.
- Measured: on 3.26.0 and 1.109.1 `openai.chat`, `openai.completions` and
  `openai.embeddings` resolve to the methods of one module client that reads
  `openai.api_key` and `openai.organization` when it is first used, and a later
  assignment to either takes effect. That is the one place the rewrite writes,
  so no client object is built and 0.28.1's global settings keep their meaning.
- Measured: 0.28.1 read `OPENAI_API_BASE` and `OPENAI_ORGANIZATION` from the environment when
  `openai` was imported (`api_base` and `organization` took them); 1.109.1 and 3.26.0 read
  `OPENAI_BASE_URL` and `OPENAI_ORG_ID` when the module client is first used, and
  `OPENAI_API_KEY` is read by both. The pack lists this as a limitation: it does not look at
  environment variables.
- Measured: the methods take keywords only, with no `**kwargs`. 0.28.1's
  `create` read `api_key`, `api_base`, `api_type`, `api_version`,
  `organization`, `request_id`, `engine`, `deployment_id`, `headers`,
  `request_timeout`, `stream` and `timeout` itself and sent everything else as
  the request body, so each of those is refused and `keywords` lists the body
  parameters that the call carried and every measured release still takes.
  `timeout` is refused too: 0.28.1 popped it as a retry deadline and never sent
  it, where the new methods send it as the HTTP timeout.
- Measured: `Embedding.create` on 0.28.1 asked for base64 itself and decoded it
  with numpy, which 0.28.1 does not install; `encoding_format` is therefore not
  carried.
- Measured: a 0.28.1 result is an `OpenAIObject`, a `dict` subclass on which
  `r["choices"][0]["message"]["content"]` and `r.choices[0].message.content`
  both work. A 3.26.0 and 1.109.1 result is a pydantic model:
  `r["choices"]` raises `TypeError`, there is no `.get`, `"id" in r` is false
  without an error and `json.dumps(r)` raises. Only attribute reads work on the new side, so a
  string key along a listed path is rewritten to its attribute (the `dict_reads` fixture reads every
  listed path by its keys and prints the same on 0.28.1, 1.109.1 and the newest release), and `result_paths` lists the fields every
  measured release defines
  (`choices[].message.content`, `usage.total_tokens`, `data[].embedding`, ...).
- Measured: the 0.28.1 result classes are not distinct types (a chat result is
  a plain `OpenAIObject`), so nothing can be read off the type: a file is
  decided by the reads it contains.

## image, moderation, transcription, translation

- Guide: `openai.Image.create` becomes `client.images.generate`, `Moderation.create` becomes
  `client.moderations.create`, and `Audio.transcribe` and `Audio.translate` become
  `client.audio.transcriptions.create` and `client.audio.translations.create`. As for the chat
  call, `openai.images`, `openai.moderations` and `openai.audio` resolve to the resources of the
  one module client on every measured release (1.109.1, 2.0.0, 2.54.0, 3.0.0, 3.26.0).
- Measured: 0.28.1's `Image.create(api_key=None, api_base=None, api_type=None, api_version=None,
  organization=None, **params)` reads those five itself and sends every other keyword as the
  JSON body, so its first positional parameter is the API key and no positional argument is
  carried. `images.generate` is keyword-only and takes `prompt`, `model`, `n`, `quality`, `size`,
  `style` and `user` on every measured release; they are what `keywords` lists. The result reads
  (`created`, `data[].url`) are fields of `ImagesResponse` and `Image` on all of them.
- Measured: `url`, `b64_json` and `revised_prompt` are optional on the new model, so a field the
  server left out reads as `None` where 0.28.1 raised `KeyError` or `AttributeError`, and a handler
  that relied on the miss (`except Exception`, a bare `except`, `except AttributeError`) stops
  running. `url` is absent from a `b64_json` response and `revised_prompt` from a `dall-e-2` one, so
  `response_format` is not carried and only `url`, which the default format returns, is a listed
  path. A model that returns no url whatever the format (`gpt-image-1`) is the case this does not
  catch.
- Measured: 0.28.1's `Moderation.create(input, model=None, api_key=None)` dropped a `model` of
  `None` from the body, where `moderations.create` sends `"model": null`, and raised `ValueError`
  before any request for a model other than `text-moderation-stable` and `text-moderation-latest`,
  which the new method sends on. So only `input` is carried, positionally or as a keyword, and a call
  with a `model` is refused. The categories are not read: 0.28.1 keyed them `"self-harm"` and
  `"hate/threatening"`, which the new model spells `self_harm` and `hate_threatening`, so only `id`,
  `model` and `results[].flagged` are listed.
- Measured: 0.28.1's `Audio.transcribe(model, file, api_key=None, ..., *, deployment_id=None,
  **params)` sends `model` and the other keywords as form fields beside the file, and
  `Audio.translate` takes the same arguments. Both new methods are keyword-only, so `positional_to_kw`
  is `model, file`. `language`, `prompt` and `temperature` reach the server as the same form fields
  (the behaviour check prints them as the mock server read them); `translations.create` has no
  `language`, so it is not listed there. `response_format` is not carried: `text`, `srt` and
  `vtt` return a string on both sides, and `verbose_json` a result with more fields than `text`
  (measured against a local server on 0.28.1 and 1.109.1), so one result type cannot be assumed.
- Measured, and not refused: the new method omits an empty `language` or `prompt` where 0.28.1
  sent the empty field; it names the upload by its base name and guesses its type where 0.28.1 sent
  `file.name` as written with `application/octet-stream`; it uploads from the start of a file where
  0.28.1 uploaded from the current offset; and it refuses a file object that is not an `io.IOBase`,
  bytes, a path or a tuple, which 0.28.1 sent if it had a `name` and a `read` (a Django upload).
  The last is a limitation of the pack.
- Measured on every rule of the pack: the new module client retries a request that fails with 408,
  409, 429 or a 5xx status twice (`openai.max_retries`), where 0.28.1 retried connection errors only,
  and connects within 5 seconds where 0.28.1 allowed 600 (`openai.timeout`). A retried image
  generation is a second request. A CA bundle named by `REQUESTS_CA_BUNDLE` is read by 0.28.1 and not
  by the new releases, which read `SSL_CERT_FILE`.

## flag-async-calls

- Measured: `acreate` is a coroutine function on `ChatCompletion`,
  `Completion`, `Embedding` and `Image` in 0.28.1, and `Moderation.acreate` returns a
  coroutine, as do `Audio.atranscribe` and `atranslate`. The new module client has no async
  form: `openai.AsyncOpenAI` is a client the file must build and close, and no
  measured release has `acreate`.

## flag-settings

- Measured: 0.28.1 defines `aiosession`, `api_base`, `api_key_path`,
  `api_type`, `api_version`, `app_info`, `ca_bundle_path`, `debug`,
  `enable_telemetry`, `log`, `proxy`, `requestssession` and `verify_ssl_certs`
  as module attributes. 3.26.0 and 1.109.1 define only `api_type` and
  `api_version` of these, and read them once, when the first call builds the
  client; assigning any of the others succeeds and changes nothing, which no
  scan, import or test of the migrated code shows.
- Measured: the old `api_type` values `open_ai` and `azure_ad` build a plain
  client in 3.26.0 without an error. A base URL set on the module must end in a
  slash or the request path is joined onto it without one.

## flag-errors

- Measured: 0.28.1 raises from `openai.error` (`InvalidRequestError`,
  `AuthenticationError`, `PermissionError`, `RateLimitError`,
  `ServiceUnavailableError`, `Timeout`, `TryAgain`, `APIConnectionError`,
  `APIError`, `InvalidAPIType`, `SignatureVerificationError`), re-exporting
  three at the top level. No measured newer release has the module, or
  `InvalidRequestError`, `TryAgain` or `ServiceUnavailableError`; `openai.Timeout`
  is a configuration class and not an exception.
- Measured: `openai.APIError` exists on both sides and is not the same class:
  the old one carries `http_status`, `json_body` and `user_message`, the new one
  `status_code`, `body`, `code` and `request_id`, and a 404 that was
  `InvalidRequestError` is `NotFoundError` now. A handler that names the old
  attributes or classes compiles and fails, or never runs. The name is not
  reported, because it is the one a repository already on the new release writes
  (`except openai.APIError`) and reporting it would keep that repository on the
  pack's list for good; the cost is a limitation of the pack.

## flag-resources

- Measured: `Audio`, `Customer`, `Deployment`, `Edit`, `Engine`, `ErrorObject`,
  `File`, `FineTune`, `FineTuningJob`, `Image`, `Model` and `Moderation` are
  stubs in 3.26.0 and 1.109.1: reading one never raises and calling it raises
  `APIRemovedInV1`. `Image.create`, `Moderation.create`, `Audio.transcribe` and `Audio.translate`
  are rewritten (see their section); the rest are not, because their replacements differ in
  shape (`Image.create_edit` and `create_variation` upload files, `Audio.*_raw` takes a file
  name of its own, `Model.list` becomes `models.list`, which returns a `SyncPage` to iterate, and
  `Edit` and `FineTune` have no counterpart: their endpoints were shut down in
  January 2024).

## flag-removed-modules

- Measured: 0.28.1 ships `api_requestor`, `api_resources`, `cli`, `datalib`,
  `embeddings_utils`, `object_classes`, `openai_object`, `openai_response`,
  `upload_progress`, `util`, `validators` and `wandb_logger`. None of them
  imports on 3.26.0; 1.x and 2.x up to 2.34.0 ship an `openai.cli` of their own
  (the `openai migrate` command), which is a different module under the name.

## flag-indirect-use

- A string target in a `mock.patch`, an `importlib.import_module` or a
  `sys.modules` stub names the old module and never meets an import statement.

## dependency

- Guide: the package is installed as `openai` before and after, and the
  guide's step is `pip install --upgrade openai`.
- Measured: `Requires-Python` is `>=3.7.1` for 0.28.1, `>=3.8` for 1.109.1 and
  2.0.0, `>=3.9` from 2.34.0 and `>=3.10` from 2.54.0; 0.28.1 is MIT-licensed
  and 1.109.1 to 3.26.0 Apache-2.0.
- Measured (modules installed in a clean environment, Python 3.12): 0.28.1 installs `requests`
  (with `urllib3`, `certifi`, `idna`, `charset_normalizer`), `aiohttp` (with `yarl`,
  `multidict`, `frozenlist`, `aiosignal`, `attrs`, `aiohappyeyeballs`, `propcache`) and `tqdm`.
  1.109.1 installs `anyio`, `certifi`, `distro`, `h11`, `httpcore`, `httpx`, `idna`, `jiter`,
  `pydantic`, `sniffio`, `tqdm` and `typing-extensions`; 3.26.0 installs `anyio`, `h11`,
  `httpcore2`, `httpx2`, `idna`, `jiter`, `pydantic`, `sniffio`, `truststore` and
  `typing-extensions`. `match.transitive` holds the pin for every module that 0.28.1 installs
  and one of the two lacks, apart from `aiohappyeyeballs` and `propcache`, which only `aiohttp`
  imports.
- Measured (OSV, retrieved 2026-10-07): no advisory names any release of the
  PyPI package `openai`, so `>=1.109.1` is a floor chosen for the reason in the
  measurement section and not for a fix.
- The pin rule: a declaration whose lowest admitted version is already 1.109.1 or later
  (`openai==3.26.0`, `openai>=2`) is left as written, and one that admits the old API
  (`openai>=0.28.1,<3`) is rewritten to `openai>=1.109.1`. A declaration the rule cannot write in
  place, with extras or a URL such as `openai[datalib]==0.28.1`, holds the repository
  (`manifest_pin_shape_unsupported`).
