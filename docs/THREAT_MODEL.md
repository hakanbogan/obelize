# Threat model

Obelize edits source files, runs commands and, only if you configure a model or
ask `upgrade` to use your own coding agent, sends slices of your code to the
endpoint or the program you chose. This document lists the
trust boundaries, the threats, the mitigation for each and the test that proves
it. Report a vulnerability as `SECURITY.md` says, never in a public issue.

## Trust boundaries

| Boundary | Source -> target | Trust |
|---|---|---|
| B1 | MigrationPack -> parser | Untrusted data; declarative only (no code). Its source is the wheel, a directory your own `config.yml` lists, or a path you type; never a repository's file |
| B2 | Repository files -> scanner and model context | Untrusted text; never instructions |
| B3 | Model output -> patch applier | Untrusted proposal; never applied unverified |
| B4 | `.obelize.yml` -> verification runner | Locally owned by the user; untrusted in CI |
| B5 | obelize -> filesystem | Only inside the repository root, only files on the impact list, symlinks not followed |
| B6 | obelize -> network | None, unless the user configures a model endpoint in their own `~/.config/obelize/config.yml`, or runs `pack synth`, `outdated` or `upgrade`, which ask the package index the user names there or in the environment (`outdated` for every dependency a repository declares), and with `--guide` the one page the user types; never an endpoint, an index or a page a repository names. Every host obelize reaches is printed first. Three things reach a host obelize does not print: `upgrade --apply`, where uv installs from the index uv is configured for, `upgrade --agent`, where the user's own `claude` sends a prompt to its login host, and `--guide` through that same agent. No pack downloads, no telemetry |
| B7 | Coding agent -> obelize (`obelize mcp`) | An untrusted caller: it may name a pack, a library, a module or a run, and nothing else; no command, path, model or consent. What it receives is repository text, which is data to it |
| B8 | Package index and its files -> archive reader and API reader (`pack synth`) | Untrusted bytes from a server and from the library's authors: never built, installed or run; opened for source and four describing files only; read statically in a child process with limits; what they say is quoted as data |
| B9 | A maintained tool (`external_fixer`) -> patch applier | Untrusted output of a program on the user's machine that a pack names by an id obelize holds: a source of edits and never of trust (TM-15) |
| B10 | A migration guide -> a model -> claims (`--guide`) | Untrusted text from a page or a file, read by a model that has no tool, whose reply is untrusted too: it is a list of claims, and code decides which become part of a pack (TM-16) |

## Threats, mitigations and tests

