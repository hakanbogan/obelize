# Known issues

I ran a full review of the codebase before opening the repository, and fixed what could hurt
someone running obelize or a number published about it. What is left is lower stakes: rough
edges, missing polish and gaps in the benchmark tooling. This page lists what I know about and
have chosen not to fix yet, grouped by area. The gaps that are actually safety-relevant are in
[THREAT_MODEL.md](THREAT_MODEL.md) instead, alongside what obelize already does about them; this
page does not repeat those.

## Trust and redaction gaps

A plain `http://` model endpoint to a non-loopback host is still accepted. A `base_url` with a
query string or fragment is accepted too, and either can end up in an error message. A relative
`XDG_CONFIG_HOME` is honoured as given, so a user's own configuration can resolve to a path
inside the repository being scanned. Approving a new verification command overwrites the stored
text of an earlier approval rather than adding to it. The request timeout bounds each read from
the network, not the whole request, so a slow reply in small pieces can run far longer than the
configured limit. A few sentences in the documentation cite the wrong safeguard for the wrong
risk; they need a pass to line back up with what the code does.

## Model replies and editing

Context sent to a model has no line numbers, and the text a proposal claims to replace is not
checked against what is actually there, so a reply that is off by one line can delete the wrong
one. A reply nested deep enough, while still within the size limit, can crash the parser that
reads it. A very unusual reply, such as deeply nested JSON or a credential-shaped string that
itself contains an error, can raise an exception that escapes uncaught instead of being reported
as a normal refusal. The path that builds and sends a consultation also does more re-parsing and
re-serialising than it needs to.

## Running commands

An invalid entry in the local list of pre-approved verification commands can still crash instead
of exiting cleanly, the way an invalid `--verify` or `--model` value now does. A baseline command
that modifies a tracked file makes an apply refuse, but the summary does not say the tests did
it. A stored configuration file or run record that is unreadable or holds an unexpected field
blocks `undo` instead of explaining what is wrong. There is no check that a directory is writable
before a migration starts, so a read-only one can be left half migrated. A few files, including
`.obelize/latest` itself, are written by truncating and rewriting rather than by the same
crash-safe rename the rest of the run folder uses. The `fix` summary gives counts of what changed
without saying why an item was left for review or what to do about it. A refusal partway through a
run can still leave the CLI's documented promise that "a refused apply runs no command" untrue,
since a baseline can have already run before the refusal.

## Report and terminal output

A file's own name is untrusted text: an unusual one can inject Markdown into the generated report
or control characters into a terminal that prints it.

Some hints give a POSIX spelling on Windows. The hint after a baseline that failed in obelize's
own environment shows `.venv/bin/python`, the refusal of a command that needs a shell advises
`sh -c`, which a Windows machine may not have, and the `--jobs` help does not mention the limit of
61 that Windows enforces.

## Scanning and rewriting

The syntax check obelize runs before touching a file inherits `from __future__ import
annotations` from its own source, so it can refuse code that is actually valid. A very long chain
of operators can crash the scan with a recursion error, or segfault it outright once the chain is
long enough. Several matching rules key off a spelling or a line position rather than the actual
binding, which can both over-match and under-match in unusual code: a private import used without
a version bound on the library that defines it, a combined import whose surviving names can
shadow the standard library's own `types` module, and a `.text` read rewritten with no warning
when no named handler recognises it. One migration pack's stated limitation does not match what
its rule actually does, and a refusal it declares is never raised. Two call arguments,
`embed_content`'s `task_type` and a dictionary `system_instruction`, are carried into the
rewritten call verbatim instead of through the same alias handling other arguments get. The
dependency-file reader misses some standard pip syntax and misreads uv, hatch and pdm tables; the
Python-floor check only recognises a floor spelled down to the patch version and ignores
`Pipfile`'s own floor.

## Codemod editing quality

A defect in one file can abort an entire run instead of being reported against that file alone,
and so can an unvalidated string that ends up somewhere a stricter type was expected. A comment
inside a rewritten call's arguments, or on a statement the codemod deletes, is lost rather than
kept. A few passes, including how a module gets re-rendered and how repeated attribute lookups
are computed, do more work than they need to and slow a migration down on a large file.

## Data files and formats

The YAML and TOML readers can raise an uncaught parsing error instead of a clean exit. A YAML set
is accepted where the pack format actually cares about order, and a duplicate key is handled in a
way that breaks merge keys and gets slower the more of them there are. The data models validate
loosely enough to coerce a wrong type rather than reject it. `.obelize.yml` is read through a
symbolic link with no size limit. The JSON Schemas I publish do not carry the same value rules the
code enforces, so a document can pass the schema and still fail validation. A file upload rule
also drops a default display name the legacy SDK used to set and changes how a name is
normalised; I have not yet measured how often that matters in practice.

## Tests and fixtures

The test suite has no shared setup, so around 40 files repeat the same fixture-building code by
hand, and the repository walk, a scan, a file read and running the codemod are each reimplemented
several different ways across the tests. Parsing the benchmark's YAML and rebuilding parsed state
account for a large share of how long the whole suite takes to run. A few tests race a short
deadline against how long the interpreter takes to start, share one mutable fixture repository, or
no longer test what their name claims. A number of no-cover markers hide code that is either
still reachable or simply dead and could be deleted.

## The benchmark harness

The harness runs an unreviewed repository's own code without a sandbox, with every environment
secret, the real home directory and the network available to it. Its subprocess helper can hang
waiting on a pipe a background process it started still holds open. A repeated run cannot
reproduce the environment an earlier one used. One published rate was measured with the legacy
SDK still installed alongside the new one, and a headline figure is divided by a different count
than the one printed next to it. The commit recorded as having produced a result is not always the
one that did. A large batch of cases that should never be reported on is never actually checked,
and the harness's own detection of whether a test run passed has drifted from the copy the product
ships. The harness itself is around 13 loose scripts sharing private helpers through path
manipulation rather than a package with its own tests.

## Continuous integration

A few checks run more than once across different jobs. Dependency pinning and the versions of the
tools themselves need a pass. Dependabot never proposes an upgrade for the one dependency the migration
targets, while the scheduled end-to-end job always installs its latest release regardless, so the
two can drift apart. The ruff version is set in two separate places, no job in continuous
integration runs pre-commit itself, and the secret-scanning configuration only excludes the test
fixtures directory rather than every path a planted example could reach.

## Documentation and examples

Some docstrings, comments and specification sentences describe an older version of the code they
sit next to. The bundled example application still defaults to model names that have since been
retired, and its own note about how it was scanned contradicts a limitation the migration pack
itself declares. The JSON Schemas shipped inside the wheel embed links and design notes meant for
this repository, not for someone who only installed the package.

## Code health

A little dead or test-only code remains in the package, a few small utilities are duplicated
across modules, there is an import cycle between two packages, and one module has grown very
large. A handful of docstrings still point forward to work that has since shipped.

## What actually gets migrated

Measured against a real sample of repositories, only a small fraction of eligible call sites
actually migrate end to end, and a repository coming out the other side with every test still
passing is rare. For most repositories, obelize's scan and its automatic rewrites are a starting
point; finishing the migration still takes a person.
