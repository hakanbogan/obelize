# Known issues

I ran a full review of the codebase before opening the repository, and fixed what could hurt
someone running obelize or a number published about it. What is left is lower stakes: rough
edges, missing polish and gaps in the benchmark tooling. This page lists what I know about and
have chosen not to fix yet, grouped by area. The gaps that are actually safety-relevant are in
[THREAT_MODEL.md](THREAT_MODEL.md) instead, alongside what obelize already does about them; this
page does not repeat those.

## Trust and redaction gaps

A plain `http://` model endpoint to a non-loopback host is still accepted. A `base_url` with a
query string or fragment is accepted too, and either can end up in an error message. A relative
`XDG_CONFIG_HOME` is honoured as given, so a user's own configuration can resolve to a path
inside the repository being scanned. Approving a new verification command overwrites the stored
text of an earlier approval rather than adding to it. The request timeout bounds each read from
the network, not the whole request, so a slow reply in small pieces can run far longer than the
configured limit. A few sentences in the documentation cite the wrong safeguard for the wrong
risk; they need a pass to line back up with what the code does.

## Model replies and editing

Context sent to a model has no line numbers, and the text a proposal claims to replace is not
checked against what is actually there, so a reply that is off by one line can delete the wrong
one. A reply nested deep enough, while still within the size limit, can crash the parser that
reads it. A very unusual reply, such as deeply nested JSON or a credential-shaped string that
itself contains an error, can raise an exception that escapes uncaught instead of being reported
as a normal refusal. The path that builds and sends a consultation also does more re-parsing and
re-serialising than it needs to.

## Running commands

An invalid entry in the local list of pre-approved verification commands can still crash instead
of exiting cleanly, the way an invalid `--verify` or `--model` value now does. A baseline command
that modifies a tracked file makes an apply refuse, but the summary does not say the tests did
it. A stored configuration file or run record that is unreadable or holds an unexpected field
blocks `undo` instead of explaining what is wrong. There is no check that a directory is writable
before a migration starts, so a read-only one can be left half migrated. A few files, including
`.obelize/latest` itself, are written by truncating and rewriting rather than by the same
crash-safe rename the rest of the run folder uses. The `fix` summary gives counts of what changed
without saying why an item was left for review or what to do about it. A refusal partway through a
run can still leave the CLI's documented promise that "a refused apply runs no command" untrue,
since a baseline can have already run before the refusal.

## Report and terminal output

A file's own name is untrusted text: an unusual one can inject Markdown into the generated report
or control characters into a terminal that prints it.

Some hints give a POSIX spelling on Windows. The hint after a baseline that failed in obelize's
own environment shows `.venv/bin/python`, the refusal of a command that needs a shell advises
`sh -c`, which a Windows machine may not have, and the `--jobs` help does not mention the limit of
61 that Windows enforces.

## Scanning and rewriting

The syntax check obelize runs before touching a file inherits `from __future__ import
annotations` from its own source, so it can refuse code that is actually valid. A very long chain
of operators can crash the scan with a recursion error, or segfault it outright once the chain is
long enough. Several matching rules key off a spelling or a line position rather than the actual
binding, which can both over-match and under-match in unusual code: a private import used without
a version bound on the library that defines it, a combined import whose surviving names can
shadow the standard library's own `types` module, and a `.text` read rewritten with no warning
when no named handler recognises it. One migration pack's stated limitation does not match what
its rule actually does, and a refusal it declares is never raised. Two call arguments,
`embed_content`'s `task_type` and a dictionary `system_instruction`, are carried into the
rewritten call verbatim instead of through the same alias handling other arguments get. The
dependency-file reader misses some standard pip syntax and misreads uv, hatch and pdm tables; the
Python-floor check ignores `Pipfile`'s own `[requires]`. A directory of your own packs that sits
inside the repository is scanned like any other path, so its fixtures are rewritten unless `exclude`
names it.

## Codemod editing quality

A defect in one file can abort an entire run instead of being reported against that file alone,
and so can an unvalidated string that ends up somewhere a stricter type was expected. A comment
inside a rewritten call's arguments, or on a statement the codemod deletes, is lost rather than
kept. A few passes, including how a module gets re-rendered and how repeated attribute lookups
are computed, do more work than they need to and slow a migration down on a large file.

## Data files and formats

The YAML and TOML readers can raise an uncaught parsing error instead of a clean exit. A YAML set
is accepted where the pack format actually cares about order, and a duplicate key is handled in a
way that breaks merge keys and gets slower the more of them there are. The data models validate
loosely enough to coerce a wrong type rather than reject it. `.obelize.yml` is read through a
symbolic link with no size limit. The JSON Schemas I publish do not carry the same value rules the
code enforces, so a document can pass the schema and still fail validation. A file upload rule
also drops a default display name the legacy SDK used to set and changes how a name is
normalised; I have not yet measured how often that matters in practice.

