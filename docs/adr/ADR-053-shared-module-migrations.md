# ADR-053: Shared-module migrations

## Status

Accepted; amended by [ADR-055](ADR-055-rename-setting.md).

## Decision

A migration may keep its module name. `openai` 0.28.1 and `openai` 1.109.1 or later are one
distribution and one import, so no import statement says which API a file was written for, and every
pack so far found its legacy code by the module it leaves. ADR-050 lets the format widen only for a
migration that needs it, and the third family, **`openai` 0 to 1**, `openai/openai-0-to-1`, needs five
things (D2 to D6). As for ADR-051, a Gate 0 measured every fact the rules rest on before any rule was
written, with no call to the API: the calls went to a local mock, and the names, parameters and
result fields were read from the modules. D11 to D17 are what an adversarial review of the finished
pack changed, D18 a later rewrite, D19 four more calls and D20 a part of a result in a name.


### D1. What the Gate 0 measured

Run on openai 0.28.1 (CPython 3.12, 3.13 and 3.14) and on 1.109.1, 2.0.0, 2.34.0, 2.54.0, 3.0.0 and
3.26.0 (3.12; 3.26.0 also on 3.13 and 3.14). The facts the pack rests on hold on all six releases
of the new side, and 3.26.0 is the newest.

- A 0.28.1 result is an `OpenAIObject`, a `dict` subclass, so `r["choices"][0]["message"]["content"]`
  and `r.choices[0].message.content` both work. From 1.109.1 a result is a pydantic model:
  `r["choices"]` raises `TypeError` and there is no `.get`. The 0.28.1 result classes are not
  distinct types, so nothing can be read off the type: a file is decided by the reads it holds.
- The new `create` methods are keyword-only with no `**kwargs`. 0.28.1 sent every unknown keyword as
  the request body but read twelve itself (`api_key`, `api_base`, `api_type`, `api_version`,
  `organization`, `request_id`, `engine`, `deployment_id`, `headers`, `request_timeout`, `stream`,
  `timeout`).
- `openai.chat`, `openai.completions` and `openai.embeddings` are methods of one module client that
  reads `openai.api_key` and `openai.organization` when it is first used, so a later assignment to
  either takes effect.
- `openai.ChatCompletion` and the other 0.28.1 resources are stubs on the new side: reading one never
  raises and calling it raises `APIRemovedInV1`. A call a scan misses is a failure at run time.
- Of the thirteen module settings 0.28.1 defined, eleven (`api_base`, `proxy`, `log` and the
  rest) are not defined by the new releases, so assigning one succeeds and changes nothing, and two
  (`api_type`, `api_version`) are read once, when the first call builds the client, to choose Azure.
- 0.28.1 has 50 public names at the top of the module and is frozen. 3.26.0 has 127, and the number
  grows with each release.
- Releases 1.0.0 to 1.50.0 fail at the first client on a fresh install, because httpx 0.28 removed
  `proxies`.
- The official guide (discussion 742) was last updated on 2024-02-11 (last edited 2024-02-05) and is stale: it lists
  `client.edits` and `client.fine_tunes`, which 1.7.2 removed, and calls `api_type` and `OpenAIError`
  removed though 3.26.0 defines both. The pack follows the measurement (ADR-018 D7).
- OSV lists no advisory for any release of the PyPI package `openai`.

### D2. A shared module lists the legacy side, not the kept side

`match.shared: true` says the module is the new SDK's too. Then `import openai`, `openai.OpenAI` and
`openai.api_key` are no finding, and only a name `match.symbols` lists is legacy, by dotted segment:
`openai.Image` covers `openai.Image.create` and not `openai.ImageX`. A name is legacy however it is
reached (`oai.Image`, `from openai import Image`).

**Rejected: `match.kept`.** The first design was the reverse: a closed list of the names valid on both
sides, with everything else under the module legacy. It fails closed, since a name nobody listed is
reported. The Gate 0 overturned it. The new surface is 127 names and grows with every release, so a
kept list is wrong the day a release adds a name, and until someone edits the pack it reports every
`openai.OpenAI(...)` in the repository. The 0.28.1 surface is frozen and finite, so a list of what it
defined can be complete and stays complete.

