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

A `Consultation` may carry `note`, what is known about the row: for a flagged place, the
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

### D5. The tests the move broke are put to the agent, as places in the code that was changed

When the tests that passed before fail after the move, each failing test's Python traceback
(`--tb=native`, which the trial runs) is read for its innermost frame in a file the move wrote,
a model edit included, that is not a test (a name `test_*`, `*_test.py`, `conftest.py`, or a
directory `test` or `tests`). That frame is a place: the file, the line, and the function it is in
for the symbol the guard asks a proposal to name, with the test's name and the last line of its
error, redacted and cut to 300 characters, as the note. The places are asked about, checked and
written as D2 and D3 say, the tests run again, and the rounds stop when the agent edits nothing,
when no fewer tests break, or after `--max-rounds` (3). A test is the evidence, so a test file is
never a place, and a failure that raises in a test file or in code the move did not touch (a wrong
value, an assertion) has no place and is left to the person. A trial that still fails writes
nothing.

### D6. The pin follows what the agent moved, and what cannot be written is said

The dependency line moves when the rules migrated a file. A pack of flags alone (the synthesized
pack of a library that renamed little) migrates none, so files the agent edited count as migrated
for the pin (`fix` takes them as files migrated elsewhere), and a trial whose every flagged place is
moved runs its tests even when the rules wrote nothing. A place left unresolved ends the trial with
the reason `unresolved`, since the repository would be half moved. A dependency line the rules cannot
write (a requirement with extras, which the new release may not have) is named, as `path:line`, in
the summary and in the commit message, for the person to change by hand.

### D7. The agent is told the names the new release added

For a removed name, `pack synth` keeps beside the pack the new names closest to it (`hints.json`,
`PACKS.md`), and the note sent with the place ends with them. Without them an agent can only answer
from what it knows of the new release, which for a release newer than the agent is nothing.

### D8. A proposal may bring its imports, and a place may need no edit

A rename often needs a name imported at the top of the file, outside the lines a place is sent.
A proposal may therefore list up to four imports, each a plain `import` or `from ... import` of a
module the pack targets. The guard refuses any other, adds the rest to the file's import block (to
its own `from m import ...` line when it has one) and licenses the names they bind. A file's places
are asked from the bottom, each where the earlier answers left it, and the import of a name is
covered once every place that used it was settled.

A place the pack flags may be one the change does not touch, such as a call that passes none of the
arguments that changed. The agent may say so in a sentence (`"unchanged"`). The place is then
settled, listed in the trial's evidence and named in the commit message, and nothing is written for
it: only the tests check the claim. A file the agent settled holds no dependency line back.

## Consequences

`docs/CLI.md`, `docs/PRIVACY.md` and `docs/THREAT_MODEL.md` (TM-13) describe the agent, what it is
sent and what restricts it. The `model:` block and `fix` are unchanged: the agent is for `upgrade`.
The repair is limited to code the move wrote and to errors a traceback places there; widening it to
other code, or to the text of a `mock.patch` in a test, is a decision of its own.