## Tests and fixtures

The test suite has no shared setup, so around 40 files repeat the same fixture-building code by
hand, and the repository walk, a scan, a file read and running the codemod are each reimplemented
several different ways across the tests. Parsing the benchmark's YAML and rebuilding parsed state
account for a large share of how long the whole suite takes to run. A few tests race a short
deadline against how long the interpreter takes to start, share one mutable fixture repository, or
no longer test what their name claims. A number of no-cover markers hide code that is either
still reachable or simply dead and could be deleted.

## The benchmark harness

The harness runs an unreviewed repository's own code without a sandbox, with every environment
secret, the real home directory and the network available to it. Its subprocess helper can hang
waiting on a pipe a background process it started still holds open. A repeated run cannot
reproduce the environment an earlier one used. One published rate was measured with the legacy
SDK still installed alongside the new one, and a headline figure is divided by a different count
than the one printed next to it. The commit recorded as having produced a result is not always the
one that did. A large batch of cases that should never be reported on is never actually checked,
and the harness's own detection of whether a test run passed has drifted from the copy the product
ships. The harness itself is around 13 loose scripts sharing private helpers through path
manipulation rather than a package with its own tests.

## Continuous integration

A few checks run more than once across different jobs. Dependency pinning and the versions of the
tools themselves need a pass. Dependabot never proposes an upgrade for the one dependency the migration
targets, while the scheduled end-to-end job always installs its latest release regardless, so the
two can drift apart. The ruff version is set in two separate places, no job in continuous
integration runs pre-commit itself, and the secret-scanning configuration only excludes the test
fixtures directory rather than every path a planted example could reach.

## Documentation and examples

Some docstrings, comments and specification sentences describe an older version of the code they
sit next to. The bundled example application still defaults to model names that have since been
retired, and its own note about how it was scanned contradicts a limitation the migration pack
itself declares. The JSON Schemas shipped inside the wheel embed links and design notes meant for
this repository, not for someone who only installed the package.

## Code health

A little dead or test-only code remains in the package, a few small utilities are duplicated
across modules, there is an import cycle between two packages, and one module has grown very
large. A handful of docstrings still point forward to work that has since shipped.

## The openai pack

`openai/openai-0-to-1` writes nothing until it can write everything, because `openai` 0.x and 1.x
are one distribution and a half-migrated repository installs neither way. A single place it
withholds anywhere in the repository (an `openai.Image` call, an async or a streamed call, a
`.get` read of a result, a file that does not parse, an import of `requests`, `aiohttp` or another
module `openai` 0.28.1 installed that no manifest declares, or a dependency line it cannot rewrite
in place) leaves every file and the pin as they were, and an apply exits `4`. `obelize scan` grades files one at a time, so it can show rows
`eligible` that `fix` then withholds. I have not measured how many repositories that is: the pack
has no Gate 1 result.

A 0.28.1 result could be read as a dictionary, and a read by key raises on a 1.x result. A read by
string keys along a path the pack lists (`response["choices"][0]["message"]["content"]`) is rewritten
to the attribute path with the call. `response.get("choices")`, a key the pack does not list, a loop
over the result and the result handed on are `response_shape_changed`, and by the paragraph above
each holds back the repository. So does a key read of a name that may hold something else (a
fallback `r = cached`, a parameter, a loop or `with` target), a key read in a closure or a lambda, one
in an f-string field written with `=`, and one inside a `try` whose handler may name a missing key
(`KeyError`, `LookupError`, a name the file defines or leaves unresolved) or inside
`contextlib.suppress`: the attribute read raises `AttributeError` and that handler would stop
running. Still unseen: a handler in a caller of the function that holds the read, an imported
exception class that subclasses `KeyError`, and a comment between the brackets of a rewritten read,
which is dropped. A test that replaces the module a function imports with one that returns
dictionaries breaks with the call, as the verify commands show.

A result bound to a module-level name that another module imports is checked for reads in the file
that binds it only. A dictionary-style read in the importing module goes unseen, so the call is
rewritten and that read fails at run time.

A requirement that names extras or a URL, such as `openai[datalib]==0.28.1`, cannot be rewritten in
place. The scan marks the line `manifest_pin_shape_unsupported`, and `fix` leaves every file as it
was, each row `repo_not_fully_migrated`, and exits `4`. The report names the line. Write the new pin
into it by hand (`openai[datalib]>=1.109.1`) and run again: a declaration whose lowest admitted
version is already 1.109.1 or later is left as written.

