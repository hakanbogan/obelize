# Roadmap

## What works today

obelize migrates Python code from `google-generativeai`, the deprecated Gemini SDK, to
`google-genai`. `scan` finds every call, import and dependency line the migration touches.
`fix` plans the rewrite and, with `--apply`, writes it; `--verify` runs your tests before and
after. `verify` re-runs that check against an applied run, and `undo` puts the files back
unless they were hand-edited since. The bundled pack covers the constructor, generation, chat,
streaming, safety settings, tool declarations, file uploads and dependency manifests; see
[README's commands table](../README.md#commands) for the full surface and
[BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for what it actually migrates end to end.

One optional model adapter can answer a call the pack cannot resolve on its own. It stays off
unless you configure an endpoint yourself, and whatever it proposes still has to pass the same
guard a human edit would before anything is written.

## What 0.1.0 accepts as a gap

Before opening the repository, I ran a security-focused pass over the whole codebase and fixed
what could hurt someone running obelize or a number published about it.
[THREAT_MODEL.md](THREAT_MODEL.md) lists every threat I considered and how obelize mitigates
it; four of those mitigations still read partial for this release.
[ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md) names each open gap and why I am shipping
anyway.

## What is not planned

Everything else I know about and have chosen not to fix yet is in
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) instead of repeated here. Two bigger directions are open
questions rather than accepted gaps: finding migrations for a dependency with no bundled pack,
and checking an HTTP API integration after the other side changes. I will decide on both after
the first release, from what people report and ask for.
