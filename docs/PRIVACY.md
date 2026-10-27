# Privacy

## v0: no network unless you ask, no telemetry

- No network call unless you ask for one: by configuring the model adapter (below), by running a
  command that reads a package index (`pack synth`, `outdated` or `upgrade`, below), or with
  `upgrade --apply`, which installs packages with uv, `upgrade --agent`, which starts your own
  `claude` program, and `--guide`, which fetches a page you name and puts its text to a model you
  set up. There is no update check, no pack download and no crash report. `scan`,
  `verify`, `undo` and `mcp` never reach a network, and `fix` reaches only a model endpoint you
  configured.
- No telemetry code at all: no usage counters, no identifiers, no ping.
- No account.
- Everything Obelize writes goes into the repository you pointed it at, bar three places. The
  cache in `$XDG_CACHE_HOME/obelize` (or `~/.cache/obelize`) holds what the package index
  answered, the releases it sent, the packs `pack synth` and `upgrade` made and, while a trial runs,
  its copy of the repository and its environments (below); `pack new` and `pack synth` write the
  pack's folder where `--dir` says. While
  verification commands run, their JUnit XML, which can hold test output, sits in a temporary
  directory under your system's temp folder and is removed afterwards. When you approve a
  verification command from a repository's `.obelize.yml`, the repository's path, the command and
  its sha256 are kept in your own `~/.config/obelize/approved.json`.

Anything a future version adds that talks to a network will be opt-in and documented here,
with exactly what it sends.

`obelize mcp` opens no socket. It answers a coding agent on standard input and output with what the
commands print and, for `obelize_residue`, the code around each place left, redacted as a model's
context is. Where that text goes next is the agent's, which you chose.

## What a maintained tool sees

A pack with an `external_fixer` change makes `fix` start a program of yours (ruff, for
`numpy/numpy-1-to-2`) and give it one file at a time on its standard input. The program is found on
your `PATH` and run on your machine, in an empty temporary directory, with `PATH`, `HOME`,
`USERPROFILE`, `SYSTEMROOT`, `TMPDIR`, `TEMP`, `TMP`, `LANG` and `LC_ALL` and no other variable, so
a token in your environment is not passed to it. obelize sends nothing anywhere for it: nothing is
installed or downloaded, and what a tool does with its own network is the tool's. The run folder
records the tool's name and release, how it was started, and the sha256 of what it was given and
what it printed for each file, and never the file.

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

## What the package index sees

`pack synth` and `upgrade` read two releases of a library, and `outdated` asks about every library
your manifests declare, so they ask a package index:

- The index is yours: PyPI unless your own `~/.config/obelize/config.yml` (`network.index`) or
  `OBELIZE_INDEX_URL` names another. A repository's `.obelize.yml` cannot name one and is refused.
  Plain `http://` is accepted only for this machine.
- `pack synth` and `upgrade` ask for the project's page (the library's name is in the address) and
  the files of the releases they compare. `outdated` asks, for each distribution your manifests
  declare, for its project page and for the index's JSON metadata of the newest release and of the
  release you use, so the name of every dependency you declare, a private one included, and the
  release in use are in the addresses it requests, so point it only at an index that may know them.
  The files come from the host the page
  names, which for PyPI is `files.pythonhosted.org`. None of them sends a cookie, a body, nothing from your
  repository and nothing about your machine beyond a `User-Agent` of the form `obelize/<version>`
  and what any HTTPS request carries. An `Authorization` value in `OBELIZE_INDEX_AUTHORIZATION` goes
  to the index host and to none other, and a redirect to another host is refused.
- Each host is printed on standard error before it is contacted, once.
- Answers are kept for you alone in `$XDG_CACHE_HOME/obelize` or `~/.cache/obelize`: a project page
  for an hour, a file for good, named by its hash. `--offline` or `network.offline: true` reaches no
  host and uses only what is kept. Delete the directory to forget them.
- A proxy named in your environment is honoured, as for any tool of yours: this is your network, not
  a model's.

## What a guide sends

