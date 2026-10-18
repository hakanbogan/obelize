# ADR-064: Finding what to upgrade

## Status

Accepted.

## Decision

Two commands close the gap between "this repository has old dependencies" and a plan to move one.
Both read the package index through the seam of ADR-062, install nothing, and write nothing in the
repository but the run folder `fix` always writes.

### D1. `outdated` reads the manifests and asks the index

`obelize outdated` takes the distributions the manifests declare (a constraints file declares
nothing), and for each asks the index for the project and for its JSON, once for the newest release
and once for the release in use. The release in use is the one a declaration pins, else its lower
bound; a declaration that names none is `unknown`. A row says the gap (`major`, `minor`, `patch`,
`none`, `unknown`), the flags the index supports (`inactive` from the classifier, `yanked` from the
files of the release in use, `advisory` from the vulnerabilities listed for that release, whose ids
are kept and whose withdrawn entries are not), and what obelize can migrate it with: `bundled` where
a known pack's `from` covers the release in use, `synthesizable` where the index has a newest release
to compare it with, `none` otherwise. A question the index cannot answer is the row's `error`; only
when it answers none of them, and not merely for want of the project (a private one is not on the
public index), is the command a failure (`6`). The questions are asked eight at a time. The rows
are a document with a committed JSON Schema, worst first: an advisory, then the size of the gap.

### D2. `upgrade` plans one move with the pack that suits it

`obelize upgrade <distribution>` fixes the two ends of the move (`--from`, else what the manifests
say; `--to`, else the newest final release) and chooses a pack: a known one that migrates from the
release in use and, when `--to` was named, to that one; else the pack of ADR-063, made from the two
releases and kept in the cache under both, so a second run asks the index nothing but the project
page. It then runs `fix` without `--apply` and without a model, so the diff, the findings and the
run folder are what any dry run has. It cannot apply: the tests that would show whether the move
holds need the new release installed, which is the work of an isolated environment and not of this
command.

## Consequences

`docs/CLI.md` documents both commands and `outdated.schema.json` is generated beside the others.
A bundled pack is chosen by what its `from` range admits; a migration it covers only in part (the
openai pack from 0.x to 3.x) is still the pack that exists.
