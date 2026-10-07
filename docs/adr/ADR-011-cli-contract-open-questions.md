# ADR-011: CLI contract, open questions

## Status

Accepted; amended by ADR-015 (the exit-code table), ADR-033 (D1.2) and ADR-052.

## Decision

### D1 -- exit `6` when verification produces no verdict

Exit `6`: the status is `inconclusive`, or `not_run` for a reason other than `policy_refused`
(still `5`, per [ADR-007](ADR-007-verify-command-trust.md)), and a verdict was expected,
because `obelize fix --apply` wrote an edit or the command is `obelize verify`. A dry run
(`dry_run`) and an apply that wrote nothing (`no_changes_to_verify`) take their code from the
plan. Not `4`, which `e2e.yml` treats as benign.

- **D1.1** When several verification commands produce different statuses, the run's
  status is the worst of them, in the order `fail` > `inconclusive` > `not_run` >
  `pass`.
- **D1.2** A run whose **baseline** already failed is `inconclusive` with reason
  `baseline_failed`, never `fail`: exit `6`, not `3`, and the after-run is skipped, because a
  failure the baseline already had says nothing about the patch.
- **D1.3** Verification command trust (ADR-007) is evaluated **only when verification
  is going to run**. A run that wrote no edits never consults `verify.commands` and
  therefore never refuses one.

### D2 -- exit `7` when a pack is not valid

Exit `7`: a pack was read and is not valid YAML or not a valid pack, from any command that
loads one; the message says which. A missing file is `2`, as are a pack named twice and two packs
that cannot run together (ADR-052), and an invalid bundled pack is `1`, a defect in Obelize. Not `2`, so a script can tell an invalid pack from a mistyped flag.

### D3 -- the default dry run exits `0`

`obelize fix` without `--apply` exits `0` when it produced a plan, review items or not. Exit
`4` means an apply wrote nothing or left review items outstanding.

### D4 -- `obelize undo --force` is removed from v0

`obelize undo` takes only `--run <id>` and `--repo <path>`, and reverts a file only while its
sha256 equals the run's after-hash: Obelize never overwrites content it did not write. Each
skipped file is reported, and recorded in `undo.json`, with both hashes and its copy under
`.obelize/runs/<id>/snapshots/before/<sha256>`; a hand-edited one has reason `hash_mismatch`.
Exit `4` when anything was skipped or nothing was reverted, else `0`. The snapshot,
`patch.diff` and git keep the bytes a force flag would restore.

### The resulting exit-code table

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Usage error, including an unusable `.obelize.yml` (ADR-015 D1) |
| `3` | Verification failed after patch |
| `4` | Nothing applied / manual review required |
| `5` | Policy refusal (dirty tree, untrusted verification command, path escape) |
| `6` | Verification produced no verdict (`inconclusive`, or `not_run` for any reason other than `policy_refused`) |
| `7` | The pack is not valid |

`2` and `1` take precedence; among the rest the first match wins, in detection order: `7`,
`5`, `3`, `6`, `4`, `0`.

## Consequences

- A first `--apply` in a repository with no tests exits `6`, by design.
- [docs/CLI.md](../CLI.md) publishes the closed verification statuses and reasons.
- Open: `6` for `no_verify_commands` may prove noise; a formatter run after an apply would
  bring `--force` back; validating anything but a pack would reopen what `7` means.
