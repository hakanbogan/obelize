# With a coding agent

An agent migrates more than obelize does, and obelize gives the migration a check. A study of 321
real Python library migrations found that language models got 89 to 94 percent of the individual
code changes right, but only 36 to 64 percent of whole migrations passed the tests that passed in
the developers' own migration ([arXiv 2504.13272](https://arxiv.org/abs/2504.13272)). A change that
looks right is not the same as a migration that still works.

Let obelize do the part it can prove, give the agent the rest, and keep the check:

1. `uvx obelize fix --apply` writes what it can prove and lists the rest in `REPORT.md`.
2. Hand the agent the `Withheld` entries of `REPORT.md` and the pack's guide for them.
3. Run `uvx obelize scan` or your CI check ([CLI.md](CLI.md#a-ci-check)) until nothing is left.
4. Run your tests, and read `git diff`.

[skills/obelize/SKILL.md](../skills/obelize/SKILL.md) is the same workflow as a skill file for an
agent.

## As tools

`obelize mcp` offers the same workflow to an agent as tools, so it calls them instead of running
commands. Add it to the agent's configuration, for example `.mcp.json`:

```json
{ "mcpServers": { "obelize": { "command": "uvx", "args": ["obelize", "mcp"] } } }
```

The agent scans, applies what obelize can prove, asks `obelize_residue` for the places left (each
with its reason, what to change and the code around it), edits them, and calls `obelize_verify` with
`current` set so your tests judge the result. No tool takes a command, a path or a consent: the
verification commands are the ones in your own configuration, and the repository's `.obelize.yml`
runs only if you start the server with `--trust-repo-config`. `--read-only` leaves out the two tools
that write files. [CLI.md](CLI.md#obelize-mcp) lists the tools. The agent edits files and obelize reports what is left, so the two never write the same
place at once: obelize writes only the files it can migrate whole.