The new releases read `OPENAI_BASE_URL` and `OPENAI_ORG_ID`, where 0.28.1 read `OPENAI_API_BASE`
and `OPENAI_ORGANIZATION`. A gateway or an organization set only through the environment is lost
without an error once the pin moves, and the pack does not look at environment variables. Rename
them where they are set. `OPENAI_API_KEY` is the same on both sides.

Top-level `openai.APIError` is not reported. It exists on both sides, and code already on the new
release writes `except openai.APIError`, so reporting it would keep every modern repository on the
pack's list. A handler for it that reads `http_status`, `json_body` or `user_message` fails with
`AttributeError` once the pin moves, and obelize says nothing: search for those three names after a
run.

Where the pack does not look, and what that costs. A legacy name in the first three is neither
migrated nor reported, and the pin still moves when everything else does:

- A name another of your modules re-exports (`from mylib import openai`), a client built in another
  file, and `pytest.importorskip("openai")`. The module is followed inside one file. Search for
  them before you apply.
- A patch target written against your own module: `mock.patch("myapp.llm.openai.ChatCompletion.create")`,
  `patch.object(myapp.llm.openai, ...)` and `mock.patch.dict(sys.modules, {...})`. Only a target that
  starts at `openai` is reported. The test keeps patching a name that no longer exists, so change the
  target by hand once the code has moved.
- Files outside `.obelize.yml`'s `include` and `exclude`. They are neither migrated nor checked,
  and the pin moves. `REPORT.md` lists an excluded file that names the distribution. It says nothing
  of a file under an always-excluded directory such as `vendor/` or `build/`, or of a `.py` file an
  `include` leaves out. Run this pack over the whole repository.
- Which app declares a module. The check for what 0.28.1 installed (`requests`, `aiohttp`,
  `urllib3`, `certifi`, `tqdm` and what those bring, listed in the pack's `match.transitive`) asks
  whether any manifest in the repository declares it, so in a monorepo a module one app declares
  counts as declared for all of them, and the pin can move while another app loses a library
  `openai` 0.28.1 installed for it.
- A file obelize does not read: one over the size limit or that it cannot open, a script with no
  `.py` name, a `.pyx` or a notebook an `include` leaves out. The report lists the first two as
  limitations, the pin moves beside them, and a legacy call in one fails at run time.
- Spellings Python folds to the same name, such as fullwidth letters in `openai`: the scan reads
  the text as written.
- The names a result is read through when the file reads names by their strings: a file that calls
  `locals()`, `globals()`, `vars()`, `eval` or `exec` holds every call whose result is bound to a
  name, which is the safe answer and often more than the file needs.
- A dependency in a form obelize does not read: `dev-requirements.txt` (only `requirements*.txt` and
  `requirements/*.txt` match), `requirements.in`, a constraints file, an `-r` include of a name
  that does not match, a `Dockerfile` pip line, a `setup.py` that assigns the requirements to a
    variable first, a `setup.cfg` line with a trailing comment, `[tool.uv] dev-dependencies`,
  `[tool.pdm.dev-dependencies]`, the `[tool.poetry.dependencies.openai]` table form, `environment.yml`
  and `tox.ini`. The old pin stays there with no row. Search for `openai==` after a run. A form it
  reads but cannot honour blocks the repository instead: a hash-pinned line, `openai===0.28.1`,
  `openai==0.*`, an editable or VCS requirement and a local wheel are `legacy_version_unsupported`,
  and a Poetry or Pipfile inline table with only a version is `manifest_pin_shape_unsupported`.

Writing is per file, not for the repository. A failure part-way (exit `5`, for example a read-only
directory) can leave the code written and the pin not, or the reverse. `obelize undo --run <id>`
restores every byte it wrote.

A rewritten call has three rough edges. An f-string `=` specifier prints the call's source text,
which the rewrite changes. A comment inside the replaced call is dropped, as for every rule:
between its arguments, in the dotted callee, or after its opening parenthesis. A call inside a
multi-line bracket is laid out at its statement's indent, which compiles and reads oddly. And a rule other than `rewrite_call` may wrap a call inside a single-line f-string, which
Python before 3.12 refuses and obelize's own check, running on 3.12 or later, accepts;
`rewrite_call` lays such a call out on one line. Separately, a chain of hundreds of terms (an `elif` ladder, a long `+`) cannot be rendered back
to bytes, so the file is a `parse_error` row and holds the repository, as under Scanning and
rewriting; it takes generated code.

The token `openai` is in every file that uses the new API too, so a repository already on the new
release parses every such file: about a tenth of a second of CPU each, a few minutes for three
thousand files, with the workers a fraction of that.

## What actually gets migrated

Measured against a real sample of repositories, only a small fraction of eligible call sites
actually migrate end to end, and a repository coming out the other side with every test still
passing is rare. For most repositories, obelize's scan and its automatic rewrites are a starting
point; finishing the migration still takes a person.
