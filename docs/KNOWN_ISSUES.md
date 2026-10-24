# Known issues

I ran a full review of the codebase before opening the repository, and fixed what could hurt
someone running obelize or a number published about it. What is left is lower stakes: rough
edges, missing polish and gaps in the benchmark tooling. This page lists what I know about and
have chosen not to fix yet, grouped by area. The gaps that are actually safety-relevant are in
[THREAT_MODEL.md](THREAT_MODEL.md) instead, alongside what obelize already does about them; this
page does not repeat those.

## Trust and redaction gaps

The request timeout to a model endpoint (120 seconds, not a setting) bounds the reply body as a
whole, checked between reads, so a reply can run up to one read past it. It does not bound the wait
for the response headers or for the chunk-size line of a chunked reply, which the HTTP library
reads in a loop of its own: a server that drips either a byte at a time is held back only by the
socket timeout of each read, and can keep a run waiting far longer than 120 seconds.

## Model replies and editing

The syntax check on the file a model's proposal would produce still applies obelize's own `from
__future__ import annotations` to it, so on Python 3.12 and 3.13 it can refuse code that is valid,
such as a walrus in an annotation.

## Running commands

A few files of the run folder, such as `findings.json`, `REPORT.md` and `run.json`, are written in
place into a folder nothing has read yet, not by the temporary file and rename that the files on a
plan and the pointer `.obelize/latest` get. A run killed halfway can leave one of them short.
`journal.json` is written before any source file, and `run.json` and then `latest` last, so a short
file never misleads `undo` and `latest` always names a complete run.

## Scanning and rewriting

A file nested more than 300 levels deep (a chain of that many operands, attributes or calls, a
dotted name, an `elif` ladder, and about a hundred brackets inside brackets, which cost more) is
refused as a file that does not parse before libcst sees it, since libcst's parser can kill the
process on a chain that `compile()` accepts. The file is not edited and keeps the dependency pin,
and obelize does not take generated code of that shape. The count is measured against what the
scan's visitors survive: the codemod's own stack use per level is not, so a file just under the
limit can still overrun it, and is then left as it was. An implicit string concatenation is not
counted either. A few hundred parts are refused by libcst's own recursion limit, with the
sentence for invalid Python (500 parts were on Python 3.12, and 200 were not).

On Windows, blocks nested as deep as Python allows (99 `if` or `def` statements inside each other)
overflow the stack of libcst's native parser on CPython 3.12 and 3.15, and the process ends without
a report; 3.14 survives it. The depth gate does not see it, since 99 nested blocks cost fewer levels
than the limit, and the same file was parsed the same way before. The smallest depth that overflows
is not measured, and no real file is known to nest blocks past a few dozen. Linux and macOS parse
the 99.

