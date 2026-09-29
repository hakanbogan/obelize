# ADR-003: Model adapter

## Status

Accepted.

## Decision

Phase 3 ships **exactly one model adapter**: an OpenAI-compatible
chat-completions HTTP adapter on stdlib `urllib`, so it adds no runtime
dependency, at `src/obelize/providers/openai_compat.py` behind the
`ModelProvider` protocol in `providers/base.py`. One wire format reaches Ollama,
OpenAI, OpenRouter and Anthropic's compatibility layer. It asks for a JSON
`response_format` and falls back to fenced JSON for endpoints that ignore it.

Configuration is the `model` key of the user's own
`~/.config/obelize/config.yml`: `provider: none | openai_compat`, `base_url`,
`model`, `api_key_env` (default `OBELIZE_MODEL_API_KEY`), `log_prompts: false`;
`--model` replaces `provider`. A `model:` block in a repository's `.obelize.yml` exits 2
before any adapter is built, because where code and a credential are sent is
the runner's choice. Claude Code headless and Codex CLI adapters are excluded
until their licensing terms are verified in writing.

The trust rules, because repository text is untrusted input to the model (threat
model B2) and its output an untrusted proposal (B3):

1. The model is consulted **only for `needs_review` cases**, never for a call
   site the deterministic rules can rewrite.
2. The context sent is the enclosing function or class range plus the rule
   message and the pack note, redacted through `src/obelize/verify/redact.py`.
   `--show-context` prints the exact payload.
3. The system prompt is fixed; repository text is delimited data, never
   instructions. The model must return a structured edit proposal as JSON; prose
   is a failure.
4. The returned `EditProposal` is **untrusted** and must pass
   `providers/guard.py`: the target is a `.py` file in the impact plan inside the
   repository root; the recorded before-hash matches the disk; the result parses
   and compiles; the diff is within the size limit; it introduces no import
   beyond `to.package`, and every name it uses is bound by the replaced lines,
   the replacement or a target import, or is an admitted builtin; the edit must
   stay inside the range that was sent as context, and the target symbol must
   exist.
5. A proposal that passes becomes a `model_proposed` edit, applied only when the
   user passes both `--apply` and the explicit `--accept-model` flag, and
   verified like any other edit: the guard proves an edit is *safe to apply*,
   not that it is *correct*.
6. Every proposal is recorded under `model/proposals-<n>.json`: context ranges,
   prompt sha256, provider, model, token counts, the proposal and the guard
   decision. The raw prompt is stored only when `model.log_prompts` is true.
7. Network access exists only for this adapter, only to the endpoint the user
   configured. The endpoint host is printed at the start of the run. There is no
   pack download and no telemetry (boundary B6).

## Consequences

- The model is the fallback, not the product: with `provider: none`, the default,
  `needs_review` cases are reported with a suggested snippet and a reason code.
- Structured output is not uniformly available: the Anthropic compatibility layer
  ignores `response_format` and `strict`, so the fenced-JSON fallback is tested.
- Rejecting a proposal is a normal outcome: the tree is unchanged, the case `needs_review`.
