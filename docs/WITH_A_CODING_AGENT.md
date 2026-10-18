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
agent. The agent edits files and obelize reports what is left, so the two never write the same
place at once: obelize writes only the files it can migrate whole.