Two rules pair a statement or an expression with its finding by the line it starts on rather than
by its binding; I know of no input where that pairs the wrong ones. The check for a module that
another file imports or reads a constant off matches modules by their last name, so another
package's `llm.py` counts (which errs toward holding), and it sees neither an `importlib` nor a
string import. A read of `response.text` is refused when a handler that could catch the old
`ValueError` surrounds it (that name, `Exception`, `BaseException` or a bare `except:`, in a `try`,
an `except*` or a `contextlib.suppress`), and any other read carries the `response_text_may_be_none`
warning. A handler in a caller, one that spells the error `builtins.ValueError` and an exception or
a `suppress` reached through a name first are not seen, so the call is rewritten with the warning
alone. Refusing on a bare or `Exception` handler is the price of failing closed: on the Gemini
frame it moved eight repositories from complete to held
([the dry run](BENCHMARK_RESULTS.md#fix-dry-run)).

A rewritten file upload carries the warning `upload_display_name_unset` where the call leaves out
`display_name`, and passes `name` as written. The old `upload_file` named the file after its path
when no `display_name` was given and the new `files.upload` sets none. The old call prefixed a name
with `files/` only when it held no slash, where the new one prefixes any name that does not start
with `files/`, so `name="a/b"` becomes `files/a/b`.

The dependency-file reader reads an `-r` or `-c` include of any name inside the repository (up to
eight includes deep, as an input that nothing writes), but does not read uv's `constraint-dependencies` and `override-dependencies`,
PDM's overrides or Hatch's matrix and `overrides` tables ([the openai pack](#the-openai-pack) lists
what that leaves behind). The Python gate reads `requires-python`, Poetry's `python`, `setup.cfg`'s
`python_requires`, a `Pipfile`'s `[requires]` and a `python_requires=` in `setup.py` written as a
string; one built from a variable, a call or an f-string, and a `.python-version`, `tox.ini` or
Dockerfile, say nothing to it. A pack of your own inside the repository leaves out of a scan only
its `fixtures/` directory: another file beside `pack.yaml` is scanned like your own code, and a
helper there that imports the legacy library holds the pin. A `pack.yaml` at the repository root
leaves out nothing.

A file half migrated by hand can still hold the whole repository when the new client is not a plain
name. A call on a name only ever assigned `genai.Client()` is no finding, but a client held on
`self`, passed in as a parameter or assigned something else too has a receiver that resolves to no
legacy model, so the scan reports it as `receiver_unresolved`
([the receiver rule](adr/ADR-019-resolution-detection-rules.md)), every other row of the file
becomes `file_not_fully_migrated` and the pin stays. The reverse is also unseen:
`genai.configure(...)` or `genai.GenerativeModel(...)` read off `from google import genai`, and
`from pypdf import PdfFileReader`, produce no row, because the file is never parsed (COVERAGE gap
36); the new module has neither name, so such code fails when it runs.

A rewritten import takes the place of the one it replaces, and a new `from google.genai import
types` follows it, so an import sorter may move them. obelize does not format: run your formatter
and sorter on the changed files after the run, then commit. Once you have formatted a file,
`obelize undo` reverts only the files still as it wrote them and would put back the dependency line
alone, and `obelize verify --run` reports `tree_changed`; use `git restore` instead. A lockfile
(`uv.lock`, `poetry.lock`, `Pipfile.lock`) is not read or written. After a manifest pin is written
the run names the lock files in that manifest's directory or above it and says to regenerate them
with the tool that made them; one in a sibling or a subdirectory is not named. The `PyPDF2` pack
does read one for another purpose: a lockfile in the repository stops it from taking an unpinned
requirement as 3.0.1, since the lock may pin another release ([the PyPDF2 pack](#the-pypdf2-pack)).

## Codemod editing quality

A comment inside a rewritten call or on a constructor the codemod deletes is kept, but not always
where it was: one beside an argument that moved into a configuration object goes on a line above
the statement, and the comments of a deleted constructor go above the next statement that stays. A
few passes do more work than they need to (a second scope resolution of the rewritten output):
`fix` takes about three seconds for a file of 800 calls and ten for 3,200, in step with the number
of calls.

## Plugins

A plugin is code of the user's, trusted as far as the user allowed it: it runs in obelize's process
with the user's rights, and obelize does not sandbox it, limit its time or its memory, or read what
it sends. The allowlist names a distribution and an entry point, not a release or a hash, so a
distribution updated after it was allowed is the one that runs; the run folder records the release
and the hash of the bytes of its `RECORD` (what `sha256sum` gives) to show which. An editable
install has a `RECORD` too, but one that lists a `.pth` file and the metadata, so its hash does not
change when the plugin's source does. Plugins are found with the working directory taken off the
path, which `python -m obelize` puts first, so a plugin developed in the directory a person runs
obelize from must be installed. A plugin is imported when a run loads a pack that requires it,
whether or not that pack finds anything; for every known pack (none named) a pack whose plugin is
not allowed is left out and said so. The interface is `obelize.plugin`, and it is not stable through
0.x beyond a line in the changelog; libcst's range is part of it.

## Members of a class

A pack that renames the member of a class (`rename_member`) renames it only where the scan can tell
what the receiver is. A value a function returned, a field of another object, an argument with no
annotation and a loop variable are left as they are, and are not reported, since reporting every
`.json()` of a file that also uses a model would drown the ones that matter. Where the library keeps
the old name working with a warning, as pydantic 2 does, what is left still runs. The classes that
derive from the library's are found in the files the walk selects, at their module level, by the name
an import gives them: a class made in a function or by `type(...)`, one in an excluded directory, and
one reached by `from module import *` are not found. A name the repository defines twice, once as a
class that derives from nothing, is not told from the derived one, and one that a module binds twice
is no class at all. If any class of the repository defines a member the pack renames (a method of
a subclass is enough), no read of that member off a receiver of the class is renamed, since the
receiver may be an instance of the subclass; the rows are held as `member_overridden`. A mixin that
comes from another library is not read for what it defines.

## Upgrading a dependency

[`obelize upgrade`](UPGRADING.md) writes a move to the whole repository or to none of it when the
library keeps its import name, since the old and the new API are then one distribution. A real
repository often has a place that a pack made from two releases can only flag, so the trial ends
`6` until a person or `--agent` has moved it. Writing the places that are safe to write while the rest
wait would leave a repository half migrated, which neither release installs.

A trial installs packages and runs their build scripts, and your tests, as you, on your machine,
with your network and your files in reach. The question it asks first is the only gate: nothing
sandboxes the installs or the tests, so run it only on a repository whose dependencies and tests
you would run anyway.

A pack made by `pack synth` reads a method through a class of yours only where the library's
message says plainly which method replaces it and a call can move to it; the others, such as
`copy`, are flagged where they are read off a receiver the scan can type, and not found where it
cannot ([members of a class](#members-of-a-class)). A method that is deprecated and still works is
therefore noticed only if a test breaks when it is read off a receiver nothing types, and the repair
rounds can put it to the agent only then.

A pack made from two releases flags a parameter that was renamed, removed or made required, and a
default that changed, in a sentence built from the two signatures. It does not rewrite the call. A requirement with
extras (`mcp[cli]>=1.28.1`) is not rewritten either: the dependency line is left, and the summary and
the commit message name it.

The environment for the release you use is made today, from the pins your files hold, so an
unpinned dependency resolves to its newest release there. A test that fails in it for that reason
fails before the move too and is not counted against it. A library that makes its names when it is
imported (pydantic 2's top level, for one) cannot be judged by reading its source: the names are
counted as ones obelize could not judge, and are neither migrated nor called removed.

`--agent` is asked about the places a pack flags only when the first run of the rules wrote nothing,
as it does for a library that keeps its import name. Where the rules did write some files, it sees
only the places where tests then broke. A flagged place in a test file is asked about like any
other, so the commit message, which names every file the agent edited, is where to look first.

A failing test whose error shows no line of your code, such as a wrong value with no traceback
through a file the move wrote, cannot be placed, and the agent is not asked about it. A library that
changed more names than a pack file holds gets a pack for the names your code reaches through its
imports, which is the smaller part of the library: a name reached any other way is not in it, and a
star import of the library is refused.

The pack made for a very large library (pandas) can repeat a name under each module that exports
it, so the file is large. `claude` is the one agent program obelize can use, and only the trial can
install anything, with uv. The agent is started the same way on Windows, but its tests stand in for
it with an executable script and run on Linux and macOS only.

## Data files and formats

The input documents refuse a number, flag or string of the wrong type. The JSON Schemas I
publish state the shape of each id, symbol, version, digest and display text, but not the rules on
a dotted call, a result path, a source URL or an environment variable name, PEP 440 specifiers,
sorted order or any rule that compares two fields, so a document can pass a schema and still fail
validation; `obelize pack validate` and the models are authoritative.

## The benchmark harness

The harness runs an unreviewed repository's own code without a sandbox and with the network
available to it, so the protocol says to run it only on a machine or VM that holds no credentials.
The commands get an allowlisted environment and a home directory of their own, and each step's
process group is killed when the step ends, but a child that starts a session of its own is not
reached. Round 1 recorded neither the installed packages nor the version of uv, so its environment
cannot be reproduced; later rounds resolve every install as of a recorded cutoff and record both.
Round 1's records name the initial public commit for every case whatever produced them; later
rounds record the commit and tree state at the start and refuse to run on a dirty tree. One
published rate (the after-run column of the suite table) was measured with the legacy SDK still
installed beside the new one; the protocol says so, and round 1 stands as measured. The harness
keeps its own copy of the rule for whether a command is pytest, held to the one `obelize verify`
uses by a test but not shared with it.

## Continuous integration

A few checks run more than once across different jobs, each pair for a different surface: the
schema drift job and its test, `pack validate` in the smoke job and in the pack tests, the example
flow in the tests and again from a built wheel, `uv build` in four places. Dependabot ignores the
libraries the packs are measured against (both Gemini SDKs, `PyPDF2`, `pypdf` and `openai`) on
purpose, while the weekly end-to-end job installs the newest `google-genai`, `pypdf` and `openai`
to check the packs' claims; the `>2.24.0` and `>6.19.0` in that job are copied by hand from the
lock file, and nothing checks them. The secret-scanning configuration only excludes
`tests/fixtures/**`, so a new planted credential outside it has to be built by concatenation, as
`tests/unit/test_verify_redact.py` does. The workflow audit (zizmor) lets a `docker://` step image
pinned only by a tag through, so `tests/unit/test_workflows.py` refuses one; an image given as a
job's `container:` or `services:` is not checked. No workflow uses either.

## Code health

There is an import cycle between `obelize.impact` and `obelize.scan`. `tests/unit/test_import_graph.py`
pins it, so that no second one appears.

## The openai pack

`openai/openai-0-to-1` writes nothing until it can write everything, because `openai` 0.x and 1.x
are one distribution and a half-migrated repository installs neither way. A single place it
withholds anywhere in the repository (an `openai.File` call, an async or a streamed call, a `.get`
read of a result with a default, a notebook that calls the legacy API, a file that does not parse
or that obelize raised an unexpected error on, a module `openai` 0.28.1 installed that an app
imports and no requirements file can declare, or a dependency line it cannot rewrite in place)
leaves every file and the pin as they were, and an apply exits `4`. `obelize scan` grades files one
at a time, so it can show rows `eligible` that `fix` then withholds. The pack has no Gate 1 result.
The [dry run](BENCHMARK_RESULTS.md#fix-dry-run) counts those withheld rows and the repositories
they leave unchanged. Writing the async, streamed, Azure, `File` or `FineTune` calls it withholds
would free at most one repository of that 80-repository frame each, so none is written.

An `openai` declaration with no lower bound (`openai`, `openai<1`, `openai>=0.20`) is migrated only
where code uses `openai.ChatCompletion` or `openai.Audio`, which no release below 0.27.0 defines and
1.x turned into stubs that raise. The run takes the declaration as a release in `>=0.27.0,<1` and
says so (`packs[].assumed` holds the range). That is a claim about an install nobody ran: an
environment, a mirror or a package that caps `openai` outside the repository's files can have
another release, and what [the PyPDF2 pack](#the-pypdf2-pack) lists as unseen is unseen here too.
Code that calls only `Completion`, `Embedding` or `error` (which 0.26 and older define too), an
undeclared `openai`, and a pin below 0.27.0 stay `legacy_version_unsupported`.

A pin that admits only 0.x (`openai==0.28.1`, `openai<1`, `openai~=0.28.0`) beside code that uses
`openai.OpenAI`, `AsyncOpenAI` or `AzureOpenAI` is a `manifest_code_mismatch` row for review, and
nothing is written. The code is found from a file's imports and the attributes of what they bind,
so a client reached through `getattr`, or a class of that name from another module, is not seen.
Any file of the repository counts, not only the app's own: in a monorepo, a pin another app keeps
on purpose reads as a mismatch while a second app uses the new client. A pin that admits a 1.x
release (`openai`, `openai>=0.27`) is not judged.

A 0.28.1 result could be read as a dictionary, and a read by key raises on a 1.x result. A read by
string keys along a path the pack lists (`response["choices"][0]["message"]["content"]`) is
rewritten to the attribute path with the call, and so is one through a name that holds a part of
the result (`message = response["choices"][0]["message"]`, `for choice in response["choices"]`); a
comment written between or inside the brackets of a rewritten read moves to a line above its
statement. A one-argument `response.get("choices")` is rewritten to
`getattr(response, "choices", None)`. `.get` with a default, a key the pack does not list, a part or
the result handed on, and `print(response)` (0.28.1 printed JSON and the new releases print a repr)
are `response_shape_changed`, and by the paragraph above each holds back the repository. So does a
key read of a name that may hold something else (a fallback `r = cached`, a parameter, a loop or
`with` target, a walrus, `m |= x`, a read above its binding in a loop), a file that mentions
`locals`, `eval`, `__dict__` or a frame's variables, a key read in a closure, a lambda or a
generator expression, one in an f-string field written with `=`, one inside a `try` or `except*`
whose handler may name a missing key (`KeyError`, `LookupError`, a name the file defines or leaves
unresolved, or an imported class other than a short list of standard library ones, so
`requests.RequestException` withholds the read) or inside `contextlib.suppress`, where the
attribute read raises `AttributeError` and that handler would stop running, and a result bound to a
module-level name (also by `global`) that another module imports or reads off the module. Modules
are matched by their last name, so another package's `a.py` counts, and only a module that names
`openai` (or one of the modules `openai` 0.28.1 installed) is read: one that imports the name and
never says so goes unseen, and its dictionary read fails at run time. Still unseen: a handler in a
caller of the function that holds the read, and a name read by its string by other means (`getattr`
on a module). A test that replaces the module a function imports with one that returns dictionaries
breaks with the call, as the verify commands show.

`openai.api_base = value` is rewritten to `openai.base_url = value` with a `/` on the end, because
the new module client joins a route onto it unseparated. A read of `openai.api_base` (a library
that prints or extends it), `+=`, `del` and a tuple target withhold the repository, as does
`from openai import api_base` and a file that already uses `openai.base_url`. Not seen: a read of
the setting in another distribution, a write through `exec`, `globals()`, `sys.modules` or
`setattr`, and `OPENAI_API_BASE` set outside the code (the new releases read `OPENAI_BASE_URL`). A
value that is not a string literal is written as `("%s" % (value,)).rstrip("/") + "/"`, which forms
the address once, at the assignment, where 0.28.1 formed it at each request. A value that is no URL
(`None`, an empty string) fails at the first call on both sides, and one with leading whitespace,
which 0.28.1 sent through `requests`, fails on the new releases. A long line can pass the
formatter's width, and ruff's `UP031` flags the `%` format, which is kept so that a file rebinding
`str` is still rewritten ([the setting rule](adr/ADR-055-rename-setting.md)).

The pack lists a result field only when a response always carries it. The new model reads an
optional field the server left out as `None`, where 0.28.1 raised, so a handler that relied on the
miss stops running. `Image.create` is where it shows: `data[].url` is the one image field listed,
and `response_format` is not carried, since a base64 response has no url. A model written out as a
string that does not begin with `dall-e` is refused (`gpt-image-1` returns no url whatever the
format); a call with no model is sent as it was and answered by the API default, and a model held
in a name or built up is not looked into.

The new module client also differs from 0.28.1 where no argument names it, for every call the pack
rewrites. It retries a request that fails with 408, 409, 429, a 5xx status or a timeout twice, where
0.28.1 retried connection errors only, and connects within 5 seconds, where 0.28.1 allowed 600
(`openai.max_retries` and `openai.timeout` set them). `engine=` of a chat, completion or embedding
call is carried as `model=`, and `request_timeout=` as `timeout=` when it is a number written out
above zero. 0.28.1 sent an engine in the URL (`/engines/<name>/...`) where the new methods send the
model in the body, so the call reaches the API by another route, and a timed-out request is sent
again twice with that timeout. `deployment_id`, `api_key` and `timeout` stay refused, and so do an
`engine` beside `model` and a `request_timeout` that is a name, zero or a tuple.
The new client does not read `REQUESTS_CA_BUNDLE`, and a test that intercepts `requests` no longer
sees the call. The file of an audio call must be a binary file, bytes or a path: an object with a
`name` and a `read` method that is none of them, a Django upload, raised nothing on 0.28.1 and
raises `RuntimeError` now.

`openai.error.RateLimitError`, `PermissionError` (as `PermissionDeniedError`) and `Timeout` (as
`APITimeoutError`) are rewritten, in a reference, in `import openai.error` and in
`from openai.error import X`, because a local server shows that the same responses raise them on
0.28.1 and on the new releases. The rest of `openai.error` is reported, with a message that says
what each class became: `OpenAIError` and `AuthenticationError` (a missing key is a bare
`OpenAIError` up to openai 2.0 and a `TypeError` from 2.54, and an empty 200 body a
`JSONDecodeError`), `InvalidRequestError` (three classes), `APIError`, `APIConnectionError` and
`ServiceUnavailableError` (bases that catch more), `TryAgain`, `InvalidAPIType` and
`SignatureVerificationError`. A renamed class that is called, raised or derived from, a handler that
reads an attribute of its error, a handler ahead of it in the same `try` that names `openai.APIError`,
`APIConnectionError`, `APIStatusError` or a class the rule cannot tell, and a name the file already
binds hold the file back. Not seen: a handler in a caller or reached by a name, a class kept in a
name and called later (`E = openai.error.RateLimitError; raise E("x")`) or given to a mock, which fail
with a `TypeError`, `getattr(error, "http_status")`, and the new text of `str(error)`. A response that
is no API error (a proxy's HTML page) was an `APIError` on 0.28.1 and is the class of its status now.
A handler for `openai.APIError`, which exists on both sides, catches every status error on the new
releases where it caught only the 5xx and malformed responses, so a rate limit or a refusal that
0.28.1 let through to a handler further out is caught there.

Top-level `openai.APIError` and `openai.OpenAIError` are not reported as names, since code already
on the new release writes `except openai.APIError`. A read of `http_status`, `json_body` or
`user_message` off the name of a handler for either is `attribute_removed`, and so is one behind a
`hasattr` guard. The same read through another name (`except Exception as e`) fails with
`AttributeError` once the pin moves, and obelize says nothing: search for those three names after a
run.

A requirement that names extras or a URL, such as `openai[datalib]==0.28.1`, or is hash-pinned,
continued over lines, editable or a local wheel, cannot be rewritten in place. The scan marks the
line `manifest_pin_shape_unsupported`, and `fix` leaves every file as it was, each row
`repo_not_fully_migrated`, and exits `4`. The report names the line. Write the new pin into it by
hand (`openai[datalib]>=1.109.1`) and run again: a declaration whose lowest admitted version is
already 1.109.1 or later is left as written.

A module `openai` 0.28.1 installed (`requests`, `aiohttp`, `tqdm` and what those bring) that a file
imports and no manifest of its app declares is declared by name, with no version, below the `openai`
requirement nearest that file in a requirements file as the pin moves, so the app gets whichever
release resolves, not the one 0.28.1 installed. The name carries no hash: for a file installed with
`--require-hashes`, declare it by hand. Where the `openai` requirement is in `pyproject.toml`,
`setup.cfg`, `setup.py`, a `Pipfile` or a constraints file, or no requirement is at or above the
file, the pin waits for you to declare it (`transitive_dependency_in_use`). The app is the directory
of the manifest, so a declaration in another app's manifest does not count.

The new releases read `OPENAI_BASE_URL` and `OPENAI_ORG_ID`, where 0.28.1 read `OPENAI_API_BASE` and
`OPENAI_ORGANIZATION`. A gateway or an organization set only through the environment is lost
without an error once the pin moves. A write of either old name in the code (`os.environ[...] =`,
`setdefault`, `putenv`, or a dict literal handed to `update` or `patch.dict`) is reported and holds
the repository; one set in a shell, a `.env` file or a deployment, `monkeypatch.setenv` and a name
held in a variable are not seen. Rename them where they are set. `OPENAI_API_KEY` is the same on
both sides.

A notebook that names the library is read as code (its cells in order, a line starting with `!` or
`%` skipped) and holds the pin only where a cell calls the legacy API, with the cell numbered; it is
never written, so migrate it by hand or list it under `exclude`. Under a narrower `include`, or
where `exclude` takes it, it is not read. IPython syntax other than line and cell magics
(`x = !ls`, `obj?`), a notebook that is not nbformat 4, and a cell magic whose body is not Python
(`%%writefile requirements.txt`) make a notebook that does not compile: it holds the pin, and the
limitation names the cell. A `%%bash`, `%%sh`, `%%script`, `%%html`, `%%markdown`, `%%latex`,
`%%javascript`, `%%js` or `%%svg` cell is left out. The terminal summary, the output of `fix` and
`REPORT.md` name a file that uses the legacy API and that no rule writes (a notebook, with its cells,
or a stub), also where the pin has already moved and the run would otherwise say that no pack
applies; `scan --json` and `run.json` carry no row for it.

Where the pack does not look, and what that costs. A legacy name in the first three is neither
migrated nor reported, and the pin still moves when everything else does:

- A name another of your modules re-exports (`from mylib import openai`), a client built in another
  file, and `pytest.importorskip("openai")`. The module is followed inside one file. Search for
  them before you apply.
- A patch target the pack does not read: `monkeypatch.setitem(sys.modules, ...)` and the keyword form
  `patch.dict(sys.modules, openai=fake)`. A target that starts at `openai` or sits under a package of
  your own (`mock.patch("myapp.llm.openai.ChatCompletion.create")`), a `patch.object` of an expression
  spelled to end in `.openai` with a legacy leaf and a dict literal handed to
  `patch.dict(sys.modules, ...)` are reported, and a package of yours with its own `openai` module and
  a class of a legacy name is a false hold. The test keeps patching a name that no longer exists, so
  change the target by hand once the code has moved.
- Files outside `.obelize.yml`'s `include` and `exclude`. They are neither migrated nor checked,
  and the pin moves. `REPORT.md` lists an excluded file that names the distribution. It says nothing
  of a file under an always-excluded directory such as `vendor/` or `build/`. Run this pack over the
  whole repository.
- A legacy name inside a string annotation is reported (`usage_unmapped`) when it is spelled
  `openai.X`, however deep (`Optional["openai.Image"]`), since a pydantic model evaluates it when the
  class is built. One the string reaches through an alias (`"oa.Image"`) is not seen.
- A file obelize does not read: a script with no `.py` name, a `.pyx`. A `.py` file over
  `max_file_bytes`, or one that cannot be opened, holds the pin in this pack and the report names
  it; raise `max_file_bytes` or list the file under `exclude`.
- Spellings Python folds to the same name, such as fullwidth letters in `openai`: the scan reads
  the text as written.
- The names a result is read through when the file reads names by their strings: a file that calls
  `locals()`, `globals()`, `vars()`, `eval` or `exec` holds every call whose result is bound to a
  name, which is the safe answer and often more than the file needs.
- A dependency in a form obelize does not read: an `-r` or `-c` include of a file outside the
  repository, more than eight includes deep, or whose argument holds a blank or a quote (a file
  inside the repository is read as an input whatever its name, and never written), a `Dockerfile`
  pip line, `environment.yml` and `tox.ini`, and uv,
  PDM and Hatch tables other than the dependency arrays (see Scanning and rewriting). A
  `setup.py` whose requirements variable is bound more than once, augmented (`+=`), annotated, a
  dict or built from other code, or given to a call (`sorted(REQS)`) or unpacked (`*REQS`) is not
  read either. The old pin stays there with no row. Search for `openai==` after a run.
- A form it reads but cannot honour is `manifest_pin_shape_unsupported`, and a coupled pack holds the
  repository until you change the line by hand: a hash-pinned or continued line, an editable or VCS
  requirement, a local wheel, a `setup.cfg` line with a trailing comment (setuptools rejects it too),
  a dependency given as a table of its own (`[tool.poetry.dependencies.openai]`, also the dev, group
  and Pipfile forms), a Poetry or Pipfile inline table with another key beside the version (extras, a
  marker, git, path), and a legacy pin in a `requirements.in`, a constraints file or a file that only an include names,
  which are read but never written. `openai===0.28.1`, `openai==0.*`, and an editable requirement or wheel (whose
  version is not read) are also `legacy_version_unsupported`. The `PyPDF2` pack uses the same files
  differently: several of them stop an unpinned requirement from being taken as 3.0.1, though a
  PyPDF2 pin that stays in one of them is still left alone ([the PyPDF2 pack](#the-pypdf2-pack)).

Writing is per file, not for the repository. A failure part-way (exit `5`, for example a read-only
directory) can leave the code written and the pin not, or the reverse. `obelize undo --run <id>`
restores every byte it wrote.

The token `openai` is in every file that uses the new API too, so a repository already on the new
release parses every such file: about a tenth of a second of CPU each, a few minutes for three
thousand files, with the workers a fraction of that.

## The PyPDF2 pack

A `PyPDF2` requirement with no version, or with a range that reaches below 3 but admits 3.0.1
(`PyPDF2>=2.10`), is taken as 3.0.1, the last release PyPI has, unless the repository shows another
one ([the newest-release decision](adr/ADR-056-newest-legacy-release.md)); the run says it did. That is a claim about an
install nobody ran, and it is wrong where the evidence is not in the repository's files:

- The environment the code runs in. A virtual environment outside the repository, a container image
  built earlier or a CI cache can hold PyPDF2 1.26 or 2.x while the manifest says nothing.
- Installer settings outside the repository: a `pip.conf` in the home directory, `PIP_*`
  environment variables (`PIP_INDEX_URL`, `PIP_CONSTRAINT`, `PIP_FIND_LINKS`, `PIP_NO_INDEX`), an
  index mirror that lags. They are not read on purpose: the machine that scans is not the one that
  installs, and a finding is the same on every machine that scans the same files. A repository that
  depends on one pins the release in a manifest obelize reads.
- A release another package requires. `pip` resolves the whole set, so a dependency that caps
  PyPDF2 below 3 holds it back, and that cap is in no file obelize reads.
- A directory that is not the top of a git repository. The fallback walk skips dot-directories, so
  nothing is taken there and the run is blocked as an unpinned requirement is; the message says that
  obelize lists every file only at the top of a git repository, and to run it there or pin PyPDF2.
- A submodule's files, an ignored lock, requirements, constraints or `.in` file anywhere but beside
  the root or a manifest that declares PyPDF2, and an ignored `.venv`, `venv` or `env` in a
  directory that holds no listed file.
- A file over 32 MiB, one that cannot be opened, and a UTF-16 file over `max_file_bytes` (2,000,000
  bytes by default): the search for a version does not read them; the report names a file over 32 MiB
  (a `file_too_large` limitation) where the run took a release, and not the other two. A file over `max_file_bytes` up to 32 MiB is searched in windows and never held whole.
- Code that uses what 3.0.1 lacks (`PdfFileReader`, `PdfFileWriter`, `PdfFileMerger`, and the modules
  `PyPDF2.pdf`, `PyPDF2.utils` and `PyPDF2.merger`) is evidence of an older release wherever it is
  written, a notebook, a Python 2 file, a stub, excluded code and prose included, but by its name
  only: `from PyPDF2 import utils` with nothing that uses the name is not read, and neither is a
  file the previous bullet lists.

The evidence is broad on purpose, so some repositories stop that would have migrated. A
`PyPDF2==1.26.0` in a Dockerfile, a CI file or a comment of any file git lists counts, and so does
prose that names `PdfFileReader`. A `requirements.in` or constraints file that names `PyPDF2` with
no version stops the run (a bare name there is not read), and so does a constraints file that names
a release below 3 or an option that moves the index; a `dev-requirements.txt`, an input or a
constraints file that says nothing of PyPDF2 does not. Pinning `PyPDF2>=3` in a manifest obelize
reads ends the question, and the message says where.

A `PyPDF2` requirement the edit cannot rewrite in place (extras such as `PyPDF2[crypto]`, a hash on
it or a continuation of it, an editable or VCS requirement, a local wheel) is left with a
`manifest_pin_shape_unsupported` row, and the code still moves to `pypdf`: the manifest keeps
`PyPDF2`, so change that line by hand. The pack does not hold on it, as the coupled `openai` pack
does.

The camelCase API of PyPDF2 1.x and 2.x (`PdfFileReader`, `PdfFileWriter`, `PdfFileMerger`,
`getPage`) is flagged and never rewritten. PyPDF2 3.0.0 turned the classes into errors, the
suggestion on the row names what each member became, and a repository that uses them is blocked from
taking an unversioned `PyPDF2` as 3.0.1. Releases 1.x and 2.x are not migrated: they differ from
3.0.1 in the default of `strict`, the sign of a rotation, the spacing of `extractText` and the
signature of `merge*Page`, and the pack's
[SOURCES.md](../src/obelize/packs/py-pdf/pypdf2-to-pypdf/SOURCES.md) has the measurements.

## The packs for the Python itself

`python/datetime-utcnow`, `setuptools/pkg-resources-to-importlib` and
`python/removed-stdlib-modules` have not been run over public repositories, so how often they
write, and how often they leave a file whole for one line, is not known.

- A scan of every pack parses each file that holds a pack's prefilter token, once per pack.
  `datetime` is in a large share of a repository's files, so a default scan, which runs every known
  pack, parses those files for `python/datetime-utcnow` as well. Pass `--pack` to name the packs a
  run needs.
- `python/datetime-utcnow` rewrites calls and nothing else. `field(default_factory=datetime.utcnow)`
  and a SQLAlchemy `default=datetime.utcnow` are references, reported as unmapped, and one of them
  keeps its whole file as it was. A test that replaces `datetime` in a module of its own with a mock
  is not seen, and fails after the rewrite because the mock answers `now`, not `utcnow`.
- Its new import is one line, `from datetime import timezone`, below the last top-level import above
  the first call, and is not merged into a `from datetime import ...` line that is there. A file
  that imports only inside functions, or that binds `timezone` to something else anywhere, is left
  as it was with `local_import` or `alias_collision`.
- `setuptools/pkg-resources-to-importlib` writes nothing and is gated at Python 3.10, so a library
  that supports 3.9 gets `runtime_unsupported` on every row and not the replacement it would have
  named. The backport `importlib_metadata` is not suggested.
- `python/removed-stdlib-modules` leaves out `imp`, `uu`, `nis`, `crypt` and `chunk`. A scan finds
  a file by a token inside the module's name, and those names sit inside `import`, `uuid`,
  `finish`, `encrypt` and `chunk`: a pack that matched them would parse most of a repository on
  every scan. A repository that still imports `imp` has to be migrated by hand.
- `obelize outdated` lists `setuptools` with the pack for `pkg_resources` whenever it is declared
  below 82 or without a release, which includes a build requirement that never imports
  `pkg_resources`.

## What actually gets migrated

Measured against a real sample of repositories, only a small fraction of eligible call sites
actually migrate end to end, and a repository coming out the other side with every test still
passing is rare. For most repositories, obelize's scan and its automatic rewrites are a starting
point; finishing the migration still takes a person.
