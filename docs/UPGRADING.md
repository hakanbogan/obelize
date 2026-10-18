# Upgrading a dependency

obelize can move a dependency to a newer release when no one has written a pack for it. It reads
two releases of the library, writes a pack from what changed, plans the move, tries it with your own
tests and, if they agree, keeps it. This page is the whole path. Every command reaches the package
index and says which host first; none of it needs an account.

## 1. See what is behind

```sh
uvx obelize outdated
```

It reads the dependency files of the repository (nothing is installed) and asks the index about
each library. A row says the release you use, the newest, how far apart they are, and what the index
knows about the release you use: that the library marks itself inactive, that the release was
withdrawn, that it has an advisory. The last column says what obelize can migrate it with: a pack
that ships with it, or two releases to compare.

## 2. Plan one move

```sh
uvx obelize upgrade pydantic
```

`upgrade` takes the release your dependency files name and the newest release, and uses the pack
that suits the move. If obelize has none, it reads the two releases (and the newest of each minor
line between them, since a library warns before it removes) and writes one, as
[`pack synth`](CLI.md#obelize-pack-synth) does. Then it plans the migration like `fix` and prints
the diff. Nothing in your repository is written.

What the made pack does is deliberately small:

- A name the library's own deprecation message says to replace, with one name beside it, is renamed.
- A name that moved up out of a submodule is moved up.
- Everything else that changed is flagged with the library's words, never rewritten: what was
  removed or moved, a parameter that was renamed, removed or made required, a default that changed,
  a class whose bases changed, a name that is deprecated.
- The dependency line moves to the new release.

A pack made this way says in its limitations that a change in what a function does is not in it.
Your tests are what show that.

## 3. Try it before it is written

```sh
uvx obelize upgrade pydantic --apply --yes
```

`--apply` does not write at once. In a copy of the repository, outside it, obelize makes two
environments with [uv](https://docs.astral.sh/uv/): one with your dependencies as they are, one with
the new release over them. It runs your tests in the first, writes the move to the copy, and runs
them in the second. The move is written to your repository only if no test that passed before now
fails, errors or is missing; a test that fails once and passes again is reported and not counted.
The evidence (the junit files, the output, what each environment held and the verdict) is in
`.obelize/trials/<id>/`.

It asks first because installing runs the build scripts of the packages it installs and the tests
run your code. `--yes` is the answer for a pipeline, and a terminal is asked. A tree with
uncommitted changes is refused before anything starts.

Exit `3` means tests broke, with their names; exit `6` means the trial could not judge: no tests,
no result obelize can read, no test that passed before, or a move that changed no file. Without
tests, write the migration with `obelize fix --apply` and check it another way.

## 4. Keep it on a branch

```sh
uvx obelize upgrade pydantic --apply --yes --branch
```

The move is committed to a new branch, `obelize/upgrade-<the new release>` or the name you give with
`--branch-name`, and your working tree is left as it is. The commit is built with git's plumbing:
no checkout, no hook, no signature. obelize never pushes; open the pull request yourself, or let a
workflow do it.

## What it will not do

- It writes a move to the whole repository or to none of it. A library that keeps its import name
  across the move is one distribution for both APIs, so one place that obelize cannot migrate holds
  every other file. Most real repositories have such a place, and the trial then ends `6` until a
  person or an agent has moved it. [With a coding agent](WITH_A_CODING_AGENT.md) hands those places
  over and keeps the check.
- It finds a name through the module (`pydantic.BaseModel.parse_obj`), not through an object whose
  class it cannot tell, such as a subclass of `BaseModel` you wrote.
- It cannot see a name a library builds when it is imported. If a module makes names on demand, the
  command counts the names it could not judge instead of calling them removed.
- It installs only from the index uv is configured for, and only in a trial.

## When places are left for a person

Most real moves leave places that a pack made from two releases can only flag, and a library that
keeps its import name has one release for both APIs, so the rules write nothing until every one has
moved. With your own coding agent installed, obelize can put those places to it:

```sh
uvx obelize upgrade pydantic --apply --yes --branch --agent claude_code
```

In the trial's copy, each flagged place is sent to your `claude` program as a text question: the
library's own words about it and the lines around it, nothing else, with every tool of the program
turned off. The answer must pass the same guard as any model proposal. The accepted edits go into
the copy, the rules then write the rest, and your tests judge the whole. Only a move the tests agree
to is committed, and only to a branch; the commit message names the files the agent edited, which
are the lines to read first. `--max-asks` limits how many places are asked about.

An answer may also list the imports it needs, which obelize adds at the top of the file, or say that
a place needs no edit at all, such as a call that passes none of the arguments that changed. That
claim writes nothing and only your tests check it, so the commit message names each such place.

If tests that passed before the move fail after it, the agent is put those too, with the error
and the line of your code the traceback points at, for up to `--max-rounds` rounds. It never edits
a test.

## Runs on real repositories

The first two ran on a public repository, `academic-mcp` at the commit the benchmark pins, and none
changed a clone's working tree.

- `upgrade PyPDF2 --apply --yes --branch`: the bundled pack changed the import in 19 files and the
  dependency line to `pypdf`. The 60 tests that passed before the move all passed after it, and a commit was made.
- `upgrade mcp --from 1.28.1 --to 2.3.0 --apply --yes --branch --agent claude_code`: no pack existed,
  so one was made from the two releases. It flagged the three places that used `FastMCP`, and the
  agent moved them, given the new names that `hints.json` offered. The 99 tests that passed before
  passed after, and the commit held the one file the agent edited. The dependency line, `mcp[cli]>=1.28.1`,
  carries an extra, so it was left, and the summary and the commit message said so.

A third needed two fixes before it passed. `upgrade pydantic --from 1.10.26 --to 2.14.1 --apply
--yes --branch --agent claude_code` on a small scraper first flagged 55 places, most of them every
`Field(...)` call, because the new release deprecates one of its parameters and gave `repr` a
private default. Neither is a change a call shows, so the pack now flags 22, all `@validator`. The
agent moved none of them: the replacement needed `field_validator`, imported at the top of the file,
outside the lines it was sent. A proposal may now list the imports it needs, which obelize adds to
the file's import block, and the import of a name is covered once every place that used it moved.
The agent then moved the ten decorators, the 23 tests that passed before passed after, and the commit
held the one file it edited and the dependency line.

What they show is that the steps join up, on three repositories. They do not show how often a move
passes: for that, the benchmark is the evidence.
