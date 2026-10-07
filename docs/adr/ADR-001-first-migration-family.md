# ADR-001: First migration family

## Status

Accepted; amended by ADR-050 and ADR-051.

## Decision

The first v0 migration family is **`google-generativeai` ->
`google-genai`**, shipped as the bundled pack
`gemini/google-generativeai-to-google-genai`. The rule kind registry (ADR-006) was proven against
this one family first; a second family, `PyPDF2` -> `pypdf` (ADR-051), shows that the pack format
and not Gemini is what the engine depends on. There is no "any SDK" abstraction beyond the kinds.

Chosen because the old SDK reached end of life on 2025-11-30 yet still installs,
the corpus is large enough for the dev/holdout benchmark (`docs/BENCHMARK.md`),
no codemod exists for it, so that benchmark's ground truth is hand-labelled, and
every rule can cite Google's official side-by-side guide:
<https://ai.google.dev/gemini-api/docs/migrate>.

## Consequences

- The parts that are not 1:1 (the automatic function calling default, safety enum names,
  the embedding response shape, client setup in another module) are declared in the pack's
  `limitations` and reported as `needs_review`.
- Repositories that declare a Python below the pack's `to.requires_python` (`>=3.10`) cannot
  install `google-genai`, so scan reports them as `blocked: runtime_unsupported` instead of
  proposing a migration.
