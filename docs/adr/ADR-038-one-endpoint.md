# ADR-038: One endpoint

## Status

Accepted; amended by ADR-039 (D10).

## Decision

### D1. Nine words for what an adapter could not answer

`ProviderError` carries one word of the closed `models.ProviderFailure`, in the
order the bytes reach each stage: `endpoint_unreachable` (nothing answered, or
not in time), `endpoint_redirected` (a 3xx, D7), `endpoint_refused` (any other
status outside 200-299), `response_too_large`, `response_not_json`,
`response_not_a_completion` (no `choices[0].message.content` string),
`answer_not_json` (no object by any of D6's readings), `answer_not_a_proposal`,
`proposal_does_not_hold` (`EditProposal` refuses it: unanswered, not refused).
A `Reply` with `None` is an answer, not a failure.

### D2. The system prompt is fixed, the user message is facts and one file, and the delimiter is not a boundary

The system message is a constant naming no pack or file; it asks for what the
guard enforces, including that `__import__` and `importlib.import_module` are
imports. The user message is eight labelled facts from `Consultation`, the pack
note, and the redacted context between two marker lines. The markers only aid
reading; `providers/guard.py` is the boundary.

### D3. The pack note is sent whole

All of `Consultation.limitations`, in the pack's order, after a sentence saying
it is background and not the task. Because ADR-036 D1 never sends a row the
pack refuses by policy, and nothing in the data links a limitation to a bail.

### D4. The column is not sent

The message carries the line and the symbol only. Because `Finding.column` is
0-based where every line number here is 1-based, and the guard does not read it.

### D5. One request per consultation, no retries, and a deadline in code

No retry: a 429 is `endpoint_refused` with the endpoint's own sentence. The body
is JSON with sorted keys, so the same question is the same bytes.
`REQUEST_TIMEOUT_S = 120`, deliberately not a configuration key, and below
verification's 600 s, which is for a whole test suite. Because a retry resends
source code for a row that is already `needs_review`, and 120 s is enough for a
local model on a CPU.

### D6. Three readings of the content, in a fixed order

The first reading that yields a JSON object wins: the whole content, then each
fenced block, then the span from the first `{` to the last `}`. The object must
be the envelope `{"proposal": <object or null>}`; a bare proposal is
`answer_not_a_proposal`. Because the envelope separates "an edit" from "none",
and being generous to a malformed answer is being generous to an untrusted one.

### D7. The request goes to the host that was configured, and to no other

The `model:` block comes only from the user's own
`~/.config/obelize/config.yml`, with `--model` replacing its provider; a
repository's `model:` block is refused with exit `2` before any adapter exists.
The opener departs from `urlopen`'s defaults: no proxy (`ProxyHandler({})`), no
redirect (a 3xx is `endpoint_redirected`), no cookies, no compression, so the
byte cap counts wire bytes. The URL is
`base_url.rstrip("/") + "/chat/completions"`, never `urljoin`, which drops a `/v1`.
`RESPONSE_BYTE_LIMIT` is 1 MiB, far above any replacement the guard accepts.
Because the payload and the key must reach only the host the run prints.

### D8. The endpoint's own words are recorded, redacted and capped

A failure detail carries the status and the endpoint's body, passed through
`obelize.verify.redact` with the run's environment and then cut to 500
characters. Every string in a `ProviderError` that obelize did not write is
redacted, the operating system's included. Because a gateway may quote back the
key it rejected.

### D9. An unset key sends no `Authorization` header

An empty or unset key in the variable `api_key_env` names omits the header; a
remote endpoint then answers 401 through D8. That variable is named only in the
user's configuration, and the key is read at request time from the mapping the
redactor gets and never enters the payload. Because a local Ollama wants no
credential.

### D10. Nothing calls it yet

Superseded by ADR-039: `obelize fix` builds the adapter; `build()` returns
`None` for `provider: none`, the default.

## Consequences

- `temperature` is 0 (an endpoint refusing it is `endpoint_refused`), `response_format` is `json_object` (degrading to D6), and `max_tokens` is not sent, since either spelling makes some endpoint refuse.
- No runtime dependency is added: `urllib`, `json`, `http.client` and `re` are standard library.
- A proxy is not honoured; its address belongs in `base_url`, where the run prints it.