The price is that a shared pack fails open: a legacy name the pack forgot is no finding, and the
repository reads clean while that code breaks. D8 is what pays for it.

The scanner separates *reaches the module* from *is a legacy name*, in `scan/analysis.py`:

- The module used as a value (`client = openai`, `getattr(openai, "Image")`) escapes, as for any
  legacy module (`module_alias_rebound`), because a name read through it can no longer be resolved.
  D14 adds the ways to reach the bare module that name no import.
- A prose mention or a `mock.patch` target is a finding only when it names a legacy symbol.
- A read off a call's result (`f(...).choices[0].x`) belongs to the call's own row and is no second
  attribute finding, since the call's rule decides which reads carry (D5). This holds only where the
  module is shared (D15).


The schema refuses a shared pack with no `symbols`, a rule whose legacy symbol is under
`match.imports` but not under `match.symbols` (resolution would never produce it), and a
`rename_import` change, since the module is not renamed and a shared module is rewritten at its
calls. The safety enum classes of a shared pack's `generative_model_calls` need no `symbols` entry:
the rule reads them for a member and never finds them as a usage. `spec_digest` leaves `ScanSpec.shared` out while it is false, so the recorded Gate 1 digest
of the Gemini pack did not move (ADR-024, ADR-050 D5).

### D3. `rewrite_call` can stay on the module

`root: module` spells `new_call` after the root expression the author wrote:
`oai.ChatCompletion.create(...)` becomes `oai.chat.completions.create(...)`, whatever name the file
bound the module to. It builds no client, so a pack with only module-rooted rewrites declares no
`configure_to_client` (ADR-050 D2 now asks for one only when a change is rooted on the client), and
`openai.api_key = ...` and `openai.organization = ...`, which 0.28.1 code sets at import time or
from another module, keep their meaning.

A call reached through `from openai import ChatCompletion` has no root to keep and is refused
(`from_import_unmigrated_symbol`). Only a module-rooted rule raises it, and
`rewrite_call.MODULE_BAILS` lists it so a test can grade it.

### D4. Keywords are an allowlist

`keywords` names the legacy parameters a call carries when they are **written as keywords**, beside
`positional_to_kw`, which lists the legacy positional order. A positional argument beyond
`positional_to_kw` is still `positional_arg_ambiguous`, and a keyword in neither list, or a `**`
splat, is `unsupported_kwarg`. The openai pack lists the request-body parameters 0.28.1 sent untouched
and every measured release still takes, and leaves out what 0.28.1 read itself (D1): `engine`,
`api_key`, `request_timeout`, `stream` and `timeout`, which 0.28.1 popped as a retry deadline and
never sent, where the new methods send it as the HTTP timeout, and `encoding_format`, which 0.28.1
asked base64 for and decoded itself. A name outside the list is refused, so a name nobody measured
never carries.

### D5. A result is read only along listed paths

`result_paths` lists the only reads of a call's result that carry: dotted attribute paths such as
`choices[].message.content`, where `[]` is an integer-literal subscript. A path ends in an attribute
and no path continues another. The reads are followed off the call itself and off the one name it is
assigned to, in that name's scope (D16 says which reads that counts). A string key that is the next
segment of a path is the same read written as a key (D18). Any other use is `response_shape_changed`:
a key off the path, `.get`, a loop over something that is not a list on the path, the result or a part
of it returned or passed on, a method on a path that is not a leaf (D20 says where a part may go). A
result nothing reads is fine. `result_paths` and `result_access_flags` exclude each other, since the
second refuses every use and the first would never be consulted. Both ways of knowing are
fail-closed.

### D6. One distribution makes the pin and the files one unit

`manifest_dependency` may name one distribution on both sides, which the schema used to refuse. The two sides are told apart by version, and `_check_version_ranges` still refuses ranges that overlap:
`openai==0.28.1` becomes `openai>=1.109.1` in one edit of one line, and a declaration already on the
new side is left alone (D11).


