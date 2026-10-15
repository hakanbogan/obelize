# ADR-015: Configuration merge and exclusions

## Status

Accepted; amended by [ADR-016](ADR-016-file-selection-path-guard.md) (D3).

## Decision

**D1. An unusable configuration file exits `2`.** Invalid YAML, an unknown or
repeated key, or a wrongly typed value stops the run before any repository file
is opened, and nothing is partially applied: the file is part of the invocation,
so a broken one is a usage error like a misspelled flag. A number or a flag is never read from
text or from another type (`allow_dirty: "yes"`, `timeout_s: "60"` and `max_file_bytes: 1000.0`
are wrongly typed), a YAML set is refused because it has no order, and a file over 1 MiB is
refused before it is parsed. Each is a refusal, never a traceback, and one about a value names its
key or line.

**D2. `--verify` replaces the file's list; it does not append to it.** The
override list is then non-empty exactly when every command in the run is level
1, so ADR-007's trust ladder needs no per-command provenance, and no command the
repository chose runs where you named your own.

**D3. A bare boolean flag adds permission and never removes it.**
`--allow-dirty` has no negative spelling, so `allow_dirty: true` in the file
stands; otherwise every flag left unwritten would silently reset a setting.

**D4. The always-excluded set is a published closed list, matched first, and no
`exclude` can undo it.** Eleven patterns, in `docs/CLI.md` and
`obelize.config.ALWAYS_EXCLUDED`, asserted equal in both directions. `.obelize/`
is a correctness property: without it a second scan finds the report the first
wrote. A `!` pattern re-includes only what the user's own `exclude` excluded.

**D5. A verification command that needs a shell is refused when it is read.**
Commands run with `shell=False` (ADR-007), so one whose `shlex` split yields a
bare operator such as `|`, `&&`, `;`, `>` or `<`, or does not split at all, is
refused and told to ask for a shell: `sh -c '<command>'`, or `cmd /c "<command>"` on Windows
(ADR-049). Tokens are checked, not the raw string, so `python -c "print(1>2)"` passes.

**D6. The `fixtures/` directory of a loaded pack that sits inside the repository is left out of
every scan.** Its fixtures are legacy code by design, so a scan that entered them would plan edits
to them. It is skipped as the always-excluded set is, not as an `exclude` is (an excluded file that
imports the legacy distribution would hold the pin, and a fixture is not the repository's code).
It is the `fixtures/` directory beside the pack file, which every fixture path of a pack is under
(ADR-018), and no more: a file the pack sits beside is the repository's own and stays scanned, or
the pin could move past a legacy import nothing read. A pack at the repository root gives up
nothing, and neither does a pack the wheel carries, which the user did not supply. `REPORT.md`
names the directory. It is not a configuration key: a repository's `.obelize.yml` cannot add to
it.

## Consequences

- The configuration models live in `obelize.models` and loading in
  `obelize.config`, so the evidence writer never imports a YAML parser.
- Only the always-excluded set and a loaded pack's `fixtures/` (D6) prune a directory; a user's
  `exclude` filters files and prunes nothing (ADR-016 D3).
- `model.base_url` may not carry a credential, so `docs/RUN_FOLDER.md`'s
  recorded host and `docs/PRIVACY.md`'s never-written key stay true together.
- `.obelize.yaml` is refused by name rather than ignored in silence.
- No key turns the always-excluded set off; `build/` is the pattern likeliest
  to hide a package a user wanted scanned.
