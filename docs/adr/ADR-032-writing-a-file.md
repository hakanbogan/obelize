# ADR-032: Writing a file

## Status

Accepted; amended by ADR-049.

## Decision

### D1. The dirty-tree refusal is over the tree, and `docs/CLI.md` is corrected

`--apply` is refused when any tracked path in the repository has an uncommitted change, not only a
path on the plan, because a clean tree makes `git diff` the migration and `git checkout` the
recovery (ADR-011 drops `undo --force` on that). `docs/CLI.md` says the tree. `fsutil.apply`
returns every dirty path (D2); the report counts them and never names them, because they are the
user's own uncommitted work (ADR-034). `--allow-dirty` skips the check.

### D2. `--untracked-files=no` survives its first contact with a real apply

Untracked files are not dirt: obelize writes `.obelize/runs/<id>/` itself, so counting them would
refuse every run after the first. A staged change is dirt: porcelain reports the index in the first
of its two status columns, and both are read, because staged work is not committed work. A file on
the plan that git does not track is dirt as well, because `git diff` cannot show its rewrite and
`git checkout` cannot undo it; the run folder is never on the plan.

### D3. `git status --porcelain -z`, and both names of a rename

Under `-z` no path is quoted, so a non-ASCII path is read as it is in the tree, not as
`"caf\303\251.py"`. A rename or copy carries its origin as an extra NUL-terminated record with no
status field; both names are read, because misreading it shifts every following path, and a run
could overwrite an uncommitted rename under the name its author stopped using.

### D4. A write is a temporary file beside the target, an `fsync`, the original mode, and a rename

`os.replace` is atomic, so a reader sees the old file or the new one; `Path.write_bytes` truncates
first and leaves half of each after a crash, kill or full disk.

- The temporary is in the target's own directory: a rename across filesystems fails with `EXDEV`,
  and a copy fallback is the half-written file this prevents.
- Its name starts with a dot and ends in `.obelize-tmp`, so a crash's leftover is never scanned.
- The target's mode replaces the temporary's `0600` before the rename, so no executable bit is lost.
- Only the file is fsynced: this survives a crash or kill, not a power cut, which would need one
  more `os.fsync` on the already-open directory descriptor.

### D5. The parent chain is descended one name at a time with `O_NOFOLLOW`; the root is not

`rename` never follows a link at its target but resolves every directory above it, so a `pkg/`
swapped for a link to `/etc` between guard and write would write into `/etc` (TM-2). `apply` opens
the root, then each component below it with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW`, and creates and
renames the temporary against that descriptor. The root is opened without `O_NOFOLLOW`, because a
repository reached through a link is ordinary (`/tmp` on macOS). `fsutil.read` guards only the last
component: winning a race on a read gains nothing an attacker who can swap a directory could not
already write, while a scan would pay one `openat` per directory per file.

### D6. Every path is checked before any is written, and the write checks again

`apply` asks the guard and the staleness check (D7) of every path first, and writes nothing if any
refuses: a refusal means the tree is unchanged. `write` asks the guard again, because the pre-flight
can be raced and `write` can be called directly. A race that remains is reported, not rolled back:
each file already written is complete and parses (ADR-010 F-1), and a rollback is itself writes that
can fail.

### D7. A file whose bytes are not the bytes the plan read stops the whole apply

`Change` carries `before` and `after`, and a file whose content is no longer `before` is refused as
`file_changed_since_read`: an edit made between scan and apply, or during a verification phase, that
the dirty-tree gate cannot see. It stops the whole apply, because a file that moved means the plan is
stale. It is a refusal and not a re-run: scanning again is a command's decision, and a plan that
repairs itself while applying is one nobody reviewed.

### D8. The write vocabulary is closed here, and it is not `limitations[].code`

`fsutil.WriteRefusal` is `models.PathRefusal`'s five values (`missing`, `not_a_file`,
`outside_root`, `symlink`, `unreadable`), shared with `Skipped.reason` so one question has one word,
plus `file_changed_since_read`. `PathRefusal` is what `fsutil.refusal` decides; `submodule` and
`unusable_name` stay the walker's. It is not `LimitationCode`, which is what a run could not look
at; a refused write is what it declined to do, and `run.json` records it in `refused[]` (ADR-034).

### D9. `apply` lives in `fsutil` and calls `gitutil`, so the order is not the caller's to get wrong

The dirty-tree gate and the writes are one call, `fsutil.apply`, so "refused with no file changed"
never depends on a caller's order. `fsutil.gate` asks the same gates without writing, so
`fix --apply` can refuse before a baseline runs; `apply` asks them again. `apply` takes a
`Sequence[Change]` of paths and bytes, not a `codemod.Run`, so the guard never imports the transform
stack.

### D10. A run replaces files. It never creates one

Every path `apply` writes was read by the scan, so a path not on disk is refused as `missing` by the
walker's own `refusal`. An absolute or empty path, or one containing `..`, is refused as
`outside_root`: `Path("/repo") / "/etc/passwd"` is `/etc/passwd`, and a descent follows `..` as a
shell does.

### D11. A directory inside a repository is gated on the repository, and no answer is not a no

`gitutil.tree` asks `git rev-parse --show-prefix` and `git status`, and with a plan also
`git ls-files`, and has three answers. No repository (git fails and no `.git` is at or above the
directory): the apply proceeds. A work tree, at its top or below: `git status` reports the whole
repository and the gate refuses on any of it (D1), also when `--repo` is spelled in another case on
macOS, and on a planned path `git ls-files` does not list (D2). No answer (git fails or times out
beside a `.git`, or inside `.git`): the apply is refused as `tree_unknown`, a `refused[]` code that
`--allow-dirty` also skips, since the flag waives the question. `run.json`'s `git_dirty` reads the
same answer without a plan, so no untracked file sets it, and is `null` when git cannot say;
`git_sha` and `git_branch` stay `null` below the top (ADR-023 D10).

## Consequences

- TM-2's write half: every write asks the same `fsutil.refusal` the walker reads through, and a
  submodule is never in a scan, so nothing writes one.
- The four `tests/fixtures/scan/encoding/` answer keys come back byte for byte after a real write,
  and a file whose parse does not reproduce its own bytes is left alone (ADR-031 D7).
- Outside a git repository the tree gate refuses nothing, so TM-8 protects nobody there
  (`docs/RUN_FOLDER.md`).
- `O_NOFOLLOW`, `dir_fd` and `os.fchmod` are POSIX; on Windows the same guarantees are made with the
  calls [ADR-049](ADR-049-platform-seam.md) describes.
