# Threat model

Obelize edits source files, runs commands and, only if you configure a model,
sends slices of your code to the endpoint you choose. This document lists the
trust boundaries, the threats, the mitigation for each and the test that proves
it. Report a vulnerability as `SECURITY.md` says, never in a public issue.

## Trust boundaries

| Boundary | Source -> target | Trust |
|---|---|---|
| B1 | MigrationPack -> parser | Untrusted data; declarative only (no code) |
| B2 | Repository files -> scanner and model context | Untrusted text; never instructions |
| B3 | Model output -> patch applier | Untrusted proposal; never applied unverified |
| B4 | `.obelize.yml` -> verification runner | Locally owned by the user; untrusted in CI |
| B5 | obelize -> filesystem | Only inside the repository root, only files on the impact list, symlinks not followed |
| B6 | obelize -> network | None, unless the user configures a model endpoint in their own `~/.config/obelize/config.yml`; never one a repository names. No pack downloads, no telemetry |

## Threats, mitigations and tests

| # | Threat | Mitigation (concrete feature) | Test / fixture |
|---|---|---|---|
| TM-1 | Malicious pack (executable content, template injection) | Closed pydantic schema (`extra="forbid"`): `changes[].kind` is an enum, `replacement` a qualified-symbol regex, `verification.suggestions` display-only; a pack id has no dot, so a bundled reference cannot leave the packs directory; `source.url` is https, credential-free and **never requested**; displayed fields refuse control, format and surrogate characters, so no ANSI repaint or right-to-left override disguises a command; the run folder keeps the pack verbatim with its sha256 | Eighty-one packs under `tests/packs/_negative/`, each rejected at the field path its header comment predicts; a socket-blocking test proves loading a pack contacts nothing |
| TM-2 | Path traversal / symlink escape | Containment with **both sides resolved**; a **separate** `is_symlink()` guard; `followlinks=False`; a mandatory regular-file check; submodules pruned and reported; reads open with `O_NOFOLLOW`; writes, and every run-folder access by `verify` and `undo`, descend one directory at a time under `O_NOFOLLOW`. See [TM-2 in detail](#tm-2-in-detail) | A symlink out of the repository -> refused, exit 5; a repository under `/tmp` still produces findings; a submodule with a legacy import is neither scanned nor rewritten; six forged run folders leave every file outside the repository byte-identical |
| TM-3 | Secret leaking to the model | Off by default: under `model.provider: none` no adapter is built and no socket opened, and a repository's `model:` block is refused with exit `2`, so a checkout cannot choose the endpoint or the key. Context comes only from a file holding a withheld finding: the smallest `def` or `class` holding the binding group, else the call site plus 20 lines either side; over 80 lines, **nothing**. It is redacted; `--show-context` prints it and sends nothing; the host is printed on stderr before the scan; no proxy, no redirect. See [TM-3 in detail](#tm-3-in-detail) | A fake `AIza...` key in a comment inside a sent context (`tests/fixtures/providers/deep/nested.py`) is in no request body, nothing printed and no file under `model/` (`tests/fixtures/providers/runs.yaml`) |
| TM-4 | Prompt injection via repository comments, documentation or pack text | Fixed system prompt; repository text is delimited data; the model returns only structured edit JSON; `src/obelize/providers/guard.py` checks every proposal in a fixed order and records the **first** refusal as one of `models.GuardRefusal`'s fifteen words: the consulted file only, its hash still matching the disk; inside the sent range, covering the asked line and naming its symbol; bounded in lines and bytes; encodable in the file's encoding, parsing under libcst **and** compiling; adding no import outside the pack's targets, `__import__` and `importlib.import_module` included; naming only what the replaced lines named, a target import or the replacement binds, or a few pure builtins, never a double-underscore name; not changing how later lines are read; no character a terminal acts on. See [TM-4 in detail](#tm-4-in-detail) | Twenty-one hand-written proposals in `tests/fixtures/providers/proposals.yaml`, thirteen of the fifteen words between them and exactly one accepted; fake adapters patching `../../.bashrc` and adding `os.system`, refused for every consultation, every file in and outside the tree byte-identical afterwards |
| TM-5 | Malicious verification command from repository configuration in CI | The [trust rule](#verification-command-trust-rule) below; no shell (`shlex.split`), so a command carrying `\|`, `&&` or `>` is refused when the configuration is read, as is one carrying a control, format or surrogate character other than a tab or a newline, so the prompt shows the command that runs; one refused command refuses the whole phase, since the rest would give a `pass` over half a verification | Twenty-four cases in `tests/fixtures/verify/` over real processes: a repository command under `CI` -> `not_run`, `policy_refused`, exit 5, nothing spawned; refused without a terminal, under `--non-interactive` and at the prompt; allowed by the user's allowlist, by `--trust-repo-config` and by a stored approval |
| TM-6 | Dependency installation | obelize never runs pip or uv; it edits the manifest as text and says "installation required"; only the user's own verification commands can install anything, and they are visible | Subprocess spy test: only configured commands are ever spawned |
| TM-7 | Our own supply chain | Trusted Publishing with attestations; SHA-pinned actions; Dependabot; few runtime dependencies (<= 7); `pip-licenses`; 2FA; `uv lock --check`; a release builds with a pinned backend, only from a commit ci passed on `main`, and checks its version, tag and changelog section before any upload; once the repository is public, the `pypi` environment waits for my approval and only I can create a `v*` tag | CI `lock` job; `tests/unit/test_packaging.py` bounds the runtime dependencies and builds with the pinned backend; `tests/unit/test_workflows.py` holds every action to a commit and runs the release's checks |
| TM-8 | Overwriting the user's work | `git status --porcelain -z --untracked-files=no` over the **whole tree**, from any directory in it, plus every file on the plan that git does not track. With no file changed, a dirty tree refuses the apply unless `--allow-dirty`, a git that cannot answer refuses it (`tree_unknown`), and so does a file changed since the plan read it (`file_changed_since_read`); evidence reaches the run folder before the write. See [Git and file safety rules](#git-and-file-safety-rules) | Eleven repositories under `tests/fixtures/apply/`: five refuse with every file byte-identical, two are a directory of a larger repository, `untracked/` and `staged/` differ by a `git add`, and `untracked_target/` plans a file git does not track; `tests/fixtures/evidence/dirty/` grades the record of a refusal; every `patch.diff` reproduces the migration under `git apply`; `tests/fixtures/commands/` grades the refusal and the undo over twelve cases in five fixture repositories |
| TM-9 | Evidence leaking secrets | One redactor for evidence, logs and model payloads ([Secret redaction](#secret-redaction)); the environment is never recorded; output is capped at 1 MiB kept as its two ends | A command printing two fake credentials, one caught by shape and one by its variable's name, run directly first so "the secret is absent" cannot pass over an empty capture |
| TM-10 | Runaway verification command | Default timeout 600 s; the command runs in its own session and the deadline kills its whole process **group**, `SIGTERM` then `SIGKILL`, because a server a test runner started holds the same pipe; `inconclusive` with reason `timeout`, never `fail`. After the command exits, a group still holding the pipe is killed after a short read. The read stops at end-of-file, the deadline, **and** a short second deadline after the kill, because a command can close its output and keep running, or start a child in another session | A sleep past the timeout -> `inconclusive`, `timeout`, exit 6, earlier output kept; a spawned child is gone and never writes its file; two tests in `tests/unit/test_verify_runner.py` for the stopping conditions end-of-file cannot provide |

## TM-2 in detail

**Resolve both sides:**
`candidate.resolve(strict=True).is_relative_to(root.resolve(strict=True))`,
`False` on `OSError` (dangling links) or `RuntimeError` (loops). Against an
unresolved root, *every* file is outside when the repository sits under `/tmp`,
`/var` or `/etc` (symlinks on macOS), and the scan silently finds nothing.

**Keep the symlink guard separate.** A symlink whose target is inside the
repository passes containment and must still not be followed.

**Guard the parent chain when writing.** `os.replace` never follows a link at
its target but resolves every directory above it, so a `pkg/` swapped for a
link to `/etc` would redirect the write. The rename opens the root (it may be a
link: the user gave it), then each component with
`O_RDONLY | O_DIRECTORY | O_NOFOLLOW`, and creates and renames the temporary
file against that descriptor. `apply` asks `fsutil.refusal` about every planned
path before writing any, and each write asks again; the codemod driver produces
no bytes for a path the scan did not select. Reads guard only the last
component: whoever can win a read race can write into the repository anyway.

**Prune submodules in the `os.walk` fallback.** `git ls-files` lists a
submodule as one gitlink entry, which the regular-file check drops. The fallback
walk prunes any subtree holding a nested `.git`, because this repository's diff
cannot review a submodule's files.

**Open the run folder, never follow it.** A checkout can carry a committed
`.obelize/`. `obelize verify` and `obelize undo` reach a run folder only
through `src/obelize/evidence/folder.py`: each directory from `.obelize/` down
opens relative to its parent with `O_DIRECTORY | O_NOFOLLOW`, files are read
with `O_NOFOLLOW`, and a write goes beside its name and is renamed over it.
`obelize fix` creates its folder under a fresh random id and refuses a link at
`.obelize/`, `runs/` and `latest`. `.obelize/.gitignore` is written the same way
as a verify or undo write, and only where nothing, a link included, is at that
name.

**On Windows**, which is not supported yet, the same calls are made in
`src/obelize/native/files_windows.py`. The root is opened with `CreateFileW`,
which follows a link as the root is followed here, and each name below it with
`NtCreateFile` relative to the parent directory's handle, with
`FILE_OPEN_REPARSE_POINT`. A symbolic link or a junction, which any user can
make, is therefore opened as itself and refused like a symbolic link, while a
reparse point that names no other path, such as a OneDrive placeholder, is read
as the file it is. The temporary file is created with `FILE_CREATE`, which
fails on any name that exists, and the rename and each delete go through the
open file, the rename naming its target relative to the parent. A read by path
opens the last component with `FILE_FLAG_OPEN_REPARSE_POINT`. A write keeps the
read-only attribute, the only part of a mode Windows has.

## TM-3 in detail

**What is sent** is decided by `src/obelize/providers/base.py` and graded by
`tests/fixtures/providers/answers.yaml`; `tests/fixtures/providers/requests.yaml`
holds the message byte for byte.

**Where it is sent:** `src/obelize/providers/openai_compat.py` departs four ways
from `urllib`'s defaults, which honour `http_proxy`/`https_proxy` and follow
redirects, either of which could carry the payload and the `Authorization`
header to a host the run never printed:
`ProxyHandler({})`; a redirect is refused (`endpoint_redirected`); no cookies;
no compression, so the 1 MiB response cap counts bytes on the wire. The URL is
`base_url` plus `/chat/completions`, never `urljoin`, which drops a trailing
`/v1`. Both are measured against a real local server, with `http_proxy` routed
to it so a request through the proxy would be recorded.

**What is written down** never holds the API key: it travels in a header, outside the recorded prompt
and its hash. The prompt is recorded only under `model.log_prompts`, because a
prompt is source code. An endpoint's own words are redacted *before* being cut
to length, so a gateway quoting back a rejected key cannot leak it.

**What is deliberately not redacted** is `patch.diff` and `snapshots/`: they
carry whole files ([PRIVACY.md](PRIVACY.md)). The corpus asserts the key is
absent from `model/` and **present** in the patch.

## TM-4 in detail

A model is asked only about `needs_review` rows in a file this run could write,
never a row the pack refused on purpose, and is sent one bounded range. A
proposal therefore answers a question naming one file, one line and one symbol.

**The order is part of the mitigation.** Only the first failed check is
recorded, so the checks run outward from "may we touch this file at all":
`../../.bashrc` is reported as an escape, not an unplanned file.

**Two checks come after the file and range checks.** The replaced range must
contain the asked line, because the sent range is a whole scope. The
replacement must encode in the file's encoding, because otherwise writing it
rewrites every line.

**What it does not cover.** The guard proves an edit safe to apply, not
correct; `--accept-model` and a reviewer cover the rest. Nothing detects an
injected instruction: whatever the model was persuaded to answer must pass
every check.

## Verification command trust rule

Running a command is the most dangerous thing obelize does, so the decision
rests only on *where a command came from*. Precedence, highest first:

1. `--verify "<cmd>"` on the command line. Always permitted: the user typed
   it into their own shell.
2. The user allowlist in `~/.config/obelize/config.yml`.
3. The repository's `.obelize.yml` (`verify.commands`).
4. A pack's `verification.suggestions`. Never run automatically, under any
   flag. Displayed as "suggested, not run".

Level 3 depends on the mode:

- Local interactive (TTY attached, `CI` unset, `--non-interactive` absent):
  each command is printed verbatim and confirmed once with `y`. The approval,
  keyed by repository path and the command's sha256, is stored in
  `~/.config/obelize/approved.json`; a changed command is asked again. A run
  that cannot ask is refused.
- Non-interactive or CI (`CI` set to any value, even empty): repository
  commands run only if they match the user allowlist or `--trust-repo-config`
  was passed. Otherwise the result is `not_run` with reason `policy_refused`,
  the command is displayed, and the exit code is `5`.

In every mode the working directory is the repository root, the environment is
inherited plus `OBELIZE_RUN=1`, and there is no shell. Local execution is
**not** isolated: a verification command can do anything your shell can.

## Secret redaction

One module, `src/obelize/verify/redact.py`, for evidence, logs, model
payloads and the diff a dry run prints (`patch.diff` itself stays whole).

1. Value-based. For every environment variable whose *name* matches
`(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)`, in any case, and whose
value is at least 8 characters long, occurrences of that value are replaced
with `[REDACTED:<NAME>]`, longest value first and in a total order so two runs
agree.

2. Pattern-based. The following patterns are replaced wherever they appear:

```
AIza[0-9A-Za-z_-]{35}
sk-[A-Za-z0-9_-]{20,}
AKIA[0-9A-Z]{16}
ghp_[A-Za-z0-9]{36}
(api[_-]?key|token|secret)\s*[:=]\s*['"][^'"]{8,}['"]
```

plus PEM private key blocks. The quoted assignment keeps the setting's name.

3. Documented limit. Secret formats not on this list are **not** redacted.
Redaction reduces accidental exposure; it is not a guarantee. Review a run
folder before sharing it.

Rule 1 **over**-redacts on purpose (`GIT_AUTHOR_NAME` matches `AUTH`): a list
of exact names would miss the first variant spelling. Above the 1 MiB cap the
middle of the output is never held, so a secret straddling the elision is cut
rather than removed.

## Git and file safety rules

- Dry-run is the default. Writing requires an explicit `--apply`.
- `patch.diff`, the before/after sha256 of every affected file and the
  originals are in the run folder before anything is written
  ([RUN_FOLDER.md](RUN_FOLDER.md)).
- A tree with uncommitted tracked changes, staged ones included, refuses
  `--apply`, so that `git diff` is exactly the migration; `--allow-dirty`
  proceeds, and `run.json`'s `git_dirty` records it. Untracked files do not
  count, since obelize's own run folder is one, unless the plan would rewrite
  one: `git diff` cannot show that change. Outside a git repository there is
  no dirty-tree check.
- A refused apply still writes its run folder, with the plan, the patch and a
  `refused[]` row, so it cannot read as one with nothing to do. Refusals
  come before any verification command starts.
- Writes are atomic: a temporary file plus a rename. Only files on the plan are
  written.
- Obelize never creates a branch, never commits, never pushes and never merges.
- `obelize undo --run <id>` restores only files whose current hash equals the
  recorded after-hash. A hand-edited file is skipped and reported with both
  hashes and the path of its pre-migration copy; there is no `undo --force`.
  `tests/unit/test_undo_command.py` grades every way undo declines.
- What a run folder holds: [PRIVACY.md](PRIVACY.md).

## Status of mitigations

No row reads `yes` without a passing test in the `ci` workflow's suite.
`partial` is not a pass. A `partial` row names the
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) entry that covers what is still open, or
cites [ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md) where that ADR accepts
the gap; `tests/unit/test_roadmap.py` fails a row that names neither. The
release gate in [ROADMAP.md](ROADMAP.md) holds `v0.1.0` until TM-2, TM-5,
TM-8, TM-9 and TM-10 read `yes` or an ADR accepts their gaps; ADR-048 accepts
those of TM-5, TM-8, TM-9 and TM-10.

| # | Threat | Mitigation implemented | Test in CI |
|---|---|---|---|
| TM-1 | Malicious pack | yes: the schema and the evidence | yes: eighty-one negative packs, one per documented refusal, and the evidence |
| TM-2 | Path traversal / symlink escape | yes: reads and writes in the working tree and in a run folder | yes: both halves, and six forged run folders |
| TM-3 | Secret leaking to the model | partial: a repository cannot choose the endpoint or the credential; what is still open is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md#trust-and-redaction-gaps) | yes: the message byte for byte, the proxy and the redirect, and every invocation over `model/` |
| TM-4 | Prompt injection | yes: the guard, its fifteen words and its name allowlist | yes: twenty-one proposals and two fake adapters |
| TM-5 | Malicious verification command in CI | partial: the ladder and the mechanics, and a command a terminal would render as another is refused; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: twenty-four cases |
| TM-6 | Dependency installation | no | no |
| TM-7 | Our own supply chain | partial: SHA-pinned actions, the dependency bound, the lock check, and a release that builds with a pinned backend and checks ci, its version, its tag and its changelog section before any upload; what a public repository still needs is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md#continuous-integration) | yes: the lock, the dependency bound, the action pins and the release workflow's checks |
| TM-8 | Overwriting the user's work | partial: detection, refusal, record and undo from any directory, and a git that does not answer refuses; evidence precedes the write and undoes an interrupted apply; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: the refusal from the top and from a subdirectory, a git that does not answer, and twelve cases over the commands |
| TM-9 | Evidence leaking secrets | partial: the redactor and the cap; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: with its control |
| TM-10 | Runaway verification command | partial: the group kill and the three deadlines; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: three shapes |

Until the row for what you are about to do reads `yes`, run obelize only on a
repository you have committed or backed up.
