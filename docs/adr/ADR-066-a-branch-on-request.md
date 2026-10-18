# ADR-066: A branch on request

## Status

Accepted.

## Decision

obelize still never pushes or merges. It makes a branch and a commit when the person asks for one,
and only for a move a trial has passed.

### D1. `upgrade --apply --branch` commits the move instead of writing it

After a trial passes, `--branch` (or `--branch-name <name>`, which implies it) commits the files the
migration wrote into the trial's copy, on top of `HEAD`, to a new branch. The default name is
`obelize/upgrade-<the release moved to>`. The working tree is not written and `fix --apply` does not
run, so there is no run folder of a write; the commit's message names the pack, the trial's counts
and the trial's id as a trailer (`Obelize-Trial:`), and `.obelize/trials/<id>/` holds the evidence.

### D2. The commit is built with git's plumbing and nothing else is touched

The files go in with `hash-object -w`; a temporary index, outside the repository's own, starts from
`HEAD` with `read-tree` and takes them with `update-index`; `write-tree` and `commit-tree` make the
commit; `update-ref` points a new ref at it and is told the ref must not exist. The mode of a file
that `HEAD` has is kept, so an executable stays one. From a directory below the top of the
repository the paths are spelled from the top. No checkout and no read of the working tree happens,
so uncommitted work stays where it is. Hooks are looked for nowhere (`core.hooksPath` is the null
device), because `update-ref` runs `reference-transaction` and a repository's own configuration says
where hooks are; the commit is not signed, because a signing prompt would hang a command nobody
watches; a name `check-ref-format` refuses, a repository with no commit, a committer git does not
know and a branch that exists are each an error that says so (exit `2`).

## Consequences

The sentence that obelize never commits or branches becomes "never pushes or merges, and branches
only when asked". `docs/SAFETY.md`, `docs/THREAT_MODEL.md`, the README and the skill say it.
