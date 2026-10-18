# Safety

`scan`, and `fix` without `--apply`, change none of your files. obelize never commits, branches,
pushes or merges, and it refuses to apply over uncommitted changes unless you pass
`--allow-dirty`, so `git diff` shows the migration alone. In the repository it writes only its own
`.obelize/` folder and the files on its plan. Each file on the plan goes through a temporary file
and a rename, and it follows no symbolic link.

It runs the verification commands you pass with `--verify` or allow in your own configuration. A
command from the repository's `.obelize.yml` runs only once you approve it at a prompt, and in CI
only if your allowlist holds it or you pass `--trust-repo-config`. A command that runs past your
timeout is stopped, and its output is redacted before it is recorded. There is no telemetry, and no
network access unless you configure a model in your own `~/.config/obelize/config.yml` or with
`--model`, or run `pack synth`, which reads two releases of a library from the package index
without installing or running anything. `upgrade --apply` is the one command that installs: it
asks first, does it in a copy of the repository with environments outside it, and writes the move
only if the tests agree.

## Before you run it

Run obelize in a repository that is committed or backed up, and pass only verification commands you
trust. A migration pack is untrusted data: obelize parses it with a closed schema and never
executes it.

## Known gaps

These gaps are known:

- obelize turns `core.fsmonitor` off for its own git calls and keeps `git status` from refreshing a
  stale index, which would run a `post-index-change` hook. A repository's `.git/config` can still
  name a filter driver that a git command starts. A clone does not carry that file, so it takes a
  repository you already trust. On Windows git can also load a DLL from the repository that it
  finds neither beside itself nor in the system directories.
- Running `obelize verify` again on a run, or `obelize undo` twice, can overwrite the record of the
  earlier attempt.
- Redaction knows the credential shapes [the threat model](THREAT_MODEL.md#secret-redaction) lists
  and no others, and a key can reach a traceback from the model adapter. obelize reads a command's
  output as UTF-8, so a secret that a Windows program writes as UTF-16, or with non-ASCII
  characters in an older code page, is not redacted. Read a run folder before you share it.
- On Linux and macOS, Ctrl-C stops the verification command, but killing obelize itself with
  `SIGTERM` or `SIGHUP` leaves it running, as does a process it started in a session of its own.
- On Windows the verification command runs in a job object that ends with it, but a process that
  WMI, Task Scheduler or `docker` starts on its behalf is outside the job and outlives it.

[THREAT_MODEL.md](THREAT_MODEL.md) has the details, and [PRIVACY.md](PRIVACY.md) lists what a run
folder holds. To report a vulnerability, follow [SECURITY.md](../SECURITY.md).
