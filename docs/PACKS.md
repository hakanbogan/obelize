# Packs

A [migration pack](GLOSSARY.md#migration-pack) is a data file that describes one migration: the
symbols to find, the rule kind that rewrites each, and the official guide that backs it. obelize
ships seven, and runs every pack your repository uses, or the ones `--pack` names. Your own packs
can sit in a directory your `~/.config/obelize/config.yml` lists as `pack_dirs`; a repository's
`.obelize.yml` may not name one. [Pack format](PACK_SPEC.md) is the specification.

| Pack | Rewrites | Reports and leaves to you |
|---|---|---|
| `gemini/google-generativeai-to-google-genai` | The import, `configure`, the model object and its generation, chat and streaming calls, safety settings, file uploads and the dependency line. | Every tool declaration, since automatic function calling is on by default in `google-genai`. |
| `numpy/numpy-1-to-2` | Twenty-three names NumPy 2 removed, by ruff's `NPY201` and only with the proof of [numpy](#numpy), and the dependency line. | The other names NumPy 2 removed or moved, and what it changes besides names. |
| `openai/openai-0-to-1` | `openai.ChatCompletion.create`, `Completion.create`, `Embedding.create`, `Image.create`, `Moderation.create`, `Audio.transcribe` and `Audio.translate`, to the same calls on the module client (`openai.chat.completions.create`), the reads of their results by string keys, the assignment of `openai.api_base` as `openai.base_url`, the exception classes `RateLimitError`, `PermissionError` and `Timeout` as `RateLimitError`, `PermissionDeniedError` and `APITimeoutError`, and the dependency line. | Async and streamed calls, Azure, the other resources, the other module settings, which the new releases ignore, the other exception classes, and any call whose arguments or reads of its result it has not checked. |
| `py-pdf/pypdf2-to-pypdf` | The import, the names that exist unchanged on both sides, and the dependency line. | The camelCase classes PyPDF2 3.0.0 removed, the modules only PyPDF2 1 ships and the names pypdf dropped. |
| `python/datetime-utcnow` | `datetime.utcnow()` as `datetime.now(timezone.utc).replace(tzinfo=None)` and `utcfromtimestamp(x)` as `fromtimestamp(x, timezone.utc).replace(tzinfo=None)`, with the import of `timezone` they need. | A reference that is not a call, such as `field(default_factory=datetime.utcnow)`, and the choice to move to aware datetimes. |
| `setuptools/pkg-resources-to-importlib` | Nothing. | Every use of `pkg_resources`, with the replacement the documentation names. |
| `python/removed-stdlib-modules` | `pipes.quote` as `shlex.quote`. | The other uses of 20 modules that Python 3.12 and 3.13 removed, with where each went. |

## Gemini

The Gemini pack, `gemini/google-generativeai-to-google-genai`, declares the 16 changes the
migration makes and 23 limitations. The limitations say what it reports instead of rewriting, such
as every tool declaration, because automatic function calling is on by default in `google-genai`;
what it cannot find; and what it rewrites without having checked it against a live API call. `scan`
and `fix` print what a pack says about each surface it flags, and `REPORT.md` lists the limitations
of every pack that ran.

## openai

The `openai` pack builds no client object, so `openai.api_key` and `openai.organization` keep their
meaning. A 0.28.1 result is a dictionary and a new one is not, so it rewrites a call only when every
read of the result is a path it has checked, `response.choices[0].message.content` or the same path
as keys (`response["choices"][0]["message"]["content"]`, which it rewrites to the attribute form).
A call whose result is read with `.get` and a default, looped over or passed on is left to you. It
writes nothing while any place is left. The other two packs write each file they can migrate whole
and leave the rest.

OpenAI's own `openai migrate` command is gone (removed in `openai` 2.35.0). For `openai` 0.x,
`uvx obelize scan --pack openai/openai-0-to-1` lists every use it can resolve with the reason it
would leave it, and [KNOWN_ISSUES.md](KNOWN_ISSUES.md#the-openai-pack) says what it cannot see.

## numpy

The `numpy` pack carries no rewrite of its own. For the 23 names NumPy 2 removed that have a
replacement of the same meaning, the rewrite is ruff's `NPY201`, which obelize starts from your
`PATH` ([why](adr/ADR-074-external-fixer.md)). It installs nothing, and runs only a release it has
measured, 0.6.2 to 0.17.2; `obelize pack validate numpy/numpy-1-to-2` prints the command that
installs one. What the tool wrote is kept for a file only if it changed no line the scan did not
report, changes nothing when run on its own output, and leaves none of the names (`from numpy import
float_` it leaves standing, so that file stays as it was). The names are those that were the same
object or the same call on NumPy 1.26.4, so the rewritten code runs on both releases. Every other
name the migration guide lists is reported, and any one such place holds the whole repository back,
the dependency line included. Promotion, the default integer on Windows and the C API are not
names, and the tests are the check ([KNOWN_ISSUES.md](KNOWN_ISSUES.md) lists what it does not see).

## pypdf

The `PyPDF2` pack moves the import and the names both libraries share, and the dependency line.
`PyPDF2` itself warns that it "is deprecated. Please move to the `pypdf` library instead." What the
pack cannot move, such as the camelCase classes that `PyPDF2` 3.0.0 removed, stays in the report
([KNOWN_ISSUES.md](KNOWN_ISSUES.md#the-pypdf2-pack) lists what it does not see).

## The Python itself

Three packs name no distribution on one side or on both: a change of the interpreter or its
standard library is not a release of a library you install. They are written and tested like the
others, and [why a side can be the Python](adr/ADR-071-runtime-packs.md) says what that changes.

- A repository that declares a Python the new code does not run on is left alone, the way one that
  declares a Python `google-genai` does not install on is. `python/datetime-utcnow` needs 3.2,
  where `datetime.timezone` began, `setuptools/pkg-resources-to-importlib` needs 3.10, where
  `importlib.metadata.entry_points(group=)` began, and `python/removed-stdlib-modules` needs 3.3,
  where `shlex.quote` began. A repository that declares no Python is not blocked.
- No dependency line moves, since none names a distribution to move to. `obelize outdated` lists
  `setuptools` below 82 with the pack for `pkg_resources`, and `obelize upgrade pkg_resources` says
  it is no dependency and names the pack to run.
- `python/datetime-utcnow` keeps the value naive, as `utcnow()` made it. `now(timezone.utc)` alone
  is aware, and an aware and a naive datetime cannot be compared, so moving to aware values is
  yours to decide. It names `timezone` by whatever import of `datetime` the file has, and adds
  `from datetime import timezone` below the last import above the first call when it has none.
  A file that binds `timezone` to something else, or imports `datetime` only inside functions, is
  left as it was with the reason.
- `setuptools/pkg-resources-to-importlib` rewrites nothing. `setuptools` 82.0.0 removed
  `pkg_resources`, and the replacements are other objects with other errors:
  `importlib.metadata.version` takes a name and not a requirement, raises another class of error
  for a distribution that is not installed, and an entry point has no `require()`.
- `python/removed-stdlib-modules` leaves out `imp`, `uu`, `nis`, `crypt` and `chunk`, whose names
  sit inside common words, so that no scan has to parse most of a repository to look for them.

None of the three has been measured on public repositories, which a new pack for a library gets
first. [KNOWN_ISSUES.md](KNOWN_ISSUES.md) lists what they do not see.

## A library with no pack

`obelize pack synth <distribution> --from <version>` makes a pack for any library on the package
index, from what two of its releases export. It downloads the two releases and the newest of each
minor line between them (only their Python source is opened, and nothing is installed, built or
run), reads each one's public API statically, and compares them. What it can show, it writes:

- A name the library's own deprecation message says to replace, with one name beside it that exists
  in the newer release, is renamed; a call is rewritten too only when the signature did not change.
- A name that left a submodule for its package is moved up, if it kept its name and signature.
- Every other change is flagged, never rewritten, with the library's words where it gave any: a name
  that was removed, moved elsewhere or deprecated, a parameter that was renamed, removed, made
  required or given another default, a class whose bases changed. A function or a class whose
  changes are to its parameters is flagged at the calls those changes can break, and each such place
  says what in the call matched; a class whose bases changed, where code derives from it.
- The dependency line moves to the newer release and its major version.

For a name the newer release removed, the command also writes `hints.json` beside the pack: the
names that release has and the older one did not, closest first by the words in the name (`FastMCP`
and `MCPServer` share `mcp`) and, for a method, by place. They are guesses, shown to a person or to
the agent of [UPGRADING.md](UPGRADING.md) with the library's own words, and never written to your
code by a rule.

A pack names at most what fits in a pack file, a little under 1 MiB. For a library that changed
more than that (pandas between 1.5 and 2.2, for one) `pack synth` stops and says so, and
`--used-by <folder>` makes the pack for the names that folder's code reaches through its imports;
`obelize upgrade` does the same for the repository it is run on. Such a pack is a different pack,
so its id ends with a digest of those names, and it is not reused for another repository.

What two surfaces cannot show is what a function does. A pack made this way says so in its
limitations, cites the file of the newer release with its hash, and is never bundled: the
tests of your repository are what show whether a migration holds. A library that builds its exports
when it is imported (a module `__getattr__`, or `from other_package import *`) hides names, and the
command counts them instead of calling them removed. `pack synth` prints every host before it reaches it, and `--offline` uses only
what an earlier run kept.
