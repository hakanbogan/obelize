# Privacy

## v0: no network unless you ask, no telemetry

- No network call unless you configure the model adapter (below) or run `obelize pack synth`
  (below): no update check, no pack download, no crash report. `scan`, `fix`, `verify`, `undo` and
  `mcp` never reach a network.
- No telemetry code at all: no usage counters, no identifiers, no ping.
- No account.
- Everything Obelize writes goes into the repository you pointed it at, bar two places. While
  verification commands run, their JUnit XML, which can hold test output, sits in a temporary
  directory under your system's temp folder and is removed afterwards. When you approve a
  verification command from a repository's `.obelize.yml`, the repository's path, the command and
  its sha256 are kept in your own `~/.config/obelize/approved.json`.

Anything a future version adds that talks to a network will be opt-in and documented here,
with exactly what it sends.

`obelize mcp` opens no socket. It answers a coding agent on standard input and output with what the
commands print and, for `obelize_residue`, the code around each place left, redacted as a model's
context is. Where that text goes next is the agent's, which you chose.

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

## What `obelize pack synth` reaches

The command exists to read two releases of a library, so it asks a package index for them:

- The index is yours: PyPI unless your own `~/.config/obelize/config.yml` (`network.index`) or
  `OBELIZE_INDEX_URL` names another. A repository's `.obelize.yml` cannot name one and is refused.
  Plain `http://` is accepted only for this machine.
- It asks for the project's page (the library's name is in the address), the files of the releases
  it compares and, where the index has one, nothing else. The files come from the host the page
  names, which for PyPI is `files.pythonhosted.org`. It sends no cookie, no body, nothing from your
  repository and nothing about your machine beyond a `User-Agent` of the form `obelize/<version>`
  and what any HTTPS request carries. An `Authorization` value in `OBELIZE_INDEX_AUTHORIZATION` goes
  to the index host and to none other, and a redirect to another host is refused.
- Each host is printed on standard error before it is contacted, once.
- Answers are kept for you alone in `$XDG_CACHE_HOME/obelize` or `~/.cache/obelize`: a project page
  for an hour, a file for good, named by its hash. `--offline` or `network.offline: true` reaches no
  host and uses only what is kept. Delete the directory to forget them.
- A proxy named in your environment is honoured, as for any tool of yours: this is your network, not
  a model's.

## What `obelize upgrade --apply` installs

Before it writes a move, `upgrade --apply` tries it: it copies the repository, installs its
dependencies twice with uv (once with the release in use, once with the release moved to) and runs
its tests in each. The copy and the environments are made in `$XDG_CACHE_HOME/obelize/trials` (or
`~/.cache/obelize/trials`) and removed when the trial ends; what stays is its evidence, in
`.obelize/trials/<id>/` of the repository: the junit files and output of each test run, what was
installed in each environment, and the verdict. Installing reaches the index uv is configured for
(`UV_INDEX_URL` and the like, not `network.index`) and runs the build scripts of what it installs;
the tests run the code of the repository. Nothing about the repository or its tests is sent
anywhere by obelize. A trial happens only if you pass `--yes` or answer yes at a terminal.

## What changes with the model adapter

One optional model adapter can be asked about cases the rules refuse. It is off by default
(`model.provider: none`), and then nothing above changes.

When you configure it:

- One endpoint, and it is yours: the `base_url` in your own `~/.config/obelize/config.yml`,
  such as a local Ollama server, your own OpenAI-compatible gateway, or a provider you have an
  account with. Obelize has no endpoint of its own, and a `model:` block in a repository's
  `.obelize.yml` is refused with exit `2` before anything is sent, so the code being migrated
  cannot choose where it, and your key, go. Plain `http://` is accepted only for `localhost`,
  `127.0.0.0/8` and `::1`; any other host needs `https://`, or `model.allow_insecure_http: true`
  in that file, since the key and your source would cross the network in the clear.
- Only the relevant slice of code is sent: the smallest function or class holding the whole
  binding group of the ambiguous call site, else that group with 20 lines either side, and
  nothing when neither fits in 80 lines. With it go the pack's id and target package, the file's
  path, the line and symbol of the call, the reason the rules refused and the pack's limitations.
  Never the rest of the repository or your git history, but a file short enough for the slice to
  reach both of its ends is sent whole.
- The slice comes only from the Python file the finding is in, and is redacted before the
  payload is built. Each of its lines is sent behind its line number in the file, so the model
  need not count them.
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
  proposal quotes the lines it replaces, so those lines of your source, as redacted when they were
  sent, are in it. The request body is written only if you set `model.log_prompts: true`, because a prompt is your
  source code.
- A proposal is written only under `--apply` and `--accept-model`, and is still listed as a
  review item.

Once a payload leaves your machine, the endpoint operator's terms govern it, not Obelize. If
that matters for your code, point `base_url` at a local model.
