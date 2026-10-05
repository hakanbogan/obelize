# gemini-legacy-app

A small command-line tool that summarises a text file and can then hold a short
follow-up conversation about the summary.

This app is pinned to a deprecated SDK on purpose. It is written against
`google-generativeai==0.8.6`, which Google has retired in favour of
`google-genai`: it is the migration subject of Obelize's end-to-end test (`tests/e2e/`).
Do not "fix" the dependency by hand.

## What it does

```
$ python -m summarizer.cli sample_docs/release_notes.txt
The scheduler no longer holds the job table lock while writing the audit row,
which fixes the nightly stalls. CSV export quoting and the health endpoint were
also corrected. PostgreSQL 13 users should expect a slow first recovery pass.

$ python -m summarizer.cli sample_docs/release_notes.txt --ask "Should we upgrade?"
...
```

Running it for real needs a Gemini API key in `GEMINI_API_KEY` (a `.env` file at the project
root works; the app loads it with `python-dotenv`). The tests need neither a key nor a network.

## Layout

```
summarizer/
  config.py        the one place that calls genai.configure()
  summarize.py     GenerativeModel + generation_config + safety_settings
  conversation.py  start_chat() / send_message(): the follow-up chat
  cli.py           argparse entry point
scripts/
  oneoff_backfill.py   a dead one-off script, excluded in .obelize.yml
tests/               pytest, with google.generativeai.GenerativeModel patched
sample_docs/         a text file to summarise
conftest.py          puts the project root on sys.path, sets a dummy API key
```

`config.py` configures the SDK at import time and the other modules rely on it, so the module
holding `configure` is not the module holding the model. That is why `obelize fix` writes
nothing here: `summarize.py` and `conversation.py` stay on the legacy SDK, and removing the
`configure` they run on would break them while their mocked tests stayed green
(`configure_consumed_elsewhere`).

## Running the tests

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

On Windows the environment's programs are in `.venv\Scripts` instead of `.venv/bin`.

Expected output:

```
12 passed, 1 warning in 0.40s
```

The warning is the legacy SDK's deprecation `FutureWarning` on import; it's left unsilenced.
Every test patches the SDK's `GenerativeModel`, the whole boundary the package touches, so a
passing suite after a migration only shows the app's own logic still works. It says nothing
about whether the new SDK accepts the calls.

## `.obelize.yml`

It sets `verify.commands: ["pytest -q"]` and excludes `scripts/**`. Those commands are
repository configuration: run interactively, obelize asks before running each; in CI or under
`--non-interactive` it refuses them unless they are on your allowlist or you pass
`--trust-repo-config` ([trust rules](../../docs/CLI.md#trust-rules-for-verification-commands)).

## Migration cases covered

Each row is an SDK usage the migration has to handle, of the kind a real application would
have:

| Where | Usage |
|---|---|
| `summarizer/config.py:22` | `genai.configure(api_key=...)` at module level |
| `summarizer/summarize.py:27` | `GenerativeModel(...)` with `generation_config`, `safety_settings` and `system_instruction` |
| `summarizer/summarize.py:39` | `generate_content(...)` on a model the function does not hold in a variable |
| `summarizer/summarize.py:40` | `response.text` |
| `summarizer/conversation.py:13` | a model held on `self` |
| `summarizer/conversation.py:14` | `start_chat(history=[...])` with a literal history |
| `summarizer/conversation.py:23` | `send_message(...)`, positional |
| `summarizer/conversation.py:28` | `chat.history`, which the new SDK does not have |
| `tests/*.py` | `mock.patch("google.generativeai.GenerativeModel")`; patch targets move too |
| `requirements.txt:3` | the pinned dependency the manifest rewrite must replace |
| `scripts/oneoff_backfill.py` | legacy usage in a file that is excluded from the migration |

`ground_truth.yaml` records, per line, what a correct scan says about each of them.