`pack synth --guide` and `upgrade --guide` read a migration guide, at an https address or in a file
you name, and ask a model to draft claims from its text:

- The page is fetched as the index is (above): one host, printed first, your proxy honoured, a
  redirect to another host refused, a size and a time limit, kept in the cache for an hour and read
  from it under `--offline`. Its query and fragment, which can carry a token, are not kept anywhere.
  A file is read where it is; only its name is ever recorded, never its path.
- The model is the one in your own configuration: the endpoint in `model` (the rules of
  [the model adapter](#what-changes-with-the-model-adapter) hold), else the coding agent in `agent`,
  started as for `--agent` ([what that sends](#what-an-agent-run-sends)). A repository's
  `.obelize.yml` can set neither. With neither set up, `--guide` says so, reads the guide and sends
  nothing.
- What goes to it is a fixed system prompt, the names of the library, its two releases and the
  module compared, the address of the guide (or the name of the file), and the text of the guide in
  parts of about 5,000 tokens, one request each. Nothing of your repository, your manifests or your
  machine goes with it. The text is not redacted, since it is not yours: if you name a guide that is
  private, its text goes to your model.
- `guide.json`, beside the pack that `pack synth` makes (in the cache for `upgrade`), keeps the
  address or file name, the hash of the text, the model's answers as it gave them, the counts, the
  tokens and what became of each claim. It holds nothing from your repository.
- `--guide-replay` takes the answers from that file and sends nothing.

## What `obelize upgrade --apply` installs

Before it writes a move, `upgrade --apply` tries it: it copies the repository, installs its
dependencies twice with uv (once with the release in use, once with the release moved to) and runs
its tests in each. The copy and the environments are made in `$XDG_CACHE_HOME/obelize/trials` (or
`~/.cache/obelize/trials`) and removed when the trial ends; what stays is its evidence, in
`.obelize/trials/<id>/` of the repository: the junit files and output of each test run, what was
installed in each environment, and the verdict. Installing reaches the index uv is configured for
(`UV_INDEX_URL` and the like, not `network.index`) and runs the build scripts of what it installs,
and with `--offline`, `network.offline` or `OBELIZE_OFFLINE` it is kept to uv's own cache; the tests
run the code of the repository. Nothing about the repository or its tests is sent
anywhere by obelize. A trial happens only if you pass `--yes` or answer yes at a terminal.

## What an agent run sends

With `--agent claude_code` (or `agent.backend` in your own configuration), `upgrade --apply --branch`
asks your `claude` program about the places the pack flags, one question each, up to `--max-asks`
(50) a round and up to `--max-rounds` (3) rounds for the tests that broke after the move. A question is the same text the model adapter sends: the pack's id and target package, the
file's path, the line and symbol, the pack's own words about the place, the new names closest to a
removed one where `pack synth` kept them in `hints.json`, and the lines around it (redacted by the
same redactor, numbered), and nothing else of the repository. It goes to wherever
your `claude` login sends a prompt, which is not obelize's to say and not a host obelize prints.
The program is started in an empty directory with every tool off, no session saved, no MCP server,
no skill and none of your settings, and with a short list of variables: `PATH`, `HOME`, the proxy and
certificate variables of your network, and any beginning `ANTHROPIC_`, `CLAUDE_`, `AWS_`, `GOOGLE_`
or `VERTEX_`, which are what a login to Claude through Anthropic, Bedrock or Vertex uses. A token
for GitHub or a package index is not among them. Its answers are checked
by the guard and written only to the trial's copy. For a test that broke, the question holds the
test's name and the last line of its error (redacted and cut to 300 characters) in place of the
pack's words, and a test that broke is never itself the place to edit. A place the pack flags in a
test file is asked about like any other, and the commit message names every file the agent edited.
`--agent` needs `--branch`, so nothing a model
helped write reaches your working tree before you have read it on a branch. No other program is
started this way: `codex exec` documents no setting that leaves a model without tools, so it is not
offered ([ADR-076](adr/ADR-076-no-backend-for-codex-yet.md)).

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