| # | Threat | Mitigation (concrete feature) | Test / fixture |
|---|---|---|---|
| TM-1 | Malicious pack (executable content, template injection) | Closed pydantic schema (`extra="forbid"`): `changes[].kind` is an enum, every symbol a qualified-symbol regex, `verification.suggestions` display-only; a pack id has no dot, so a bundled reference cannot leave the packs directory; `source.url` is https, credential-free and **never requested**; displayed fields refuse control, format and surrogate characters and line separators, so no ANSI repaint or right-to-left override disguises a command, and `REPORT.md` escapes their Markdown and HTML, so a viewer fetches and runs nothing; the run folder keeps the pack verbatim with its sha256, and a `rewrite_pattern` can call only into the modules it lists under `imports`, each of a closed list of the few (`datetime`, `json`, `re`, `importlib.metadata` and the like) that build or read a value and reach nothing else, and one segment below it, so `os`, `subprocess`, `importlib` itself and a module nobody has looked at are refused when the pack loads; `pack validate` and the header of `fix` print the paths a pack may call into, so a pack written by someone else is read before it is run. A pack names a maintained tool by an id obelize holds (`external_fixer`) and carries no command, flag, path or release ([TM-15](#threats-mitigations-and-tests)). This is a guard against a pack that names a dangerous module, and not a sandbox: a listed module's own functions run in the repository; a pack that is only mistaken is covered under [What a pack can get wrong](#what-a-pack-can-get-wrong-without-being-hostile) | Two hundred and fifty-two packs under `tests/packs/_negative/`, each rejected at the field path its header comment predicts; a socket-blocking test proves loading a pack contacts nothing |
| TM-2 | Path traversal / symlink escape | Containment with **both sides resolved**; a **separate** `is_symlink()` guard; `followlinks=False`; a mandatory regular-file check; submodules pruned and reported; reads open with `O_NOFOLLOW`; writes, and every run-folder access by `verify` and `undo`, descend one directory at a time under `O_NOFOLLOW`. See [TM-2 in detail](#tm-2-in-detail) | A symlink out of the repository -> refused, exit 5; a repository under `/tmp` still produces findings; a submodule with a legacy import is neither scanned nor rewritten; six forged run folders leave every file outside the repository byte-identical |
| TM-3 | Secret leaking to the model | Off by default: under `model.provider: none` no adapter is built and no socket opened, and a repository's `model:` block is refused with exit `2`, so a checkout cannot choose the endpoint or the key. Context comes only from a file holding a withheld finding: the smallest `def` or `class` holding the binding group, else the group plus 20 lines either side; over 80 lines, **nothing**. It is redacted; `--show-context` prints it and sends nothing; the host is printed on stderr before the scan; no proxy, no redirect. See [TM-3 in detail](#tm-3-in-detail) | A fake `AIza...` key in a comment inside a sent context (`tests/fixtures/providers/deep/nested.py`) is in no request body, nothing printed and no file under `model/` (`tests/fixtures/providers/runs.yaml`) |
| TM-4 | Prompt injection via repository comments, documentation or pack text | Fixed system prompt; repository text is delimited data; the model returns only structured edit JSON; `src/obelize/providers/guard.py` checks every proposal in a fixed order and records the **first** refusal as one of `models.GuardRefusal`'s seventeen words: the consulted file only, its hash still matching the disk; inside the sent range, covering the asked line, naming its symbol and quoting the lines it replaces as they were sent; bounded in lines and bytes; encodable in the file's encoding, compiling **and** parsing under libcst; adding no import outside the pack's targets, `__import__` and `importlib.import_module` included, and the proposal's own `imports` list being one plain `import` or `from ... import` of a target each, joined to the file's own line or placed after its imports and never on a line it replaces; naming only what the replaced lines named, a target import or the replacement binds, or a few pure builtins, never a double-underscore name; not changing how later lines are read; no character a terminal acts on; no `[REDACTED` placeholder the replaced lines did not hold. See [TM-4 in detail](#tm-4-in-detail) | Twenty-four hand-written proposals in `tests/fixtures/providers/proposals.yaml`, fifteen of the seventeen words between them and exactly one accepted; fake adapters patching `../../.bashrc` and adding `os.system`, refused for every consultation, every file in and outside the tree byte-identical afterwards |
| TM-5 | Malicious verification command from repository configuration in CI | The [trust rule](#verification-command-trust-rule) below; no shell (`shlex.split`), so a command carrying `\|`, `&&` or `>` is refused when the configuration is read, as is one carrying a control, format or surrogate character other than a tab or a newline, so the prompt shows the command that runs; one refused command refuses the whole phase, since the rest would give a `pass` over half a verification; every git call obelize makes empties `core.fsmonitor` and takes no optional lock, so the repository's own config cannot start a hook while the tree is read, neither the file monitor nor the `post-index-change` hook a stale index would run | Twenty-four cases in `tests/fixtures/verify/` over real processes: a repository command under `CI` -> `not_run`, `policy_refused`, exit 5, nothing spawned; refused without a terminal, under `--non-interactive` and at the prompt; allowed by the user's allowlist, by `--trust-repo-config` and by a stored approval; a `core.fsmonitor` hook and a `post-index-change` hook behind `core.hooksPath` that touch a marker, which `git status` runs and `gitutil` does not |
| TM-6 | Dependency installation | obelize edits the manifest as text and says "installation required"; the user's own verification commands are visible, and so is the one other thing that installs, `upgrade --apply`: it asks first (`--yes`, or a terminal and no `CI`), refuses a tree with uncommitted changes before it starts, and installs with uv into environments outside the repository, in a copy of it, so no installer runs in the repository itself; a pack that sets `declare_transitive` writes into a manifest only the names its own `match.transitive` lists, never one read from the repository; a pack that runs a maintained tool does not install it, and a missing tool is a reason on the rows and the command that installs it | Subprocess spy test: only configured commands are ever spawned; `tests/unit/test_upgrade.py`: a trial without `--yes` runs nothing, and a dirty tree is refused before any copy |
| TM-7 | Our own supply chain | Trusted Publishing with attestations; SHA-pinned actions, a commit for the pre-commit hook repository, and the one uv release the actions install; Dependabot, which waits a week after a release; few runtime dependencies (<= 7); `pip-licenses`; 2FA; `uv lock --check`; a release builds with a pinned backend, only from a commit ci passed on `main`, and checks its version, tag and changelog section before any upload; the `pypi` environment waits for my approval and only I can create a `v*` tag | CI `lock` job; CI `workflows` job, which runs zizmor and so holds each GitHub action to a commit and is a required check; `tests/unit/test_packaging.py` bounds the runtime dependencies, builds with the pinned backend and holds each hook repository to a commit; `tests/unit/test_workflows.py` runs the release's checks |
| TM-8 | Overwriting the user's work | `git status --porcelain -z --untracked-files=no` over the **whole tree**, from any directory in it, plus every file on the plan that git does not track. A dirty tree refuses an apply that has a file to write, or a model that could propose one, unless `--allow-dirty`, a git that cannot answer refuses it (`tree_unknown`), and so does a file changed since the plan read it (`file_changed_since_read`); evidence reaches the run folder before the write. See [Git and file safety rules](#git-and-file-safety-rules) | Eleven repositories under `tests/fixtures/apply/`: five refuse with every file byte-identical, two are a directory of a larger repository, `untracked/` and `staged/` differ by a `git add`, and `untracked_target/` plans a file git does not track; `tests/fixtures/evidence/dirty/` grades the record of a refusal; every `patch.diff` reproduces the migration under `git apply`; `tests/fixtures/commands/` grades the refusal and the undo over twelve cases in five fixture repositories |
| TM-9 | Evidence leaking secrets | One redactor for evidence, logs and model payloads, and for the command and the command line a run records ([Secret redaction](#secret-redaction)); the environment is never recorded; output is capped at 1 MiB kept as its two ends | A command printing two fake credentials, one caught by shape and one by its variable's name, run directly first so "the secret is absent" cannot pass over an empty capture |
| TM-10 | Runaway verification command | Default timeout 600 s; the command runs in its own session, closing it kills what is left of its **group** so a Ctrl-C of obelize leaves nothing running (a `SIGTERM` or `SIGHUP` sent to obelize itself does not: nothing handles them), and the deadline kills the whole process **group**, `SIGTERM` then `SIGKILL`, because a server a test runner started holds the same pipe; `inconclusive` with reason `timeout`, never `fail`. After the command exits, a group still holding the pipe is killed after a short read. The read stops at end-of-file, the deadline, **and** a short second deadline after the kill, because a command can close its output and keep running, or start a child in another session. On Windows the command runs in a job object instead ([what differs there](#what-differs-on-windows)) | A sleep past the timeout -> `inconclusive`, `timeout`, exit 6, earlier output kept; a spawned child is gone and never writes its file; two tests in `tests/unit/test_verify_runner.py` for the stopping conditions end-of-file cannot provide |
| TM-11 | An agent drives obelize | `obelize mcp` runs the commands as child processes with no input and the output captured, so the protocol's stream carries nothing else. Each tool argument is checked against a closed shape (a pack id obelize knows, a distribution, a module, a run id this session made, a number, a boolean) before it reaches a command line, so no flag, path or command can be passed and a file of the repository cannot be named as a pack. The child starts with `-P`, so a file of the repository cannot stand in for one of obelize's imports. No tool takes `--verify`, `--model`, `--accept-model`, `--allow-dirty` or `--trust-repo-config`: the last is given only by the person who starts the server. `apply` always runs with `--non-interactive --model none`, the trust the person gave covers the `.obelize.yml` the server started with and no edit of it, `--read-only` leaves out the tools that write source files, results are cut to about 200 KB, a fault of the server ends one call and not the session, and the code a tool quotes is redacted by the one redactor. What stays open: a verification command runs the repository's tests, which run code an agent can have edited | `tests/unit/test_mcp.py`: no tool property names a command, a path or a consent, every argument that could name a flag or a path is refused before a run folder exists, a repository's `typer.py` does not run, an edited configuration ends the trust, a forged run id is refused, a real server process writes only protocol to standard output, and the trust and refused flags are checked on the argv a tool builds; `tests/unit/test_undo_command.py` for a forged row in `.git/` |
| TM-12 | A hostile or tampered release, or index (`pack synth`) | A file is read only if the index gave its sha256, and the bytes are compared with it every time, cache included, so a poisoned cache entry or a swapped CDN file is refused (a compromised index that lies about both is what the user's choice of index covers). The archive is opened for `.py`, `.pyi` and four describing files only, each under a name checked for a parent directory, a drive letter, a backslash, a Windows device name and a case-folded twin, with a limit on one file, on the whole, on the count and on how much comes out of a compressed byte; a link or a device ends it. Nothing is built, installed or run, and no import is made: the API is read with griffe statically, in a child process started with `-P`, an environment of what Python needs, a memory and a time limit and a deadline, whose output is JSON read as data. A request goes to https (http only to this machine), follows a redirect only within one host, is read up to a size and a time, and carries a credential only to the index host; the cache is used only if others cannot write to it. A library's own words (a deprecation message) reach a pack only after control, format and surrogate characters are escaped and the text is cut, and the pack is data like any other (TM-1). `network` is refused in a repository's `.obelize.yml` | `tests/unit/test_archive.py` (parent directory, absolute and drive-letter names, links, devices, device names, case twins, bombs, size, count, damage); `tests/unit/test_net.py` (a redirect to another host, plain http, a credential to another host, a size and a time limit, a cache others can write); `tests/unit/test_index.py` (a file without a hash, a poisoned cache entry); `tests/unit/test_apidiff.py` (a read that takes too long, output that is no surface, an environment with a secret in it); `tests/unit/test_synth.py` (a message with an escape character, a tampered file, an index that is offline) |
| TM-13 | A coding agent edits the code (`upgrade --agent`) | The agent is the user's own program, started in an empty directory with every tool off, no session, no MCP server, no skill and none of the user's settings, with an allowlist of environment variables (names and prefixes, listed in [PRIVACY.md](PRIVACY.md#what-an-agent-run-sends)), and refused if it does not offer those restrictions. It is sent redacted lines around a place, as data, with the library's own words; its answer is a proposal that must pass the guard of TM-4 (inside what was sent, parses and compiles, no import or name beyond the question), is written only to a copy outside the repository, and is kept only if the repository's tests agree. The names a hint offers come from a release, which anyone can publish: they are identifiers cut to printable characters, sent as data with the rest. A test's error text, which the repository controls, is also data it is sent, redacted and cut; it may steer the agent, and the guard, the copy and the tests bound what that can do. A test that failed is never itself a place it may edit, and the repair rounds leave test files alone, but a flagged place in a test file is asked about like any other, and the commit message names every file the agent edited. It may also say that a place needs no edit, which writes nothing and which only the tests check; the evidence names each such place and the commit message the first five. It never reaches the working tree: `--agent` needs `--branch`, so a person reads the commit first, and the commit message names the files it edited. What stays open: the guard proves an edit safe to write, not correct, and the tests are the user's | `tests/unit/test_agent_cli.py` (the restrictions, the environment, every failure word); `tests/unit/test_resolve.py` (an accepted answer, a refused import, a model that proposes nothing, the question limit); `tests/unit/test_upgrade.py` (the move that lands on a branch, the one that stays unwritten, `--agent` without `--branch`) |
| TM-14 | A plugin runs with the user's rights | A plugin is code the user installed. Nothing is imported until the user allows its distribution and entry point in `~/.config/obelize/config.yml`; a repository's `.obelize.yml` may not set `plugins`, and a bundled pack never requires one. A pack names it by entry point and release range, the run records its release and the hash of its `RECORD`, an import error is named by its class and never its message, and its rewrites go through the same output gate, atomicity and undo as any rule's. What a plugin does beside editing is not contained | `tests/unit/test_plugins.py` |
| TM-15 | A maintained tool is a source of edits (`external_fixer`) | A pack names a fixer by an id from a closed registry in code (`ruff:NPY201`), and carries no command, flag, path or release. obelize finds the tool among the absolute entries of the user's `PATH`, so a repository cannot stand in for it, installs nothing, and starts it with an argv list and no shell, in an empty directory, with nine environment variables and no token (a `RUFF_*` setting of the user's cannot change what it prints), under a 60-second deadline and 4 MiB in and out (its output read no further than the limit, and the session or job it runs in ended with it, so a flood is stopped at the limit and a grandchild goes with the tool), and only a release the registry lists, written as `major.minor.patch` and read again when the file changes, since what a rule fixes changes between releases. The tool never reads a repository's configuration (`--isolated`). Its output is dropped unless it changed no line the scan did not report, none a rule of the pack wrote, added only imports, blank lines and comments beside a replaced line (and none whose name a function, class or comprehension of the file binds, which would make the call read a local), wrote no line wider than the pack's layout, changes nothing run on its own output, and the scan of it finds none of the names the fixer claims; what is kept then passes the parse, compile and unresolved-name gates, atomicity, the run folder (release, argv template, the hash of what the tool was given and what it printed, the lines changed) and undo. The tool itself runs with the user's rights and is not contained | `tests/unit/test_external_fixer.py`, `tests/unit/test_external_fixer_safety.py`; `tests/packs/test_all_packs.py` over the real ruff |
| TM-16 | A guide steers the model that reads it (`--guide`) | The page is fetched under the rules of the index (TM-12: https, a redirect only to the same scheme, host and port, a size and a time limit, a length that must hold, no credential, the host printed) and kept as text only: scripts, styles and navigation are dropped by tag, a code block is fenced, characters that do not print become a space, HTML is parsed in slices under a time limit and refused if it leaves more than 16 KiB open, and a marker in the text is removed until none is left, so the pieces of one cannot be joined into a live one by taking another out. A page is HTML by the type it was served with, a file by its suffix, and a file must be a regular file with a suffix of text or HTML. A guide over 400,000 characters is refused and not cut. The system prompt is fixed and says the text is data; the model is the user's own (an endpoint they set up, or their agent started as in TM-13, with every tool off) and a repository cannot choose it; `--offline` skips the guide, since asking a model reaches a host; nothing of the code of the repository goes with the text, so a page has nothing to ask for (`upgrade` names the dependency and the release it is pinned to, and nothing else from the manifests). The reply is read as one JSON object of claims in a closed shape, with no key twice and at most white space or one code fence around it, and anything else is refused whole. A claim is kept only if its quote is in the page, its names are in both releases, its pattern is one a pack may hold ([TM-1](#threats-mitigations-and-tests)), and the API diff does not contradict it. It becomes a report that quotes the page, and a rewrite only where the quote says in one of a few shapes that the new name takes the place of the old one, nothing in its sentence limits or takes that back, the diff shows the old name removed or deprecated and the new one there, not deprecated and written the same way (`async`, `staticmethod`, `classmethod`, `property`, `cached`), and for a pattern every call `after` writes resolves in the new release and fits. So a page can reach a report, or a rewrite of a name the library is dropping to a name the library has, by a sentence in a known shape that is false or misleading; it cannot reach a name outside the two releases, a call the new release does not take, or a file of the repository. The words of a report reach a pack escaped and cut. The model is not asked for the rest of a guide after two failures one after another or 30 minutes. The pack is data like any other, held to `pack test`, and made without the claims, under the id of a pack made with no guide, if it fails with them | `tests/unit/test_guide.py`, `tests/unit/test_net.py`, `tests/unit/test_claims.py`, `tests/unit/test_guided.py` (a page that gives orders, what a quote must say, every reason a claim is rejected) and `tests/unit/test_guided_pack.py` (the pack, the skip, the replay, a pack that fails with the claims, a page that says a name is async or no replacement) |
| TM-17 | A job that runs the repository's tests can write to it (`mode: upgrade`) | The action's upgrade mode is the half that runs code. It stops if the event is `pull_request_target`, `workflow_run` or `issue_comment`, if `GH_TOKEN`, `GITHUB_TOKEN` or `ACTIONS_ID_TOKEN_REQUEST_TOKEN` is set, or if the checkout kept a credential in its git configuration (`extraheader`, `includeIf`, `credential`: found by key and never printed); the documented workflow gives it `contents: read` and a checkout with `persist-credentials: false`, and it pushes nothing. The job is not without a token: the read-only `GITHUB_TOKEN` that `contents: read` gives is there, and the runner sets `ACTIONS_RUNTIME_TOKEN` for the artifact service, which is not refused. It leaves a git bundle, a patch and the trial's evidence in an artifact. The half that writes runs none of the repository's code. `action/upgrade.py publish` reads each folder of the artifact as data from a stranger. It takes only the folders of the dependencies the workflow asked for (a list the workflow holds once, not the artifact's) and at most twenty. It fetches only a bundle of one branch, named as the CLI names one, of one commit whose parent is the commit the workflow ran on, and uses only that commit's tree: the commit it pushes is made by the script on that parent, by the action's identity, with a message made from checked values, so the forged commit's message, headers and dates are never published. Every path the tree changes must be an edit of a regular file the base has (an added file, a deletion, a rename, a link, a submodule, a change of mode or an executable is refused), a Python source or a manifest obelize reads, in no `.git*` or `.obelize` path, of any case, and with no control, format or separator character, colon, backslash, backtick, name NFKC changes, short name or non-UTF-8 byte. The trial's list of paths is a consistency check, not a control. The pull request text is written before the push, a branch on the remote is never touched, and git runs with no hook and no force. What a hostile dependency can write into an existing source or manifest (a `setup.py`, a `conftest.py`), and the test counts and evidence the pull request quotes as the first job's claim, are left to the reader of the pull request | `tests/unit/test_action_upgrade.py` (forged bundles checked in a clone that lacks their objects, one for each refusal; a push to a bare remote; the CLI's own trial through a depth-1 clone), `tests/unit/test_action.py` (the steps, the pins and the example under zizmor) |

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
`.obelize/` and `runs/`. `latest` and `.obelize/.gitignore` are written the same way
as a verify or undo write: a link at `latest` is replaced and what it names is not written, and
the ignore file is written only where nothing, a link included, is at that name. `fix --apply`
tries to make a file in each directory it will write into before it writes any, so a directory
that takes none refuses the whole apply, where the write would have stopped partway. `.obelize.yml`
is read without following a link, and a relative `XDG_CONFIG_HOME` is ignored, since a user's own
configuration decides the model, the allowlist and the pack directories and a repository does not.
A file name with a control or format character, a backtick or a pipe is skipped, and its name is
spelled out and escaped wherever a report or a terminal shows it.

**On Windows** the same calls are made in
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
holds the message byte for byte. Each line of the context goes behind its number in the file and a
colon (`12: code`), added after redaction so a number cannot split a secret; a colon, because a
number a model copies into its replacement then cannot compile.

**Where it is sent:** `src/obelize/providers/openai_compat.py` departs four ways
from `urllib`'s defaults, which honour `http_proxy`/`https_proxy` and follow
redirects, either of which could carry the payload and the `Authorization`
header to a host the run never printed:
`ProxyHandler({})`; a redirect is refused (`endpoint_redirected`); no cookies;
no compression, so the 1 MiB response cap counts bytes on the wire. The URL is
`base_url` plus `/chat/completions`, never `urljoin`, which drops a trailing
`/v1`. Both are measured against a real local server, with `http_proxy` routed
to it so a request through the proxy would be recorded.

A `base_url` with a query string or fragment is refused, and so is plain `http://` to any host
but `localhost`, `127.0.0.0/8` and `::1` unless the user's config sets
`model.allow_insecure_http: true`: the key and the source would cross the network in the clear.

**What is written down** never holds the API key: it travels in a header, outside the recorded prompt
and its hash. The prompt is recorded only under `model.log_prompts`, because a
prompt is source code. An endpoint's own words are redacted *before* being cut
to length, so a gateway quoting back a rejected key cannot leak it.

**What is deliberately not redacted** is `patch.diff` and `snapshots/`: they
carry whole files ([PRIVACY.md](PRIVACY.md)). The corpus asserts the key is
absent from `model/` and **present** in the patch.

## TM-4 in detail

A model is asked only about `needs_review` rows in a file this run could write,
never a row the pack refused on purpose, and is sent one bounded range. It is asked only in a
run that uses one pack, so the imports a proposal may add are that pack's targets and no other's, and never about a pack whose one distribution holds both APIs, which writes a whole repository or none. A
proposal therefore answers a question naming one file, one line and one symbol.

**The order is part of the mitigation.** Only the first failed check is
recorded, so the checks run outward from "may we touch this file at all":
`../../.bashrc` is reported as an escape, not an unplanned file.

**Three checks come after the file and range checks.** The replaced range must
contain the asked line, because the sent range is a whole scope. The proposal
must quote the lines it replaces (`replaces`) and the quote must be what was
sent for those lines, ignoring trailing whitespace, line endings and blank
lines at the end, because a range that slipped one line still covers the asked
line and would delete its neighbour; a redaction that joined lines of the
context leaves no line number to trust, so nothing is accepted for it. The
replacement must encode in the file's encoding, because otherwise writing it
rewrites every line.

**A reply nested deeper than the stack is refused, not raised, up to a limit.** libcst's parser
overruns the C stack and kills the process on a very deep or long expression. `compile()` is asked
first and refuses most of them with an exception, but it takes a chain of about 13,000 `and` or
`or` terms on every version, and a long chain of any operator from Python 3.14. So the guard also
counts the tokens of the longest statement in the replacement and refuses more than 500 as
`replacement_too_large` before libcst sees it. A reply that passes both and still overruns the
stack in the tree walks is `output_does_not_parse` ([ADR-037](adr/ADR-037-proposal-validation.md)
D6, D11). The limit covers the replacement only: a file that already holds such an expression is
refused by the scanner's own depth limit ([CLI.md](CLI.md#what-a-selected-file-still-has-to-survive)).

**What it does not cover.** The guard proves an edit safe to apply, not
correct; `--accept-model` and a reviewer cover the rest. Nothing detects an
injected instruction: whatever the model was persuaded to answer must pass
every check.

## What a pack can get wrong without being hostile

TM-1 is about a pack that is hostile. A pack that is only mistaken fails another way: it writes an edit
that reads right and is wrong, or it reports nothing where it should report. The format keeps those
fail-closed, with one exception.

- A call is rewritten only with the keywords the pack lists (`keywords`), and its result is read only
  along the paths it lists (`result_paths`), as attributes or as string keys, which become the
  attributes. Anything else is refused (`unsupported_kwarg`,
  `response_shape_changed`), so a name the pack leaves out refuses more and writes nothing wrong. A
  name the pack lists wrongly is the open side, which `tests/packs/test_openai_facts.py` closes by
  reading each keyword from the new method's signature and each path from the result model.
- A shared module (`match.shared`) is the exception. Only the names `match.symbols` lists are legacy,
  so a legacy name the pack forgot is no finding: a repository that uses only that name scans clean
  and breaks. The mitigation is a frozen snapshot of the old release's names, which the suite holds
  equal to `match.symbols` plus a short list of names the new release keeps, and which a weekly job
  compares with the real old release. It covers the names the old release defined, and nothing
  about what the pack does with one it lists ([ADR-053](adr/ADR-053-shared-module-migrations.md) D2 and D8). The ways to reach the module with no name are rows too: a repository that fetches it
  by a string (`importlib.import_module("openai")`, `__import__`, `sys.modules`), reads its
  `__dict__` or star-imports it is withheld and not read clean (D14). A name another module of
  the repository re-exports is not seen ([KNOWN_ISSUES.md](KNOWN_ISSUES.md#the-openai-pack)).
- A pack that names its newest legacy release (`from.newest`, [ADR-056](adr/ADR-056-newest-legacy-release.md)) takes a declaration with no version as that release, which is a claim about an install nobody ran. A wrong claim writes a migration for a release the repository does not use, and the edit then reads right and fails when it runs. The gate asks for evidence of another release before it takes the claim: the code, a lock file, a constraints file or other requirements file that names another release, a resolver setting, a version written anywhere git lists, an environment kept in the repository, and it stops on the first. The run says what it took, `--verify` runs the repository's own tests on the result, and `undo` restores the bytes. What lives outside the repository is not read, on purpose, so that a finding is the same on every machine that scans the same files and the machine that scans is not taken for the one that installs: no `PIP_*` variable (`PIP_INDEX_URL`, `PIP_CONSTRAINT`, `PIP_FIND_LINKS`, `PIP_NO_INDEX`), no `pip.conf` in the home directory, no index, and not the environment the code runs in or a requirement another package brings in. These are listed in [KNOWN_ISSUES.md](KNOWN_ISSUES.md#the-pypdf2-pack). A pack whose claim lapses is the open side of this, and the weekly end-to-end run closes it: it fails when PyPI lists a newer final release than `newest`.
- A pack whose new library is its own distribution writes every file and the pin together or none, so the rules leave no mistaken half; a write that fails part-way (exit `5`) can, and `undo` restores every byte (ADR-053 D6). A pin the rule cannot write (extras, a URL)
  holds the repository when the scan plans it, and the model is never asked about such a pack, since
  its proposal is one row and is written after that rule has decided (ADR-053 D12 and D13).

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

2. Pattern-based. The following patterns are replaced wherever they appear, in this order:

```
AIza[0-9A-Za-z_-]{35}
sk-[A-Za-z0-9_-]{20,}
A[KS]IA[0-9A-Z]{16}
gh[pousr]_[A-Za-z0-9]{36,}
github_pat_[A-Za-z0-9_]{22,}
hf_[A-Za-z0-9]{30,}
xox[a-z]-[A-Za-z0-9-]{10,}
[sr]k_live_[A-Za-z0-9]{16,}
glpat-[A-Za-z0-9_.-]{20,}
pypi-[A-Za-z0-9_-]{40,}
eyJ(?:(?!eyJ)[A-Za-z0-9_-]){8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}
```

plus PEM private key blocks. Two more keep what labels the secret and replace the rest: a
`Bearer` token of 16 characters or more, and the password of a URL (`scheme://[user]:password@host`).
The last pattern is a quoted assignment, which keeps the setting's name:

```
(api[_-]?key|token|secret|passw(or)?d)\s*[:=]\s*['"][^'"]{8,}['"]
```

A shape other than a PEM block takes neither a quote nor a space, so the command line a run
records, which is redacted the same way, still splits into the arguments it had. When a match
crossed a quote, the record keeps the program and `[REDACTED]`.

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
  `refused[]` row, so it cannot read as one with nothing to do. A refusal
  the gate sees comes before any verification command starts; one a baseline
  command causes (a tracked file it changed) or a race comes after it.
- Writes are atomic: a temporary file plus a rename. Only files on the plan are
  written.
- Obelize never pushes and never merges. It creates a branch and a commit only for `upgrade --apply
  --branch`, with git's plumbing (`hash-object`, a temporary index, `write-tree`, `commit-tree`,
  `update-ref`): the working tree and the index are not read or written, no hook runs because hooks
  are looked for nowhere, nothing is signed, and a branch that exists is never moved.
- `obelize undo --run <id>` restores only files whose current hash equals the
  recorded after-hash. A hand-edited file is skipped and reported with both
  hashes and the path of its pre-migration copy; there is no `undo --force`.
  `tests/unit/test_undo_command.py` grades every way undo declines.
- What a run folder holds: [PRIVACY.md](PRIVACY.md).

## What differs on Windows

The guarantees are the ones above, made with the Windows calls that
[ADR-049](adr/ADR-049-platform-seam.md) describes. Where the outcome differs:

- TM-2: a junction is refused like a symbolic link, a file's mode is its read-only attribute and
  nothing more, and a OneDrive placeholder is read as the file it is.
- TM-5: git looks in the current directory for a DLL it finds neither beside itself nor in the
  system directories, and obelize runs git inside the repository, so a DLL placed there can be
  loaded. [ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md) accepts that, and a filter driver in
  the repository's `.git/config`, which a clone does not carry.
- TM-8: on a volume that reports no POSIX rename semantics, replacing a file that another program
  holds open can fail. No test makes that happen. A replace that fails refuses the file as
  `unreadable`, and obelize does not retry it.
- TM-9: obelize reads a command's output as UTF-8. A Windows program that writes UTF-16, or
  non-ASCII characters in an older code page, leaves a secret in a form the redactor does not
  match, and ADR-048 accepts that with the other redaction gaps.
- TM-10: a command and everything it starts run in a job object. The deadline terminates the job
  at once, and the job ends if obelize does, so the POSIX gaps in ADR-048 do not exist there. A process that a broker such as WMI, Task Scheduler or `docker` starts is outside the job
  and outlives the command. A command killed at the deadline exits with 3221225786, not a negative
  number.
- CI runs the suite on GitHub's `windows-latest` runner. A real console, a OneDrive folder and a
  path longer than 260 characters are not covered.

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
| TM-1 | Malicious pack | yes: the schema and the evidence | yes: two hundred and fifty-two negative packs, one per documented refusal, and the evidence |
| TM-2 | Path traversal / symlink escape | yes: reads and writes in the working tree and in a run folder | yes: both halves, and six forged run folders |
| TM-3 | Secret leaking to the model | partial: a repository cannot choose the endpoint or the credential; what is still open is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md#trust-and-redaction-gaps) | yes: the message byte for byte, the proxy and the redirect, and every invocation over `model/` |
| TM-4 | Prompt injection | yes: the guard, its seventeen words and its name allowlist | yes: twenty-four proposals and two fake adapters |
| TM-5 | Malicious verification command in CI | partial: the ladder and the mechanics, and a command a terminal would render as another is refused; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: twenty-four cases |
| TM-6 | Dependency installation | partial: only `upgrade --apply` installs, after a yes, into environments outside the repository and from a copy of it; what the build script of a package does as the user is not contained, and is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md#upgrading-a-dependency) | yes: a trial without `--yes` runs nothing, and a dirty tree is refused before any copy |
| TM-7 | Our own supply chain | partial: SHA-pinned actions and the hook commit, the dependency bound, the lock check, and a release that builds with a pinned backend and checks ci, its version, its tag and its changelog section before any upload; what a public repository still needs is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md#continuous-integration) | yes: the lock, the dependency bound, the action pins (zizmor), the hook pin and the release workflow's checks |
| TM-8 | Overwriting the user's work | partial: detection, refusal, record and undo from any directory, and a git that does not answer refuses; evidence precedes the write and undoes an interrupted apply; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: the refusal from the top and from a subdirectory, a git that does not answer, and twelve cases over the commands |
| TM-9 | Evidence leaking secrets | partial: the redactor and the cap; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: with its control |
| TM-10 | Runaway verification command | partial: the group kill and the three deadlines; the rest is accepted for 0.1.0 ([ADR-048](adr/ADR-048-accepted-gaps-in-0-1-0.md)) | yes: three shapes |
| TM-11 | An agent drives obelize | yes: closed argument shapes, no command, path or consent, the person's trust flag only, a captured child | yes: `tests/unit/test_mcp.py` |
| TM-12 | A hostile or tampered release, or index | yes: a hash from the index, source-only archives with limits, a static read in a limited child, one host; an index that lies about a file and its hash is not answered, and which index to trust is the user's to say | yes: archives, network, index, surface and pack tests |
| TM-13 | A coding agent edits the code | yes: the restrictions on the program, the guard, a copy, the tests and a branch to read; correctness is the tests' and the reader's, as for any model edit | yes: the agent, resolve and upgrade tests |
| TM-14 | A plugin runs with the user's rights | partial: the user's allowlist of a distribution and an entry point, the release range, the record, the gates on its rewrites; the plugin itself is trusted and not contained ([KNOWN_ISSUES.md](KNOWN_ISSUES.md#plugins)) | yes: `tests/unit/test_plugins.py` |
| TM-15 | A maintained tool is a source of edits | partial: the closed registry, the `PATH` of absolute entries, the cleaned environment, the empty directory, the deadline and sizes, the releases measured, and the proof every output is held to; the tool itself is trusted and not contained ([KNOWN_ISSUES.md](KNOWN_ISSUES.md#external-tools)) | yes: `tests/unit/test_external_fixer.py` |
| TM-16 | A guide steers the model that reads it | partial: the fixed prompt, the closed reply, the checks, a report by default and a rewrite only on a quote in a known shape that nothing in its sentence limits, with a diff that shows it; a page can still make a model say something true to the page that misleads, or write that sentence of a name for which it is false, and a rewrite the diff supports may not mean what the guide meant ([KNOWN_ISSUES.md](KNOWN_ISSUES.md#migration-guides)) | yes: `tests/unit/test_guided.py` and `tests/unit/test_guided_pack.py` |
| TM-17 | A job that runs the repository's tests can write to it | partial: the job that runs the tests has no credential that writes (the checkout is refused if it kept one) and the job that writes runs none of the code, takes only the dependencies the workflow named, and pushes a commit it made itself from a tree that edits existing sources and manifests; what a hostile dependency writes into such a file, and the counts it forges, are for the reader of the pull request ([KNOWN_ISSUES.md](KNOWN_ISSUES.md#continuous-integration)) | yes: forged bundles for each refusal, a push to a bare remote and a real trial |

Until the row for what you are about to do reads `yes`, run obelize only on a
repository you have committed or backed up.
