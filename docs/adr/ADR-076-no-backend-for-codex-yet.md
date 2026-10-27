# ADR-076: No backend for codex yet

## Status

Accepted.

## Decision

`--agent` and `agent.backend` take `claude_code` and nothing else. ADR-067 D1 offers a coding agent
only as a text-only model: a program that cannot be held to a text answer would be a way for a
repository's text to run a tool, so a backend whose restriction cannot be guaranteed is not
supported. OpenAI's `codex exec` does not meet that on what its own documentation says today, and no
backend is built for it.

### D1. What was checked

On 2026-10-27, the Codex CLI reference (the flags of `codex exec` and the ones every command takes),
"Non-interactive mode", the configuration reference, "Config basics", "Permissions" and "Agent
approvals and security", all under `developers.openai.com/codex`, which redirects to
`learn.chatgpt.com/docs`. The newest release of the CLI was then 0.164.0 (`rust-v0.164.0` on
openai/codex, 2026-10-23). `codex` was not installed where this was checked: no `--help` was read,
nothing was run and nothing of any repository was sent. The pages state no version for the flags; the
one setting they date is managed permission-profile allowlists, "Codex 0.138.0 or later".

### D2. What the documentation gives

- `codex exec` runs in a read-only sandbox by default, and that sandbox takes nothing away from a
  model that is to answer in text: the page for `--sandbox read-only --ask-for-approval never` says
  "Codex can read files and run commands within the read-only sandbox".
- `--disable <feature>` is `-c features.<name>=false`. `features.shell_tool` is documented
  ("Enable command execution tools"), so the earlier finding that no feature is documented to
  control the shell no longer holds. What the page never says is what `shell_tool = false` removes.
  Of the other command feature, `features.unified_exec`, it says that a person's opt-out is ignored,
  that managed requirements can switch off resumable processes and `write_stdin` and that one-shot
  `exec_command` stays available.
- A permission profile (`default_permissions` with `[permissions.<name>.filesystem]`, where `"deny"`
  denies reads) is documented to "govern sandboxed commands that run on your machine"; connectors,
  MCP servers, browser and computer use "use their own controls". A profile limits a command and
  removes no tool.
- The other tools each have a switch or none: `web_search = "disabled"`, `tools.view_image`,
  `features.apps`, `features.multi_agent`, `mcp_servers` and plugins in the configuration
  (`--ignore-user-config` skips the user's file), and for file changes, which the JSON events of
  `codex exec` list as an item type, no switch. The table of features says it "lists common
  user-facing flags, not every internal or under-development feature".

### D3. What the rule needs and what is missing

ADR-067 D1 starts the agent with flags that each take a capability away and refuses a program whose
`--help` does not name them. For `claude` one of them, `--tools ""`, closes the set: whatever tools
a release adds, none is on. Codex documents no such thing. Closing its set would mean switching off
by name every tool the pages list today, in a list they say is not complete, with one command
feature a person cannot switch off, no switch for file changes, and no statement that the result is a
model with no tools. A check at start could read `codex features list` to see which names the
release knows; it could not show that nothing is left. A model that is to answer in text but can run
a command in a read-only sandbox reads the person's files, which is what the empty directory and
the missing tools are there to prevent.

### D4. What would change the answer

Documentation, with the CLI version it first appears in, of a setting that gives the model no tools
(the counterpart of `--tools ""`), or of a set of flags that it says removes command execution
(`exec_command` and `write_stdin` named), file changes and every other tool, and that `codex exec
--help` or `codex features list` shows at start. A backend would then be an entry in `BACKENDS`,
`PROGRAM` and `RESTRICTIONS` of `providers/agent_cli.py`, checked at start as `claude`'s are, with
its own tests and its own ADR.

## Consequences

Nothing in the code changes. `--agent codex` is refused with "--agent takes one of claude_code, not
'codex'." (exit `2`), and `agent.backend: codex` in the configuration file with "agent.backend:
Input should be 'none' or 'claude_code'", since the setting is a closed list. A person who
uses Codex can still use it beside obelize, outside it, with obelize as the check
([With a coding agent](../WITH_A_CODING_AGENT.md)), or set a `model` endpoint for `fix` and
`--guide` (ADR-038). `docs/KNOWN_ISSUES.md` lists the gap, and `docs/CLI.md`, `docs/PRIVACY.md`
and `docs/UPGRADING.md` say that `claude_code` is the one backend.
