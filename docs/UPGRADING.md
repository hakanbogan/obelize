# Upgrading a dependency

obelize can plan the move of a dependency to a newer release when no one has written a pack for it,
and try it with your own tests. It reads two releases of the library, writes a pack from what
changed, plans the move, tries it with your own tests and, if they agree, keeps it. This page is the
whole path, and [how far it gets](#how-far-it-gets-without-a-pack) on public repositories is measured
only as far as the plan: over 80 of them it wrote no file. A command that reads the package index
says which host it will contact first, and none of them needs an account; `--agent` uses the login
of your own `claude`.

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
line between them, at most six, since a library warns before it removes) and writes one, as
[`pack synth`](CLI.md#obelize-pack-synth) does. Then it plans the migration like `fix` and prints
the diff. No file of your code is written; its run folder goes under `.obelize/`. A dependency that is
already on the newest release (no `--to` names another, and no pack moves it to another
distribution) has nothing to move: `upgrade` says so and exits `0`.

`--from` names the release your code is written for. Where no dependency file declares the library,
or every declaration admits that release (`pydantic`, `pydantic<2`, `pydantic>=1.8` and
`pydantic = "^1.9.1"` all admit `--from 1.10.26`), the plan takes it as that release, says so in its
summary and in `REPORT.md`, and records it as `stated` in `run.json`. A declaration that admits the
release and others is taken against your word: the plan goes with yours. One that rules it out
(`pydantic==2.5.0`, `pydantic>=2`, `pydantic<1.5`), or that obelize cannot read, stops the plan and
says so, and so does a release the pack does not cover. Every declaration counts, in every file
obelize reads, a requirements file that is a lock too; a lock file of another kind (`uv.lock`,
`poetry.lock`) is not read. A dry run takes your word for the release; `--apply` installs it in the
trial, so your tests are what check it.

What the made pack does is deliberately small:

- A module-level name that the library's own deprecation message says to replace, with one name
  beside it, is renamed.
- A method of a class that the library's message says to replace with another method of the class
  (`use model_dump instead`, and no more than that) is renamed where your code reads it off an
  instance of the class or of a class of yours that derives from it. If the new method takes fewer
  keywords than the old one, a call that passes one it lacks is left for you; if a call could not
  move by a rename (a positional parameter went, a required one is new), the method is flagged.
- A name that moved up out of a submodule is moved up.
- Everything else that changed is flagged and never rewritten, with the library's own message where
  it gave one: what was
  removed or moved, a parameter that was renamed, removed or made required, a default that changed,
  a class whose bases changed, a name that is deprecated.
- A function or a class whose changes are to its parameters is flagged at the calls those changes
  can break, and says which: a call that passes a keyword that went (one that a new `**kwargs`
  takes without a word too), has an argument at a position that went, leaves out a parameter that is
  now required or has a new default, or passes a `*` or `**` argument that could give one of those.
  A call that does none of these is not listed, and neither is the name where it is imported,
  annotated or handed to another call (`Column(Integer)`, `map(pd.to_datetime, rows)`), unless that
  call passes a keyword that went (`functools.partial(read_csv, delim_whitespace=True)`). Each place
  says what in the call matched, such as `keyword infer_datetime_format`, so a call that passes none
  of what changed is not one more place to read. A default that became a name that means "not
  given" (`lib.no_default`) is no change.
- A class whose bases changed is flagged where your code derives from it, and not where it is
  called, if it is built with what it was. A deprecation whose message names a parameter that
  changed (`The 'fastpath' keyword in pd.Series is deprecated`) is about the calls that pass that
  parameter.
- A name that also left or moved, a deprecation that names no changed parameter, a function that
  changed kind, a class whose constructor comes from a base that changed, and every method, is still
  flagged wherever it is used.
- The dependency line moves to the new release. A requirement that names extras
  (`mcp[cli]>=1.28.1`) keeps them if the newer release lists every one as `Provides-Extra` in its
  wheel, which the pack records: only the version after the extras changes. With an extra the
  release does not list, with no wheel to read it from, in a constraints file or a pip-tools input,
  or in a form where the edit would be more than the version (a hash, a continued line, a Poetry
  table with other keys), the line is left as it was and the summary and the commit name it, for
  you to change ([why](adr/ADR-077-extras-on-a-pin.md)).

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
uncommitted changes to tracked files is refused before anything starts.

Exit `3` means tests broke, with their names; exit `6` means the trial could not judge: no tests,
no result obelize can read, no test that passed before, tests that did not finish within
`--timeout`, a move that changed no file, a place left for a person, or environments that could
not be made. Without
tests, write the migration with `obelize fix --apply` and check it another way.

## 4. Keep it on a branch

```sh
uvx obelize upgrade pydantic --apply --yes --branch
```

The move is committed to a new branch, `obelize/upgrade-<the new release>` or the name you give with
`--branch-name`, and your working tree is left as it is. The commit is built with git's plumbing:
no checkout, no hook, no signature. obelize never pushes; open the pull request yourself, or let a
workflow do it ([Upgrading in CI](UPGRADING_IN_CI.md): the action runs the trial in one job and a
second job opens the pull request).

## What a guide adds

Two releases show what a library renamed or removed, not what its authors say in prose: "`copy()` is
now `model_copy()`". A migration guide says it. With `--guide`, a model you have set up reads the
guide and drafts claims, and code keeps only those it can check against the guide and the two
releases. You set the model up once, in your own `~/.config/obelize/config.yml`, as the endpoint in
`model:` or, as here, your coding agent:

```yaml
agent:
  backend: claude_code
```

```sh
uvx obelize pack synth pydantic --from 1.10.26 --to 2.12.5 \
  --guide https://pydantic.dev/docs/validation/latest/get-started/migration/
```

```text
--guide https://pydantic.dev/docs/validation/latest/get-started/migration/: its text (43949 characters) will go to /opt/homebrew/bin/claude, which sends it where your own login does, in 3 part(s), one at a time; nothing of your code goes with it.
...
Guide: 47 claim(s) drafted, 31 kept (1 as a rewrite, 30 to report); rejected: quote_weak 5, legacy_unknown 1, in_the_diff 10. Tokens: 21171 in, 7980 out. Record: .../guide.json
```

10 of the 47 were changes the API diff had already made or reports, and were dropped; 5 had a quote
too short to carry a claim ("min_items (use min_length instead)"), and one named a method that
pydantic 1 does not have (`BaseSettings.parse_env_var`). Of the 31 kept, 30 are reports that quote
the guide, among them `pydantic.validate_arguments` (renamed to
`validate_call`), `pydantic.utils.GetterDict` (moved to `pydantic.v1.utils`) and
`pydantic.generics.GenericModel` (removed), names the diff did not report, since pydantic 2 makes
many of them when they are imported. One is a rewrite: the diff shows `BaseModel.copy` deprecated and
`model_copy` there to take its place, so `user.copy(update=...)` is rewritten where the file shows
what `user` is, and a call that passes `include` or `exclude`, which `model_copy` lacks, is left for
you. A claim becomes a rewrite only on two pieces of evidence together: the guide's passage says in
a known shape that the new name takes the place of the old (here the line of a table,
`copy() | model_copy()`) with no word in its sentence that limits it or takes it back, such as
"not", "but" or "only", and the diff shows the old name going and the new one there, written the
same way (not a coroutine where the old was not). The others stay reports that say "The migration
guide says: ..." with the passage, however sure the model was. Fed back through these checks, the
answers of that run gave the same result, 47 drafted, 31 kept, one of them a rewrite, and no kept
claim lost its place.

`guide.json` beside the pack keeps the answers and what became of each claim, and `--guide-replay`
makes the same pack again from it without asking a model, with the day the guide was read.
`upgrade --guide` does the same inside a move, once, and only when obelize makes the pack: a pack
that ships is used as it is, without the guide being read, and one made before from the same guide is
used again. The guide is fetched like the index is, so a page that moved to another host is refused
and the message names the host: `docs.pydantic.dev/latest/migration/` is now at `pydantic.dev`, and
the address above is where it went. If no model is set up, or under `--offline`, `--guide` says so in
one line, reads and sends nothing, and the pack is made from the two releases alone.
[What is sent](PRIVACY.md#what-a-guide-sends), [the checks](PACK_SPEC.md#changes-taken-from-a-guide) and
[what a guide cannot give](KNOWN_ISSUES.md#migration-guides) are on their own pages.

## What it will not do

- It writes a move to the whole repository or to none of it. A library that keeps its import name
  across the move is one distribution for both APIs, so one place that obelize cannot migrate holds
  every other file. A real repository often has such a place, and the trial then ends `6` until a
  person or an agent has moved it. [With a coding agent](WITH_A_CODING_AGENT.md) hands those places
  over and keeps the check.
- It finds a method through a class of yours (`User(BaseModel)` and `user.dict()`) only where the
  file shows what `user` is: a call of the class, `self`, an annotated parameter. A value a function
  returned, or a field of another object, is not found.
- It cannot see a name a library builds when it is imported. If a module makes names on demand, the
  command counts the names it could not judge instead of calling them removed.
- It installs only from the index uv is configured for, and only in a trial. A pack that runs a
  maintained tool (`numpy/numpy-1-to-2` runs ruff) runs the tool on your `PATH` over the copy,
  installs nothing, and says on the rows why a file was left when the tool is missing or of a
  release obelize has not measured; `obelize pack validate numpy/numpy-1-to-2` prints what to
  install.
- It does not run a pack for the Python itself. `obelize upgrade setuptools` from a release below 82
  says that the pack for `pkg_resources` moves what that release holds onto the Python, which is no
  release to try, and that `obelize fix --pack setuptools/pkg-resources-to-importlib` runs it. A
  module of the Python or of setuptools that no manifest declares (`obelize upgrade pkg_resources`)
  is stopped with exit `2` and the same command.

A library can change more names than a pack file can hold. Then `upgrade` makes the pack for the
names your code reaches through its imports and says so (`... changed <n> names, more than a pack
holds. It flags the <m> name(s) this repository uses.`). The names come from the `import` statements and the attribute chains that start at what they bind; a name
reached any other way, through an object's attribute for one, is not among them.

## When places are left for a person

A real move often leaves places that a pack made from two releases can only flag, and a library that
keeps its import name has one release for both APIs, so the rules write nothing until every one has
moved. With your own coding agent installed, obelize can put those places to it:

```sh
uvx obelize upgrade pydantic --apply --yes --branch --agent claude_code
```

In the trial's copy, each flagged place is sent to your `claude` program as a text question: the
pack's words about it (the library's own message where it gave one), the closest new names that
`hints.json` offers if there are any, and the lines around it, nothing else, with every tool of the
program turned off. The answer must pass the same guard as any model proposal. The accepted edits go into
the copy, the rules then write the rest, and your tests judge the whole. Only a move the tests agree
to is committed, and only to a branch; the commit message names the files the agent edited, which
are the lines to read first. `--max-asks` limits how many places are asked about. `claude_code` is
the one backend: `codex exec` documents no setting that leaves a model without tools, so it is not
offered ([why](adr/ADR-076-no-backend-for-codex-yet.md)); use Codex beside obelize, with obelize as
the check ([With a coding agent](WITH_A_CODING_AGENT.md)).

An answer may also list the imports it needs, which obelize adds at the top of the file, or say that
a place needs no edit at all, such as a call that passes none of the arguments that changed. That
claim writes nothing and only your tests check it, so the commit message names each such place.

If tests that passed before the move fail after it, the agent is put those too, with the error
and the line of your code the traceback points at, for up to `--max-rounds` rounds. It never edits
a test.

## Runs on real repositories

The first two runs were on a public repository, `academic-mcp` at the commit the benchmark pins, and
none changed a clone's working tree.

- `upgrade PyPDF2 --apply --yes --branch`: the bundled pack changed the import in 19 files and the
  dependency line to `pypdf`. The 60 tests that passed before the move all passed after it, and a commit was made.
- `upgrade mcp --from 1.28.1 --to 2.3.0 --apply --yes --branch --agent claude_code`: no pack existed,
  so one was made from the two releases. It flagged the three places that used `FastMCP`, and the
  agent moved them, given the new names that `hints.json` offered. The 99 tests that passed before
  passed after, and the commit held the one file the agent edited. The dependency line, `mcp[cli]>=1.28.1`,
  carries an extra, so it was left, and the summary and the commit message said so.

The third run needed two fixes before it passed. `upgrade pydantic --from 1.10.26 --to 2.14.1 --apply
--yes --branch --agent claude_code` on a small scraper (`THSR-Ticket`, whose tests that need the
network were left out with `--test-command`) first flagged 55 places, most of them every
`Field(...)` call, because the new release deprecates one of its parameters and gave `repr` a
private default. Neither is a change a call shows, so the pack now flags only the `@validator`
places. The agent moved none of them: the replacement needed `field_validator`, imported at the top of the file,
outside the lines it was sent. A proposal may now list the imports it needs, which obelize adds to
the file's import block, and the import of a name is covered once every place that used it moved.
The agent then moved the ten decorators, the 23 tests that passed before passed after, and the commit
held the one file it edited and the dependency line.

The fourth, on `ga4gh/openapi-test-runner` with pydantic 1.10.13 and the same flags, flagged nine places
(`validator`, `EmailStr.validate`, `pydantic.tools`). The agent moved the validators, rewrote
`EmailStr.validate(x)` as `TypeAdapter(EmailStr).validate_python(x)`, joined both new names to the
import line the files already had, and the 55 tests that passed before passed after. It also added a
check for `None` that a version 2 validator needs, which is why the commit message names the files it
edited.

What they show is that the steps join up, in four runs on three repositories. They do not show how often a move
passes, and the dry run below is the only measure of how far it gets so far.

## How far it gets without a pack

The four runs above were on three repositories. The dry run of `upgrade`, which writes, installs and
tries nothing, is also measured over four frames of twenty public repositories each that
still use the old API of pydantic 1.10.26, SQLAlchemy 1.4.54, urllib3 1.26.20 and pandas 2.3.3, each
planned with a pack made from the two releases ([the numbers](BENCHMARK_RESULTS.md#upgrade-dry-run),
[the method](BENCHMARK.md#upgrade-dry-run)). Over those 80 repositories the dry run of `upgrade` with
no pack writes no file: 36 stop before planning, 33 are held and 11 have no usage of a name the pack
lists. It finds 944 usages: 78 are places a rule would rewrite if nothing else were left in the
repository (all in pydantic, `rename_member`), the pack only flags 810 and 56 are held for a cause of
its own, and none is in a file the dry run would write.

Of the 36 that stop, 18 stop on a manifest that declares the library in a way the pack does not take
(`legacy_version_unsupported`: no version, a range that reaches below the release the pack was made
from, or a pin under it) and 18 on a declared Python that the new release does not run on
(`runtime_unsupported`). Since that measurement `--from` counts where a declaration admits it, as
[described above](#2-plan-one-move), so not all of those 18 would stop now (a pin that rules the
release out still does); I have not measured it again. Each of the 33 that are held has a place the
pack cannot write: 32 have one it only flags, and one has a file the scan cannot parse. A
repository's plan is written only when nothing in it is left, so one such place holds the rest of
that repository.

What did work is the pack and the report: a pack from two releases in 8 to 79 s for four large
libraries, and every place found is reported with its reason. No `--apply` was run on these
repositories, so nothing was written wrongly, and none of this says whether a trial would pass their
tests. [Known issues](KNOWN_ISSUES.md#upgrading-a-dependency) names what still stands between a pack
made from two releases and a written move, and I have not decided it.
