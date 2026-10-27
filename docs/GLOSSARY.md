# Glossary

The words obelize uses, in the sense it uses them. Where a term has a page of its own, the entry
links to it.

## Migration pack

A data file that describes one migration between two versions of a library: which symbols to find,
which [rule kind](#rule-kind) handles each, and what backs it: the official guide for a bundled
pack, the public API of the two releases for one that `pack synth` made. A pack holds no code.
obelize parses it with a closed schema and never executes it. The format is in
[Pack format](PACK_SPEC.md), and the seven that ship are in [Packs](PACKS.md).

## Runtime pack

A [migration pack](#migration-pack) with the Python itself on one side or both: a change of the
interpreter or its standard library (`datetime.utcnow()`, a module Python 3.12 removed) or of a
module setuptools dropped (`pkg_resources`). It names no distribution to install, so it moves no
dependency line, and it is gated by the Python a repository declares ([why](adr/ADR-071-runtime-packs.md)).

## Rule kind

One of the fixed ways obelize rewrites code, such as renaming an import or moving a call to a
client object. A pack chooses a rule kind for each change it declares, and the rewrite itself lives
in obelize, not in the pack. A [plugin](#plugin) can provide one more.

## External fixer

A change that hands the files to a maintained tool (ruff's `NPY201`) instead of rewriting them with
a rule of obelize. The pack names the tool by an id obelize holds, never a command. obelize runs
the tool on your machine, installs nothing, and keeps its output only if it holds to the proof of a
rule's own ([why](adr/ADR-074-external-fixer.md)).

## Member

A method or attribute of a class, such as `dict` of pydantic's `BaseModel`. A `rename_member` change
renames it where your code reads it off an instance of the class, or of a class of yours that
derives from it, and the file shows what the receiver is ([why](adr/ADR-068-rename-member.md)).

## Pattern

Two one-line templates in a pack, `before` and `after`, in which `$name` stands for any expression.
A call is found by the name it is of and compared with `before` by form; `after` is written over
what it bound ([why](adr/ADR-069-rewrite-pattern.md)). A template is read by libcst and never run.

## Plugin

A rule kind that a distribution you installed provides, which a pack can name. It is code that runs
in obelize's process with your rights, so it runs only once you have allowed it in your own
configuration, and obelize does not contain it ([how to write one](PLUGINS.md)).

## Codemod

An automated, mechanical edit of source code. obelize's codemods are written with
[libcst](https://libcst.readthedocs.io/), so an edit keeps the formatting and comments around it.

## Scan

A read-only pass that lists every import, call and dependency line the migration affects, and for
each whether obelize can migrate it. `obelize scan` edits nothing.

## Dry run

What `obelize fix` does until you pass `--apply`: it prints the plan and the diff and writes only
its own record under `.obelize/`.

## Apply

`obelize fix --apply`. It writes the files on the plan, each through a temporary file and a rename,
and records what it did so that `obelize undo` can put the files back.

## Withheld

A place obelize found and did not rewrite. Each withheld place carries a [reason](#reason), so you
can fix it by hand or hand it to an agent. A file is written only when everything in it can be
migrated, so one withheld place holds back its whole file.

## Reason

The closed-vocabulary code that says why a place was withheld, such as `usage_unmapped` or
`file_not_fully_migrated`. [Scan vocabulary](SCAN_VOCABULARY.md) lists every reason and what to do
about it.

## Baseline

Your verification command run on the code as it was before the change. A run is
[verified](#verified) only when the baseline passed.

## Verified

A run is verified when the command you gave to `--verify` passed before the change (the baseline)
and still passes after it. Verified describes your tests agreeing with the change. It does not
prove the migrated code behaves the same where no test looks.

## Run folder

The `.obelize/runs/<id>/` directory every `fix` writes: the plan, the patch, the verification logs
and `REPORT.md`. [The run folder](RUN_FOLDER.md) lists each file.

## Library, SDK and distribution

A library is code you import. An SDK is a library a service publishes to be called from your code,
such as `google-generativeai`. A distribution is the package pip installs, and its name can differ
from the name you import: the distribution `google-genai` provides the module `google.genai`.
obelize reads both, because an import and a dependency line must move together.