Where the new SDK is its own legacy distribution (`manifests.coupled`), a half-migrated repository
installs neither way: a file written for the new API fails on the old pin, and a file left behind
fails on the new one. ADR-010 F-2 assumed two distributions, so a partial migration could keep both
pins. Here atomicity is the repository's, in two places:

- **The survey.** `manifests.survey(..., paired=True)` counts any withheld row that is not
  `not_a_usage` as blocking. No import marks the old API (`import openai` is in both), so a withheld
    `openai.Image.create` is what keeps the pin, which reads `repo_not_fully_migrated`, or
  `transitive_dependency_in_use` when a file imports `requests` or `aiohttp` and no manifest declares
  it, or `manifest_pin_shape_unsupported` when the line cannot be written (D12).
- **The driver.** `codemod.run` asks `_unfinished`: is any row of the pack, in a file or a manifest,
    withheld? If so, `_together` leaves every file as it was and stamps each applied row
  `repo_not_fully_migrated`, an import row included (`models.IMPORT_BAILS`). A scan prints the pin
  row alone and keeps the eligible rows eligible, since it applies no rule.

**Rejected:** writing the files that migrate and leaving the pin (the code fails on the old pin);
moving the pin whatever else is left (the code left behind fails on the new one); and letting only an
import block, as for two distributions (the survey would never see the row that is withheld).

### D7. What the first version of the pack refuses, and why

The first version rewrites `ChatCompletion.create`, `Completion.create` and `Embedding.create`, and
reports the rest, because each of these is a measured way for the rewrite to be silently wrong.

| Surface | Why it is refused |
|---|---|
| `acreate` | The new module client has no async form: `AsyncOpenAI` is a client the file must build and close. |
| `stream=True`, `engine`, `deployment_id`, `request_timeout`, `timeout`, `api_key`, `api_base`, any other keyword, a positional argument, a splat | D1 and D4. |
| A result read with `.get`, by a key off the path, looped over, passed on or returned | D5, D18. |
| The thirteen module settings | Eleven do nothing on the new side, and nothing a scan, import or test of the migrated code shows. `api_type` and `api_version` choose Azure, once. `api_base` has a counterpart and is rewritten (ADR-055). |
| `openai.error`, `InvalidRequestError` | A handler for a name that is gone fails or never runs. |
| `openai.APIError` | **Deliberately not reported.** The name exists on both sides with other attributes, and code already on the new release writes `except openai.APIError`, so reporting it would keep every modern repository on the pack's list for good. The cost: a handler that reads `http_status`, `json_body` or `user_message` compiles and raises `AttributeError` once the pin moves, and nothing says so. It is a limitation of the pack. |
| `File`, `Model`, `FineTune`, `Edit` and the rest, the image edit and variation calls, the raw audio calls | Their replacements differ in shape, and the edits and fine-tunes endpoints were shut down. `Audio.transcribe` and `translate`, `Image.create` and `Moderation.create` were in this row until D19. |
| The twelve modules of the 0.28.1 package (`util`, `api_requestor`, ...) | None imports on 3.26.0, and `openai.cli` is another module on the releases that ship `openai migrate`. |
| Dynamic access, `mock.patch` targets, `sys.modules` stubs | The legacy name is a string, so no rewrite can follow it. The bare module fetched by its string is one too (D14). A target written against your own module is not seen. |
| `openai[datalib]` and other pins that name extras or a URL | The manifest rule cannot write the line, so the plan holds the repository (`manifest_pin_shape_unsupported`, D12). |


The repository is blocked, as ADR-050 D4 and D5 say, when it declares Python below 3.8, declares
openai below 0.28.1, or uses openai and declares it nowhere obelize reads.

### D8. The facts are tests, and the legacy side is frozen

0.28.1 and 1.109.1 cannot be installed together, because the module has one name. So the two sides
are held differently:

- The new side, names, parameters and result fields, is `tests/packs/test_openai_facts.py` against
  `openai==3.26.0` in the dev group, and weekly against 1.109.1, the floor of `to.version`. Each
  `keywords` entry is a parameter of its method, each `result_paths` segment a field of the model
  that call returns, and the pack's `to.requires_python` covers the Pythons the installed release
  declares, and equals them on the floor.
