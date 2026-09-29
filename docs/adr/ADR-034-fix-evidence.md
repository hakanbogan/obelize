# ADR-034: Fix evidence

## Status

Accepted; amended by ADR-039 (D1).

## Decision

### D1. `plan.json` is what a run would write; `file_edits` is what it wrote

One row shape, `models.FileEdit` (`path`, `before_sha256`, `after_sha256`,
`hunks`, `rules`, `proposals`), in `plan.json`'s `files[]` and `run.json`'s
`file_edits[]`. A dry run has a full plan and no edits; for an apply that wrote
only part of it, the difference names what did not land, so no reader computes it.

### D2. `plan.json` carries nothing time-derived, and no counts

Two runs over the same input write byte-identical plans; the run id and clock
live only in `run.json`. No counts, because `plan.json` has no stdout twin and
`run.json` beside it already summarises it.

### D3. The patch is bytes, split on `\n`, quoted the way git quotes

`evidence/patch.py` never decodes, splits lines on `b"\n"` only, C-quotes a path
holding a quote, backslash, control or non-ASCII byte, leaves a space unquoted
with a trailing tab on `---`/`+++`, and writes no `index` line, so `git apply`
accepts it. Because a migration must carry latin-1, CRLF, BOM and bare-CR files
through byte for byte.

### D4. Obelize never applies or reverses its own diff

`patch.diff` is for people and `git apply`. The write is `fsutil.write` (temp
file, fsync, rename); `obelize undo` writes `snapshots/before/<sha256>` back
through it, only where the file still hashes to `after_sha256`, and reads
`journal.json` when an interrupted apply left no `run.json`. Because a
reverse-applied diff can half succeed or match a drifted file.

### D5. Snapshots are content-addressed, `apply` only, written files only

`snapshots/before/<before_sha256>` and `snapshots/after/<after_sha256>`, no
extension; `file_edits[]` maps each hash to its path. Before the first write an
apply creates its folder, copies every planned original and writes
`journal.json`; a finished run prunes the copies it did not write and removes
the journal. A dry run writes none. Because a mirrored tree would be a second
path to trust and could not hold two versions of one path.

### D6. A refused write gets its own array, and a seventh code

`run.json`'s top-level `refused[]` (`code`, `path`, `detail`) records what an
apply planned and did not write; `limitations[]` stays what a run could not
look at. `models.RefusalCode` is `fsutil.WriteRefusal`'s six plus `tree_dirty`
and `tree_unknown` (ADR-032 D11), both raised by `evidence/run_dir.py` with
`path: null`; `tree_dirty`'s detail counts the dirty paths and never names
them. Because without it a refused apply reads as one with nothing to do.

### D7. `idempotent` is computed, and the record refuses a disagreement

On an apply, `idempotent` is `true` exactly when `file_edits` is empty (a row
whose hashes match is not an edit); a scan or plan records `null`. `RunRecord`
refuses a record where the two disagree. It describes the bytes only; whether
anything went wrong is `refused[]`'s job.

### D8. `run.json`'s verification is a projection, not the result

`models.VerifyResult` holds each command's output; `models.VerifyRecord`, which
`run.json` holds, replaces it with `log`, a path under `verify/`. The command-row
invariants live in one function both models call. Because the file people
attach to bug reports must not inline a megabyte of test output per command.

### D9. `verify/` is laid out by phase, because the runner numbers by phase

`verify/baseline/<n>.log` and `verify/after/<n>.log`, each beside the junit
report its command wrote, plus `verify/verify.json`, the same `VerifyRecord`
without the logs. Because `runner.run` numbers commands from 1 on every call,
so one directory would collide.

### D10. `REPORT.md` reads the findings beside the edits

A plan or apply report adds what would be or was written, the rules behind it,
edits carrying a warning, and edits a rule refused with their bail and
`caused_by`, and keeps the findings table. A file the scan refused has findings
and no `Edit`, because an `Edit` is what a rule did.

### D11. One report function with an optional run, and no terminal half yet

`report.document(record, scan, run=None, plan=None, proposals=())` renders
`REPORT.md` for every mode and raises when `run` and `plan` do not match
`record.mode`. The terminal summaries (`fixed`, `verified`, `reverted`) are
ADR-035's, in the same module.

### D12. `mode` is what the run was asked to do

An apply refused over a dirty tree records `mode: apply` and still writes its
folder with `plan.json`, `patch.diff` and a `refused[]` row. Because everything
was computed and then declined, unlike an invalid pack, which writes no folder.

### D13. `counts` reports `auto` for a plan, and the driver defines it

A scan reports `eligible` and never `auto`, `plan` and `apply` the reverse, and
`RunRecord` refuses a record that mixes them. `auto` counts rows still `eligible`
after `transforms/codemod.py`, since F-1 has already demoted every row in a file
with anything withheld. Because a second count would disagree with the driver.

## Consequences

- `plan.schema.json` is generated from `PlanDocument`; `ci / schema-drift` guards it.
- `withheld[]` is a finding the run would not rewrite; `refused[]` is a file it would not write. They name different paths.
- Nothing deletes an old run folder; `snapshots/` grows with the repository.
- A binding table in `REPORT.md` must arrive with ADR-020's sentence that `model_object_escapes` and `client_source_unresolved` answer different questions.
