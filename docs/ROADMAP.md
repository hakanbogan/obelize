# Roadmap

## What works today

obelize migrates Python code from `google-generativeai`, the deprecated Gemini SDK, to
`google-genai`, from `PyPDF2` to `pypdf`, and from `openai` 0.x (0.27.0 and later) to 1.109.1 or
later. `scan` finds every call, import and dependency line the migrations touch. `fix` plans the
rewrite and, with `--apply`, writes it; `--verify` runs your tests before and after. `verify`
re-runs that check against an applied run, and `undo` puts the files back unless they were
hand-edited since. The Gemini pack covers the constructor, generation, chat, streaming, safety
settings, file uploads and dependency manifests, and flags every tool declaration for you; see
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

`numpy/numpy-1-to-2` is the first pack to run a maintained tool: its 23 rewrites are ruff's
`NPY201`, run from your `PATH` and kept only when the output holds to the proof of a rule's own
([why](adr/ADR-074-external-fixer.md)). It reports the other names NumPy 2 removed, holds the whole
repository back for any one of them, and has no Gate 1 measurement.

Three packs are for the Python itself, where no distribution is on one side
([why](adr/ADR-071-runtime-packs.md)). `python/datetime-utcnow` rewrites `utcnow()` and
`utcfromtimestamp(x)` to the spelling that keeps the value naive, importing `timezone` where the
file has no name for it. `setuptools/pkg-resources-to-importlib` reports every use of
`pkg_resources` with its replacement and writes nothing, since none is the same call under another
name, and `python/removed-stdlib-modules` renames `pipes.quote` and reports the rest of what Python
3.12 and 3.13 removed. A repository that declares a Python they do not run on is left alone. Like
the openai and PyPDF2 packs they have no Gate 1 measurement yet.

One optional model adapter can answer a call the pack cannot resolve on its own. It stays off
unless you configure an endpoint yourself. A guard checks each proposal before anything is
written: it must stay inside the lines it was shown and the file it was asked about, parse, and
add no import or name outside the question. That proves a proposal safe to write, not correct, so
an accepted one is still a line to review.

A library with no pack can be planned for too. `obelize outdated` lists the dependencies a repository
declares that the package index says have moved on. `obelize upgrade <distribution>` plans the move
with the pack that ships for it or, if there is none, with one it makes from two releases of the
library, which it reads without importing or building anything: a module-level name that the
library's own deprecation message says to replace is renamed, a name that moved up out of a submodule
is moved, and everything else that changed is flagged, with the library's message where it gave one. With `--apply --yes` it tries the move in a copy of the repository, in two
environments made with uv, compares your tests one by one before and after, and writes only if no
test that passed now fails ([the guide](UPGRADING.md)). `--branch` commits a passed move to a new
branch, with no hook, signature or push. `--agent claude_code` puts the places a pack can only flag,
and the tests the move broke, to your own `claude` program as a text-only model behind the same
guard. The network is optional: obelize names every index host before it contacts it, caches the
answers, and with `--offline` reads only the cache and keeps the trial's installs to uv's cache.
`scan` and `fix` stay off it.

Four runs on three public repositories passed their own tests before and after the move
([the runs](UPGRADING.md#runs-on-real-repositories)). That shows the steps join up, not how often a
move passes. The dry run without a pack is measured over 80 public repositories that use the old API
of pydantic 1, SQLAlchemy 1.4, urllib3 1 and pandas 2, and it writes no file: 36 stop before planning,
33 are held and 11 have no usage of a name the pack lists. It finds 944 usages: 78 are places a rule
would rewrite if nothing else were left in the repository (all in pydantic, `rename_member`), the pack
only flags 810 and 56 are held for a cause of its own, and none is in a file the dry run would write
([the numbers](BENCHMARK_RESULTS.md#upgrade-dry-run)). The benchmark of the trial itself, which
installs packages and runs the tests, is still to come.

A pack can say more than it could. `rename_member` renames a method or attribute of a library
class wherever the file shows what a receiver is, in a class of yours or in another file of the
repository ([why](adr/ADR-068-rename-member.md)), `rewrite_pattern` rewrites a call from the shape
of its arguments with two templates ([why](adr/ADR-069-rewrite-pattern.md)), and a plugin you
install and allow can provide a rule kind of its own ([why](adr/ADR-070-plugins.md), [how to
write one](PLUGINS.md)). `pack synth` writes the first for the methods a library's message plainly
replaces: pydantic 1 to 2 gives `parse_obj`, `construct`, `schema`, `dict`, `json` and
`update_forward_refs`.

What the authors of a library say only in prose can come in through `--guide`: a model you have set
up reads a migration guide and drafts claims, and a claim becomes part of the pack made from two
releases only if code finds its quote in the guide, its names in both releases and nothing in the API
diff against it. It becomes a report that quotes the guide, and a rewrite only where the quote says in
a known shape that the new name takes the place of the old one with nothing that limits it, and the
diff shows the old name going and the new one able to take its place
([why](adr/ADR-075-claims-from-a-guide.md)).

Around the commands are the pieces a pipeline and a coding agent use. `scan --library` lists every
use of a library that has no pack, `pack new` and `pack test` help write one, `scan --sarif` and
`--fail-on` serve a CI step, `verify --current` checks a tree that someone else edited, and
`obelize mcp`, `action.yml` and `.pre-commit-hooks.yaml` offer obelize to a coding agent and a
pipeline. The action also upgrades a dependency (`mode: upgrade`).

## Where it goes next

obelize is meant to upgrade a dependency without a pack someone wrote for it, and to check the
result with your tests in one command ([the decision](adr/ADR-059-verified-dependency-upgrades.md)).
The commands above are that path for a library whose changes two releases show, and on the 80
repositories measured so far it does not reach a written move: what stops it, and the choice I
have not made, are in [the known issues](KNOWN_ISSUES.md#upgrading-a-dependency). This is the order I
intend to build the rest in. Nothing below ships until the changelog says so, each step is its own
release, and an option I add defaults to today's behaviour.

1. More places. Use an agent program other than `claude` once one documents how to leave it no tool
   (`codex` does not yet: [why](adr/ADR-076-no-backend-for-codex-yet.md)), and let the kinds the
   bundled packs use cover more shapes. The command itself never pushes; the GitHub Action runs the
   trial in one job and a second job opens the pull request ([Upgrading in CI](UPGRADING_IN_CI.md)).
2. Ecosystem. A registry of packs, more existing fixers behind the same evidence (ruff's `NPY201`
   ships in `numpy/numpy-1-to-2`; the others need a target release a pack can state, [why](adr/ADR-074-external-fixer.md)), writing
   notebooks, and hand-checked packs for the libraries people ask about most.
3. 1.0. Stable formats, with only additions after it, and a published benchmark of the pack-free
   mode that includes the trial, which only its dry run has so far.

TypeScript is a separate plan.

## What the release accepts as a gap

Before opening the repository, I ran a security-focused pass over the whole codebase and fixed
what could hurt someone running obelize or a number published about it.
[THREAT_MODEL.md](THREAT_MODEL.md) lists every threat I considered, how obelize mitigates it and
which mitigations still read partial. [The accepted gaps](adr/ADR-048-accepted-gaps-in-0-1-0.md)
name the open gaps of the first release and why I shipped anyway, and
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) names the rest, including what a trial leaves open when it
installs packages.

## What is not planned

Everything else I know about and have chosen not to fix yet is in
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) instead of repeated here. [The product boundary](PRODUCT.md)
lists what I will not build.