- The old side is `tests/packs/openai_legacy_surface.json`, a frozen snapshot of 0.28.1's names,
  submodules and error classes. `tests/packs/test_openai_facts.py` requires every name in it to be
  either listed in `match.symbols` or in a short `KEPT` set the new release defines with its old
  meaning (`OpenAIError`, `VERSION`, `api_key`, `organization`, `version`), or be `APIError`, which both
  sides define and the pack leaves unreported on purpose (D7), and not both. What 0.28.1's own imports
  leaked into its namespace (`os`, `sys`, `aiohttp`, `Optional`, ...) is not API and is exempt. That is the
  answer to D2's price. `tests/packs/openai_legacy_check.py`, standard library
  only, compares the snapshot to the real 0.28.1 weekly, with
  `uv run --isolated --no-project --python 3.12 --with openai==0.28.1`, and asserts the behaviours the
  refusals rest on.

The weekly job is `.github/workflows/e2e.yml`. Dependabot leaves the dev pin alone, since a newer
release is a different surface until it is measured, and the weekly job is what looks at the floor.

### D9. The target is 1.109.1, and the Pythons are the floor's

`to.version` is `>=1.109.1`. The first measured release that runs is the floor, because 1.0.0 to
1.50.0 fail at the first client on a fresh install (D1), and 1.51 to 1.108 were not measured. It is
chosen for the releases that run and not for a fix, unlike ADR-051 D1, which set pypdf's target above
the release whose surface matches because 97 advisories name it: OSV lists none for openai.
`to.requires_python` is `>=3.8`, what 1.109.1 declares. 2.34.0 needs 3.9 and 2.54.0 needs 3.10, and
pip picks the newest release a repository's Python installs, so the claims have to hold on every
release from the floor up, and were measured on the six between the floor and 3.26.0.

### D10. A shared pack's negative fixtures are scanned

A pack's negative fixture is normally one without a prefilter token, so the scan never parses it. The
token of a shared module, `openai`, is in every new-API file, so `tests/packs/test_all_packs.py` scans
a shared pack's negatives instead and requires no finding but `not_a_usage`. The cost is that a
repository using the new API only parses every file that names `openai`: about a tenth of a second
of CPU each, so three thousand such files are minutes of CPU, a fraction of that with the workers.
A file whose rendering overruns the stack (an `elif` ladder of hundreds of branches) is one
`parse_error` row, and holds the repository.

### D11. A declaration of the one distribution is legacy or arrived

