# ADR-065: Trying an upgrade

## Status

Accepted.

## Decision

A migration is verified when the tests that passed before it still pass after it. For a change of
a dependency's release that means two environments, one for each release, which obelize makes
itself and never in the repository.

### D1. A trial is a copy, two environments and the repository's tests

`obelize upgrade <distribution> --apply` copies the repository (the files git lists, byte for byte,
no link or device, into a directory of the user's cache that is a repository of its own, one commit,
no template and no hook), installs the dependencies twice with uv, and runs the tests twice. The
recipe is the lock file if there is one with a `[project]` table, else the project file, else the
`requirements*.txt` at the top; pytest is added. The second environment is the first with the
release moved to installed over it. The tests are pytest unless the person names a command, run by
each environment's own interpreter with its `bin` first on `PATH`, with a junit file.

### D2. The verdict is per test

A test is `classname::name`. The baseline needs no green run: only a test that passed before is
evidence. After the migration is written to the copy, a test that passed before and now fails,
errors or is not reported (a module that no longer imports takes its tests with it) is a break; the
breaks are run once more with `--lf`, and one that passes the second time is reported as flaky and
not as a break. No tests, no junit obelize can read, no test that passed before, or a migration that
wrote no file is `inconclusive` and writes nothing. The junit file is the repository's own output,
so it is refused if it is large or declares a document type or an entity.

### D3. Writing is the same `fix --apply`, after the trial

The trial uses the migration the same code would write: `fix --apply` runs in the copy, with the
same pack and no model. When the verdict is `pass`, the real write is `fix --apply` in the
repository, whose own guards apply (a clean tree is checked before the trial starts, since a trial
takes minutes). That write has no verification command of its own and would end `6` ("patch applied,
no verdict"); the trial was the verification, so the command ends `0`. The run folder of the real
write does not record the trial; `.obelize/trials/<id>/` does, and holds the junit files and output,
the freeze of each environment and the verdict.

### D4. A trial needs a yes

Installing runs the build scripts of what it installs and the tests run the repository's code, so
`--apply` asks: `--yes`, or an answer at a terminal when `CI` is not set, else exit `2`. The
environments and the copy are in the user's cache, outside the repository, and are removed at the
end. What reaches the network is uv's own business with the index uv is configured for.

## Consequences

The old promise that obelize never installs anything is now "obelize installs only in a trial, with
a yes" (TM-6). A same-distribution move is still written only when nothing is left for a person in
the whole repository, so a trial of a repository with flagged places ends `inconclusive` until those
are resolved.
