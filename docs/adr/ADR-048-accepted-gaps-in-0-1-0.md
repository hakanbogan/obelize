# ADR-048: Accepted gaps in 0.1.0

## Status

Accepted.

## Decision

The release gate in ROADMAP.md holds `v0.1.0` until TM-2, TM-5, TM-8, TM-9 and
TM-10 read `yes`. TM-2 does. For the other four I accept these gaps in 0.1.0
instead of holding the release for them:

- TM-5: a git call obelize makes can run a program the repository configured,
  such as `core.fsmonitor`, and on Windows can load a DLL placed in the
  repository that git finds neither beside itself nor in the system
  directories.
- TM-8: running `obelize verify` again on a run, or `obelize undo` twice, can
  overwrite the record of the earlier attempt.
- TM-9: the redactor misses common credential shapes, the recorded argv is not
  redacted, and a key can reach a traceback.
- TM-10: on POSIX, Ctrl-C leaves the command's process group running, a member
  that ignores `SIGTERM` outlives a leader that obeys it, and a member that has
  closed its output outlives the command's exit. On Windows, where the command
  runs in a job object instead, a process it has a broker start, such as WMI,
  Task Scheduler, a COM server, `runas`, `wsl` or `docker`, is outside the job
  and outlives it.

[THREAT_MODEL.md](../THREAT_MODEL.md) states each one, and the README tells
users to run obelize on a repository that is committed or backed up and to pass
only verification commands they trust.

Formats stay unstable through 0.x. The CLI surface, the exit codes,
`.obelize.yml`, migration packs, the run folder and its JSON Schemas carry no
format version; any 0.x release may change any of them, and `CHANGELOG.md`
lists each change in the release that makes it.

## Consequences

- `v0.1.0` ships with TM-5, TM-8, TM-9 and TM-10 reading `partial`.
- Anyone who scripts against a format reads the changelog before upgrading.