Where `from` and `to` name one distribution, a manifest line that names it can be on either side:
`openai==0.28.1` is the old API and `openai>=1.109.1` the new. Rewriting both would move a migrated
repository backwards, or keep it on the pack's list for good. `ScanSpec.new_range` is the pack's
`to.version`, set only for such a pack and left out of `spec_digest` while unset, as `shared` is, and
`manifests._arrived` asks it: a declaration whose **lowest admitted version** is in `new_range` has
arrived, and is left as written with no row. The first version it admits decides, not the range:
`openai==3.26.0` and `openai>=2` have arrived, while `openai>=0.28.1,<3` admits the old API and is
rewritten to `openai>=1.109.1`, as is `openai>=1.0`, since 1.0 to 1.50 do not run (D9). A declaration
with no readable floor is legacy, and one that names no version never gets here, because the
repository is blocked first (`legacy_version_unsupported`). Only the pin line is left alone: a file of
such a repository that uses the old API is rewritten as before. The reading of a declared spec
(alternatives, `lowest`, Poetry's caret and tilde) moved from `scan/runtime.py` to `scan/manifests.py`,
which the legacy-floor check now shares.

### D12. A pin the rule cannot write holds the repository when the scan plans it

`manifest_dependency` refuses a declaration that names extras, a URL or a non-version value
(`manifest_pin_shape_unsupported`, ADR-030 D7) when it writes. With two distributions that leaves one
pin and the rest migrates. With one it left 1.x code beside a 0.28.1 pin, the half D6 exists to
prevent. So `manifests.plan` raises `SHAPE_BAIL` itself for a legacy declaration with no pin span,
once anything has migrated and only where `new_range` is set. The row is withheld, `_unfinished`
sees it, and `_together` leaves every file as it was. The scan prints the row and keeps the code rows
eligible, as in D6. The rule's own refusal stays for packs of two distributions. A declaration that
has arrived (D11) is never one: `openai[datalib]>=1.109.1` is left as written, and writing that
line by hand is how a user clears the hold.

### D13. A model is not asked about a pack that is its own target

A model's proposal is one row, and `--accept-model` writes it after the driver has decided what
moves (ADR-039). A proposal for one row of a pack that moves a whole repository or none would put a
file on the new API while the pin and the rest stay on the old, the half D6 forbids. So `fix` never
consults the model about such a pack. `--model`, `--accept-model` or `--show-context` with one exits `2`, and a model
only the user's file configures is skipped, with one line on stderr:
`The configured model was not asked: <pack> moves a whole repository.` ADR-052 D6's rule for several
packs is asked first and is unchanged.

### D14. A shared module reached without a name is a row

D2 makes `import openai` no finding, and that is why every other way to reach the bare module has to
be one: the module holds every legacy name, and a repository that gets at it by a string or by
reflection would read clean while the code breaks. In a shared module `importlib.import_module("openai")`,
`__import__("openai")` and `sys.modules["openai"]` are `dynamic_access` rows, as they are for a string
that names a legacy symbol. A read of `openai.__dict__` or `openai.__getattribute__` is a
`module_alias_rebound` row for the bare module, since the namespace those hand out holds the legacy
names. A star import is a row only from the module itself or from a legacy symbol: `from openai import *`
binds `ChatCompletion` and the rest, and `from openai.types import *` binds nothing legacy, so
reporting it would hold back a modern repository.

### D15. A read off a call's result is part of the call's row only where the module is shared

A shared pack's `result_paths` (D5) decides which reads of a call's result carry, so a second
attribute row for the read would withhold a call whose reads are all listed.
`analysis._shared_after_call` drops that row where `match.shared` is set. A pack that is not shared
keeps it: its `result_attribute_flags` and `result_access_flags` name fields and whole results, not
the paths a read may take, so the attribute row is the one guard against a read nobody vetted. The
Gemini results are byte-identical (`tests/oracle/`).

### D16. `result_paths` counts every read of the name, and refuses a class body

D5 follows the reads of the name a result is assigned to through the scope analysis. Two reads that
analysis does not link to the assignment count as reads of the result. A read above the assignment,
in a loop whose second pass reaches it, links to no assignment, so every unlinked read of the same
spelling counts. A result bound in a class body is read as `A.r` or `self.r`, which no scope links,
so the call is `response_shape_changed`. Both only refuse more, and only `result_paths` sees them: a
pack that names fields to refuse reads the linked reads alone, as before.

### D17. A call in an f-string field goes on one line

Before Python 3.12 a field of an f-string takes no newline, and the layout of ADR-026 wraps a call at
the pack's width. `rewrite_call` lays a call inside an f-string out on one line however long it is
(`Tree.in_f_string`). obelize's own output check runs on 3.12 or later, where the wrapped call is
valid, so only the rule can prevent it. The other rules still wrap there
([KNOWN_ISSUES.md](../KNOWN_ISSUES.md#the-openai-pack)).

### D18. A string key along a path is rewritten to the attribute

A 0.28.1 result is a `dict` subclass on which `r["choices"]` and `r.choices` read one field (D1), so
`r["choices"][0]["message"]["content"]` is a read along `choices[].message.content` and migrates as
`r.choices[0].message.content`. `rewrite_call` records the read next to the call and writes both in
the one pass, or neither: a call refused for another reason leaves its reads as written. A key
counts only when:

- it is a single string literal (no concatenation, f-string, bytes, star or trailing comma), the next
  segment of a listed path, and an identifier;
- the read loads: an assignment, `+=` or `del` through it is `response_shape_changed`. This is
  conservative, not measured: a new result is a model that accepts such writes;
- the name holds the result alone: one binding in its scope (a fallback `r = cached`, a parameter,
  a loop or `with` target, a `global` or `nonlocal` write each make a second, and a dictionary
  that binding holds would lose its keys), no read the scope analysis cannot link to the call
  (D16), and every read in the call's own function, since a closure or lambda runs when something
  calls it;
- no `try` around it has a handler that may name the missing key: `KeyError`, `LookupError`, or a
  name this file defines or leaves unresolved, which may be a tuple holding one; and no
  `contextlib.suppress` encloses it. The read would raise `AttributeError`, which only a bare
  `except:`, `Exception` or `AttributeError` catches, and a handler that never ran would hide the
  change. Imported exception classes are not looked into, nor is a handler in a caller: both go unseen;
- it is not in an f-string field written with `=`, which prints the source text, and no word follows
  it with no space (`r["id"]or 1`): the attribute ends in a name, and libcst refuses to join one to
  a keyword.

The replaced node is rebuilt over the value as already rewritten, not visited again, so nested calls
that read each other's results cost no more than nested calls do.

The format gains no field: whoever lists a path says both spellings read the same field of the
legacy result. `dict_reads` reads every listed path by its keys, a test
(`test_the_dict_reads_fixture_reads_every_listed_path_by_its_keys`) holds it to that, and the weekly
job prints the fixture's results on 0.28.1 and on 1.109.1 and the newest release and diffs them.
The other spellings stay refused: `.get` has a default where the attribute read raises, and a key
held in a name or an expression is not known to be on the path. A comment between the brackets of a
rewritten read is dropped, as for every rule.

### D19. Image, Moderation and Audio are rewritten

Four more calls are `rewrite_call` changes on the module, read and written as D3 to D5 and D18 say, with
no new rule kind and no new format value:

| 0.28.1 | Becomes | Positional, in the old order | Keywords | Reads that carry |
|---|---|---|---|---|
| `Image.create` | `images.generate` | none | `model`, `n`, `prompt`, `quality`, `size`, `style`, `user` | `created`, `data[].url` |
| `Moderation.create` | `moderations.create` | `input` | none | `id`, `model`, `results[].flagged` |
| `Audio.transcribe` | `audio.transcriptions.create` | `model`, `file` | `language`, `prompt`, `temperature` | `text` |
| `Audio.translate` | `audio.translations.create` | `model`, `file` | `prompt`, `temperature` | `text` |

The Gate 0 of D1 was run on these calls too, on 0.28.1 and on 1.109.1, 2.0.0, 2.54.0, 3.0.0 and 3.26.0:

- 0.28.1's `Image.create` reads five parameters itself, the first of them the API key, and sends every
  other keyword as the body. `images.generate` takes the seven listed keywords on every release.
- `Moderation.create(input, model=None, api_key=None)` and `Audio.transcribe(model, file, ...)` are the
  signatures whose positional order the pack states, and the legacy check compares them with the
  release (`openai_legacy_check.py`). The new methods are keyword-only, so the rewrite names them.
- The behaviour check prints the same results on 0.28.1 and on every new release above for an image,
  a moderation and both audio calls, reading the form fields as the server received them. A multipart
  upload carries `model`, `language`, `prompt` and `temperature` under the same names.

What a review of the first version changed, each confirmed by running both SDKs:

- A path lists a field the server sends whatever the call carries. D5 and D18 assume a field the
  result lacks raises on both sides, so a handler for the miss still runs. The new model declares
  `url`, `b64_json` and `revised_prompt` optional, and reads one the server left out as `None`: the
  handler stops running, as for the `KeyError` of D18, and no scan can see it. So `response_format` is
  not carried, `url` (what the default format returns) is the one listed path, and `b64_json` and
  `revised_prompt` are not. A model that returns no url whatever the format, `gpt-image-1`, is not caught.
- `Moderation.create` carries only `input`. 0.28.1 dropped a `model` of `None` from the body and
  raised `ValueError` before any request for a name other than two; the new method sends `"model":
  null`, and sends any name on. A call with a `model` is `unsupported_kwarg` or `positional_arg_ambiguous`.
- `response_format` of an audio call is not carried. `text`, `srt` and `vtt` return a string on both
  sides, and `verbose_json` a result with more fields than `text`, so one set of `result_paths` cannot
  hold for every value; the call is `unsupported_kwarg`.
- The categories of a moderation are not read. 0.28.1 keyed them `self-harm` and `hate/threatening`,
  which the new model spells with underscores and no read by key can be shown to mean the same, so a
  read of one is `response_shape_changed`.
- Measured and left as limitations of the pack, since no argument names them: the new client retries
  408, 409, 429 and 5xx twice and connects within 5 seconds, 0.28.1 retried connection errors only and
  allowed 600; `REQUESTS_CA_BUNDLE` is not read; HTTP-level test mocks stop intercepting; and an audio
  `file` that is not a binary file, bytes or a path (a Django upload) raises `RuntimeError`. These hold
  for every rule of the pack, and the pack's `limitations` say so.

A part of a result kept in a name is followed as D20 says. `Image.create_edit`, `create_variation`,
the `*_raw` audio calls and every `a`-prefixed method stay reported (`flag-resources`,
`flag-async-calls`), and a bare `openai.Image` or `from openai import Image` is `usage_unmapped` or
`from_import_unmigrated_symbol`, as for chat.

**Rejected:** carrying `response_format` for the values that return a string. The rule would have to
tell the values apart, which `dispatch_prefixes` cannot do for an argument left out, and a string
result is read as a string, which no `result_paths` expresses.

### D20. A part of a result kept in a name, and a loop over its items

D5 and D18 followed the call and the one name it is assigned to. Code that takes a part of a result
into a name of its own (`message = r["choices"][0]["message"]`, `choice = r.choices[0]`,
`usage = r["usage"]`) or walks a list of them (`for choice in r["choices"]`) is as common as the
reads that D5 lists, and until now held the repository. `rewrite_call` follows a read that stops at
a proper prefix of a listed path, a stem, into:

- the one name an assignment with a single name target gives it, and every read of that name; or
- the one name a `for` or comprehension binds to each item, when the stem and `[]` is itself a
  prefix of a path, since iterating a list reads the element that an integer subscript reads, and a
  0.28.1 list and a new one iterate alike.

Each name is held to the conditions D18 sets for the result's own name, and a key read through it is
rewritten to its attribute on the same terms:

- No name on the way is bound twice or by a walrus anywhere in the file (one in a comprehension binds
  the function's name, which the scope analysis lists in the comprehension's own scope), and none is
  rebound by `name |= x`, which reads the part and which no read lists. A name that may hold
  something else makes the keys read through it, and through every name copied from it,
  `response_shape_changed`; attribute reads of it are carried.
- No read of it that the analysis cannot link to it, or links to a name outside its scope (a read above
  its binding in a loop is the second pass's), no class body, and no file that mentions a way to reach
  a name by its string: `eval`, `exec`, `globals`, `locals`, `vars`, `f_locals`, `f_globals`,
  `currentframe`, `_getframe` or `__dict__`, called or not, since `f = locals` calls it unseen.
- Every keyed read in the call's own frame. A generator expression is a frame of its own, since it
  runs when something iterates it, possibly outside the handler around it, so a key read in one is
  refused, and so is a call inside one.
- The keys of each stretch of the chain placed as D18 says (no handler for a missing key, no `=`
  f-string, no word glued on).

A name chains into another (`n = m`). Each name is followed once per path from a worklist, so a name
that takes itself ends the walk and a chain of thousands costs the length of the file, and the reads
of a result's own name are gathered once for every call bound to it. An alias of the whole result,
the empty path, is still refused. A tuple target, an annotation, a chained assignment, a walrus and a
star are not names the rule follows, and a stem given to a call, returned, appended or put in a
container is `response_shape_changed` as before. The `result_names` fixture reads a part of a result
in a name and a loop over `choices` and `data`, and the weekly job prints its results on 0.28.1 and
on the new releases and diffs them.

**Rejected:** accepting `print(result)`. It reads no field, but 0.28.1 printed a result as JSON and
the new releases print a one-line repr, so a program whose output another reads (`| jq`) would change
with no error. A call given to `print` stays `response_shape_changed`.

### Review

Three adversarial reviewers each ran 150 to 450 inputs against the finished pack and the engine under
it. They found these classes, all fixed:

- A shared module reached with no name: fetched by its string, through `__dict__` or
  `__getattribute__`, or star-imported from a submodule it keeps (D14).
- A repository already on the new release: its declaration rewritten, or, with extras, left beside
  migrated code (D11, D12).
- A read of a result the scope analysis does not link to the call: in a loop, or on a class (D16).
- A read off a call's result folded into the call's row for a pack that is not shared, where the
  attribute row is the guard against an unvetted read (D15).
- A call wrapped inside an f-string field, which Python before 3.12 refuses (D17).
- A model proposal for one row of a pack that moves a whole repository (D13).
- A name modern code writes, `openai.APIError`, reported, which kept a repository already on the new
  release on the pack's list (D7).
- Pack format: a keyword renamed onto the configuration keyword was emitted twice, a shared pack's
  safety enum classes were asked to be in `match.symbols`, and the error for a call with no service
  named only the client.
- A part of a result in a name (D20), by five more reviewers: an alias or a loop variable that a walrus
  in a comprehension rebinds, a read above a loop's binding that the scope analysis links to a name
  outside, a key read in a generator expression that runs after the handler around it is gone, a name
  that takes itself or a chain of hundreds that overflowed the stack, a script that reuses two
  names 60 times, which took four minutes, a part rebound by `m |= {...}`, and a name read through
  `sys._getframe().f_locals` or an alias of `locals`.
- Crashes with a cause outside the pack: a `match` statement with a mapping pattern that captures a
  name broke the scan of every pack, two packs editing one `setup.py` broke `codemod.chained`, and a
  `setup.py` string literal Python cannot evaluate broke the manifest reader.

The gaps the review left open are in [KNOWN_ISSUES.md](../KNOWN_ISSUES.md#the-openai-pack).

## Consequences


- obelize ships three packs, listed by id: `gemini/google-generativeai-to-google-genai`,
  `openai/openai-0-to-1` and `py-pdf/pypdf2-to-pypdf`. The README, `docs/CLI.md` and the CI
  workflow name each, and `tests/packs/test_all_packs.py` fails when one does not.
- The pack format gains `match.shared`, `rewrite_call`'s `root`, `keywords` and `result_paths`, and
  a `manifest_dependency` on one distribution. No code, vocabulary or JSON Schema value is new:
  `from_import_unmigrated_symbol` is also raised by a module-rooted rule, `repo_not_fully_migrated`
  also lands on the source rows of a coupled pack, an import row included,
  `manifest_pin_shape_unsupported` is also raised by the scan for a coupled pack (D12), and
  `response_shape_changed` also means a read outside `result_paths`. `CHANGELOG.md` lists the format changes (ADR-048).
- One withheld row anywhere keeps every file as it was: a `.get` read of a result, an `openai.File`
  call, an undeclared `requests` import or a pin it cannot write leaves the repository unchanged,
  with exit `4`. Gate 1 is
  not measured for this pack, so no rate says how often. [KNOWN_ISSUES.md](../KNOWN_ISSUES.md#the-openai-pack)
  names this cost and the gaps that stay open.
- The fail-open of D2 is bounded by the snapshot: it covers every name 0.28.1 defines, and says
  nothing about what the pack does with a name it lists, which the fixtures grade. D14's rows cover
  the ways to reach the module with no name.
- `openai` is a development dependency pinned to 3.26.0, as `pypdf` and `PyPDF2` are to the releases
  they were measured on.
- Open:
  - Async: an `AsyncOpenAI` client the file builds and closes needs a placement rule, as in
    ADR-026.
  - Streaming: a `stream=True` result is read through its chunks, which have no `result_paths` yet.
  - Azure: `api_type`, `api_version`, `engine` and `deployment_id` become an `AzureOpenAI` client
    with an endpoint and an API version, which is a configuration rewrite across modules.
  - A `.get` read of a result, which has no attribute spelling that raises the same way.
  - Client-object output: `openai.OpenAI(...)` with the module settings moved into its construction,
    for code that needs the client itself.
