# Packs

A [migration pack](GLOSSARY.md#migration-pack) is a data file that describes one migration: the
symbols to find, the rule kind that rewrites each, and the official guide that backs it. obelize
ships three, and runs every pack your repository uses, or the ones `--pack` names. Your own packs
can sit in a directory your `~/.config/obelize/config.yml` lists as `pack_dirs`; a repository's
`.obelize.yml` may not name one. [Pack format](PACK_SPEC.md) is the specification.

| Pack | Rewrites | Reports and leaves to you |
|---|---|---|
| `gemini/google-generativeai-to-google-genai` | The import, `configure`, the model object and its generation, chat and streaming calls, safety settings, file uploads and the dependency line. | Every tool declaration, since automatic function calling is on by default in `google-genai`. |
| `openai/openai-0-to-1` | `openai.ChatCompletion.create`, `Completion.create`, `Embedding.create`, `Image.create`, `Moderation.create`, `Audio.transcribe` and `Audio.translate`, to the same calls on the module client (`openai.chat.completions.create`), the reads of their results by string keys, the assignment of `openai.api_base` as `openai.base_url`, the exception classes `RateLimitError`, `PermissionError` and `Timeout` as `RateLimitError`, `PermissionDeniedError` and `APITimeoutError`, and the dependency line. | Async and streamed calls, Azure, the other resources, the other module settings, which the new releases ignore, the other exception classes, and any call whose arguments or reads of its result it has not checked. |
| `py-pdf/pypdf2-to-pypdf` | The import, the names that exist unchanged on both sides, and the dependency line. | The camelCase classes PyPDF2 3.0.0 removed, the modules only PyPDF2 1 ships and the names pypdf dropped. |

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

## pypdf

The `PyPDF2` pack moves the import and the names both libraries share, and the dependency line.
`PyPDF2` itself warns that it "is deprecated. Please move to the `pypdf` library instead." What the
pack cannot move, such as the camelCase classes that `PyPDF2` 3.0.0 removed, stays in the report
([KNOWN_ISSUES.md](KNOWN_ISSUES.md#the-pypdf2-pack) lists what it does not see).

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
  required or given another default, a class whose bases changed.
- The dependency line moves to the newer release and its major version.

For a name the newer release removed, the command also writes `hints.json` beside the pack: the
names that release has and the older one did not, closest first by the words in the name (`FastMCP`
and `MCPServer` share `mcp`) and, for a method, by place. They are guesses, shown to a person or to
the agent of [UPGRADING.md](UPGRADING.md) with the library's own words, and never written to your
code by a rule.

What two surfaces cannot show is what a function does. A pack made this way says so in its
limitations, cites the file of the newer release with its hash, and is never bundled: the
tests of your repository are what show whether a migration holds. A library that builds its exports
when it is imported (a module `__getattr__`, or `from other_package import *`) hides names, and the
command counts them instead of calling them removed. `pack synth` prints every host before it reaches it, and `--offline` uses only
what an earlier run kept.
