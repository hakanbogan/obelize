# ADR-039: Model command surface

## Status

Accepted.

## Decision

### D1 -- Three flags, and the two that cannot be combined say so

`obelize fix` takes `--model <provider>`, `--accept-model` and `--show-context`; the last two have
no `.obelize.yml` key, because a repository must not decide them for the user. `--accept-model`
without `--apply`, and `--show-context` with `--apply`, exit `2` before the scan: the first has
nothing to act on, the second asks to write and not write. A run that uses more than one pack
refuses `--model` and `--accept-model` the same way (ADR-052 D6). `--allow-dirty` on a dry run is
no error: it has a file equivalent.

### D2 -- `--show-context` prints and stops

It prints the consultations and exits `0`, with no request and no run folder, and works under
`provider: none`, since whoever decides whether to configure a provider is who the audit is for.
Every string of the request body is printed once, unescaped, below a line naming the endpoint and
model or saying none is configured; the JSON framing is not, because an escaped one-line payload
cannot be read.

### D3 -- The model pass sits between the plan and the tree gate

```
scan -> rules -> [ tree gate ] -> model -> baseline -> write -> compile -> verify
```

After the rules, because it asks about rows they refused; after the tree gate, because a refused
apply must not have sent source code first. `fsutil.apply` asks both gates again. A dry run consults
too, so `--accept-model` has something to decide on.

### D4 -- A model edit and a rule edit never touch the same file

A consultation needs a `needs_review` row, and ADR-010 F-1 then bails every eligible row in that
file, so the rules leave it unchanged. `providers/proposals.py` raises otherwise, and `FileEdit`
refuses a row naming both a rule and a proposal.

### D5 -- One accepted proposal per file, and eight words for what became of one

A file takes at most one model edit per run, the first in document order, because a guarded
proposal is a whole file and merging two would write bytes no guard checked (ADR-037 D8).
`ProposalOutcome`, first match in this order (answer before run, permission before placement):

| Word | What it says |
|---|---|
| `unanswered` | The adapter raised; `ProviderFailure` says why. |
| `nothing_proposed` | The endpoint answered `{"proposal": null}`. A normal answer. |
| `guard_refused` | A proposal, refused; `GuardRefusal` says why. |
| `not_applied` | Accepted, and this run wrote nothing at all: no `--apply`. |
| `not_accepted` | Accepted, and `--accept-model` was not given. |
| `file_already_proposed` | Accepted, and an earlier proposal holds this file. |
| `write_refused` | Accepted and due to be written, and the apply was refused. |
| `written` | On the disk. |

### D6 -- A model-proposed edit does not clear a review item

The row stays in `withheld[]`, `counts` do not move and the run exits `4`, because the guard proves
an edit safe to apply, not correct. The `Edit` becomes `model_proposed` and keeps its bail.

### D7 -- `model/` holds one index and one file per **consultation**

`model/model.json` holds the run's `model` summary and each row not asked about, with its
`ConsultSkip` word. `model/proposals-<n>.json` is written for every consultation, answered or not,
because a failed endpoint is what a reader opens the folder to see.

### D8 -- The prompt hash is of the bytes that went on the wire

`prompt_sha256` hashes the exact request body that `ModelProvider.request()` builds and the
adapter sends (sorted keys, ADR-038 D5), so a re-ask records the same hash. The prompt itself is
kept only under `model.log_prompts`; the key travels in a header and is in neither.

### D9 -- `FileEdit` gains `proposals[]`, because a hunk must stay traceable

`proposals[]` names the `model/proposals-<n>.json` behind a file's hunks, and a `FileEdit` with
neither a rule nor a proposal is refused, so every applied hunk traces to something a reviewer can
open.

### D10 -- The host is printed before the run, on stderr, and only when there is one

One stderr line before the scan names the provider, the host of `base_url` (a URL can carry a
credential) and the model, so `--json` stdout stays one document. None under `provider: none`.

### D11 -- `RunTimings` gains `model_ms`

Present exactly when a model was consulted and `null` otherwise, because the model pass is a run's
slowest phase; `RunRecord` refuses the disagreement.

## Consequences

- A fake key in a comment is graded absent from the payload and from every run folder file.
- `model.schema.json` and `proposal.schema.json` describe `model/`; `docs/RUN_FOLDER.md` publishes
  the four vocabularies.
- A run with a model is not reproducible: `model/` and `plan.json` vary, `findings.json` does not.
- Nothing changes under `provider: none`.
