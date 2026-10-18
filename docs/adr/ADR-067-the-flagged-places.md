# ADR-067: The flagged places

## Status

Accepted.

## Decision

A pack made from two releases flags most of what changed, and a library that keeps its import name
has one distribution for both APIs, so the rules write nothing while one flagged place is left. The
places can be put to a model, in a copy, and only a move the tests agree to is kept.

### D1. The agent is the person's own program, asked for text

`--agent claude_code` (or `agent.backend` in the user's configuration, which no repository may set)
asks the `claude` program on `PATH` as a text-only model. It is started in a new empty directory
with `--print --output-format json`, `--tools ""`, no session saved, `--strict-mcp-config` with no
config, `--disable-slash-commands`, `--setting-sources ""` (so none of the person's hooks or
settings load), `--permission-mode dontAsk` and obelize's own system prompt, with the question on
standard input and a fixed list of environment variables: the ones it needs for its login, its
network and its terminal, and none that carries a token for GitHub or an index. A program whose
`--help` does not name every one of those restrictions is not used, and a batch file is refused on
Windows because its quoting cannot be trusted. Its answer is read as the HTTP adapter's is. Failures
use the adapter's words (`endpoint_unreachable` for a program that did not start or answer in time,
`endpoint_refused` for one that exited with an error). No other backend is offered: a program that
cannot be held to a text answer would be a way for a repository's text to run a tool.

### D2. A flagged place is a question with the pack's words

A `Consultation` may carry `note`, what the pack says about the row: for a flagged place, the
flagged change's message and suggestion, which for a pack made from two releases are the library's
own words. The question is otherwise the adapter's: the file, the line, the symbol, the modules a
proposal may import, and the redacted lines around the place. Each place is its own question, the
bottom of a file first so the lines above keep their numbers, and a place inside the lines an
accepted answer replaced is not asked. `--max-asks` (50) limits the questions of a trial.

### D3. The guard decides what may be written, and the copy keeps it from the repository

Each proposal goes through `providers.guard.check` against the file as it is in the copy: inside
the lines sent, covering the line asked about, parsing, compiling, importing and naming nothing
beyond the question. An accepted proposal is written to the copy and nowhere else. When the answers
are in, the rules run in the copy again; now that nothing is flagged, they write the rest. The tests
then judge the copy as for any trial (ADR-065), and a trial in which the places were not all
resolved ends `inconclusive` with the reason `unresolved`.

### D4. What a model helped write lands on a branch

`--agent` requires `--apply` and `--branch`. The working tree is not written by a move a model
touched, so a person reads the commit first; the commit message names the files the agent edited,
and `trial.json` records every place: the outcome, the guard's refusal or the proposal's lines.
This is the rule that a model's edit is never written unreviewed (ADR-003, ADR-039) held in the one
place a trial makes a write.

## Consequences

`docs/CLI.md`, `docs/PRIVACY.md` and `docs/THREAT_MODEL.md` (TM-13) describe the agent, what it is
sent and what restricts it. The `model:` block and `fix` are unchanged: the agent is for `upgrade`.
Repairing what the move broke, a loop on failing tests, is not part of this decision.
