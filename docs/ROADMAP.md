# Roadmap

## What works today

obelize migrates Python code from `google-generativeai`, the deprecated Gemini SDK, to
`google-genai`, from `PyPDF2` to `pypdf`, and from `openai` 0.x (0.27.0 and later) to 1.109.1 or
later. `scan` finds every call, import and dependency line the migrations touch. `fix` plans the
rewrite and, with `--apply`, writes it; `--verify` runs your tests before and after. `verify`
re-runs that check against an applied run, and `undo` puts the files back unless they were
hand-edited since. The Gemini pack covers the constructor, generation, chat, streaming, safety
settings, tool declarations, file uploads and dependency manifests; see
[the README's commands table](../README.md#commands) for the full surface and
[BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for what it actually migrates end to end.

A run uses every pack the repository needs, in one pass over one read, and packs of your own can
sit in a directory your config lists ([why](adr/ADR-052-several-packs-per-run.md)).

`openai/openai-0-to-1` is the pack for a library that keeps its import name across a major version
([why](adr/ADR-053-shared-module-migrations.md)). It rewrites `openai.ChatCompletion.create`,
`Completion.create`, `Embedding.create`, `Image.create`, `Moderation.create`, `Audio.transcribe` and
`Audio.translate` to the same calls on the 1.x module client, and only when every argument and every
read of the result is one it has checked. It reports async calls, streaming, Azure, the other
resources, the settings (but `openai.api_base`, which it
[renames](adr/ADR-055-rename-setting.md)) and the exception classes the new SDK changed (but
`RateLimitError`, `PermissionError` and `Timeout`, which it
[renames](adr/ADR-057-rename-symbol.md)), and it writes nothing while any one of them is left,
because `openai` 0.x and 1.x are one distribution. What stays out: a client object, a `.get` read of
a result with a default, and a Gate 1 measurement, which neither of the two newer packs has. Another
library that keeps its import name needs the same measurement before it gets a pack.

One optional model adapter can answer a call the pack cannot resolve on its own. It stays off
unless you configure an endpoint yourself. A guard checks each proposal before anything is
written: it must stay inside the lines it was shown and the file it was asked about, parse, and
add no import or name outside the question. That proves a proposal safe to write, not correct, so
an accepted one is still a line to review.

## Where it goes next

obelize is meant to upgrade a dependency without a pack someone wrote for it, and to check the
result with your tests in one command ([the decision](adr/ADR-059-verified-dependency-upgrades.md)).
This is the order I intend to build it in. Nothing below ships until the changelog says so, each
step is its own release, and an option I add defaults to today's behaviour.

1. Reach. List the places a library with no pack affects (`scan --library`), generalise the rule
   kinds the three packs already use, add `pack new` and `pack test` for writing a pack, print
   SARIF and fail a CI step on what is left (`--fail-on`), and offer obelize to a coding agent
   through an MCP server, a GitHub Action and a pre-commit hook.
2. Extension. Rename a method or attribute across a class hierarchy, rewrite a pattern a pack
   declares, and load rule kinds from Python plugins you install and allow.
3. Packs without writing them. Read a package index and two releases' API, draft a pack from what
   changed, read a migration guide, and offer `outdated` and a dry-run `upgrade`. The network is
   optional, every host is named before the request, and `--offline` always works. A model can be
   your own coding agent as well as an endpoint.
4. The autonomous loop. Build the old and the new release in isolated environments, compare the
   result of every test, let rules and a model edit the same file, repair what the change newly
   broke within a few rounds, and leave the result in your working tree or on a branch you ask
   for. A GitHub Action can open the pull request. The command never pushes.
5. Ecosystem. A registry of packs, existing fixers such as ruff behind the same evidence, writing
   notebooks, packs for the Python runtime itself (`pkg_resources`, the modules PEP 594 removed,
   `datetime.utcnow`) and hand-checked packs for the libraries people ask about most.
6. 1.0. Stable formats, with only additions after it, and a published benchmark of the pack-free
   mode.

TypeScript is a separate plan.

## What the release accepts as a gap

Before opening the repository, I ran a security-focused pass over the whole codebase and fixed
what could hurt someone running obelize or a number published about it.
[THREAT_MODEL.md](THREAT_MODEL.md) lists every threat I considered and how obelize mitigates
it; four of those mitigations still read partial for this release.
[The accepted gaps](adr/ADR-048-accepted-gaps-in-0-1-0.md) name each open gap and why I am
shipping anyway.

## What is not planned

Everything else I know about and have chosen not to fix yet is in
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) instead of repeated here. [The product boundary](PRODUCT.md)
lists what I will not build.
