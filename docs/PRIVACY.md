# Privacy

## v0: no network, no telemetry

- No network call unless you configure the model adapter (below): no update check, no pack
  download, no crash report.
- No telemetry code at all: no usage counters, no identifiers, no ping.
- No account.
- Everything Obelize writes goes into the repository you pointed it at.

Anything a future version adds that talks to a network will be opt-in and documented here,
with exactly what it sends.

## What is written to `.obelize/`

Every run writes `.obelize/runs/<run-id>/` in the migrated repository, on your disk; nothing
uploads it. The layout and every field are in [RUN_FOLDER.md](RUN_FOLDER.md#layout). What the
files may contain:

| File | Contains |
|---|---|
| `run.json` | No file content and no command output: the verification's output is a path into `verify/` |
| `findings.json` | Paths, positions, symbols and verdicts, and no source: `Finding.evidence` is never written |
| `plan.json` | Paths, line numbers and hashes, and no source |
| `patch.diff`, `snapshots/` | Your source, **not redacted**: changed lines with three lines of context, and each written file whole, before and after |
| `verify/<phase>/*.log` | What your commands printed, redacted and capped |
| `REPORT.md` | A readable summary of the other files |
| `model/` | Only with a model configured (below) |

What reduces the exposure:

- Command output and model context are redacted before they are written or sent, by one
  redactor whose rules and limits are in [THREAT_MODEL.md](THREAT_MODEL.md#secret-redaction).
  It misses secret formats it has no pattern for.
- Environment variables are never recorded.
- Command output is capped at 1 MiB per command (the first 256 KiB plus the last 768 KiB).
- Git ignores `.obelize/`: obelize writes a `.gitignore` inside it and never edits yours.

`patch.diff` and `snapshots/` hold your code exactly as it is, secrets included, because a
snapshot you cannot restore from is useless. **Review a run folder before you share it.**

## What changes with the model adapter

One optional model adapter can be asked about cases the rules refuse. It is off by default
(`model.provider: none`), and then nothing above changes.

When you configure it:

- One endpoint, and it is yours: the `base_url` in your own `~/.config/obelize/config.yml`,
  such as a local Ollama server, your own OpenAI-compatible gateway, or a provider you have an
  account with. Obelize has no endpoint of its own, and a `model:` block in a repository's
  `.obelize.yml` is refused with exit `2` before anything is sent, so the code being migrated
  cannot choose where it, and your key, go.
- Only the relevant slice of code is sent: the smallest function or class holding the whole
  binding group of the ambiguous call site, else that group with 20 lines either side, and
  nothing when neither fits in 80 lines. With it go the file's path, the reason the rules
  refused and the pack's limitations. Never the repository, the whole file or your git history.
- The slice comes only from the Python file the finding is in, and is redacted before the
  payload is built.
- One host, and nothing helping you reach it: a proxy named in your environment is not
  honoured and a redirect is refused, since either would carry the payload and the API key to
  a host you did not configure.
- The request identifies itself as `obelize/<version>`, and says nothing else about your
  machine.
- The host is printed before the run starts, on stderr.
- `--show-context` prints every string the payload carries, and sends nothing; it works with
  no provider configured.
- The API key never appears anywhere: it is read from the environment variable named by
  `model.api_key_env` (default `OBELIZE_MODEL_API_KEY`) and never written to configuration,
  logs, evidence or prompts.
- Raw prompts are not stored: `model/proposals-<n>.json` records the context range, a prompt
  sha256, the provider, the model, token counts, the proposal and whether it passed validation. The
  request body is written only if you set `model.log_prompts: true`, because a prompt is your
  source code.
- A proposal is written only under `--apply` and `--accept-model`, and is still listed as a
  review item.

Once a payload leaves your machine, the endpoint operator's terms govern it, not Obelize. If
that matters for your code, point `base_url` at a local model.
