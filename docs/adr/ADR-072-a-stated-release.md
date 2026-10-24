# ADR-072: A stated release

## Status

Accepted.

## Decision

`obelize upgrade <distribution> --from <release>` says which release the code is written for. The
manifests are how the legacy version gate (ADR-050 D5) learns which release is in use, and a
repository that declares none was stopped (`legacy_version_unsupported`), so a plan made from two
releases could never be shown for it. The person's own statement now stands in for the missing
declaration, and in no other case.

### D1. It counts only where no manifest declares the library

The gate asks every declaration of the legacy distribution, as before. When it finds none, the run
is not blocked if all of these hold:

- the run is an `upgrade` that was given `--from`; a `fix`, a `scan`, a pack named with `--pack` and
  an `upgrade` without the flag are gated as they were;
- the pack's `from.version` has a floor, and covers the release (`ScanSpec.legacy_range` contains it,
  a pre-release too);
- the code uses the library (a repository that does not is not blocked, as before); and
- nothing else blocks the run (the Python, a pin of the new distribution).

A declaration that exists is judged as it is, and the release does not overrule it: `pydantic>=1.8`
admits releases below the floor, so it blocks though `--from` names one above. The block says that
`--from` names a release and counts only where no manifest declares the distribution
(`Blocked.stated`). A release outside the pack's range blocks as an undeclared distribution does, and
the message says that the migration does not cover it.

### D2. The value comes from the command line and nowhere else

`upgrade` hands the pair (distribution, release) to the run (`commands.fix.Request.stated`), and the
scan receives the release for the pack whose legacy distribution it names. No pack, no `.obelize.yml`
and no environment variable can set it, and `ScanSpec` does not hold it, so `spec_digest` does not
move. The trial's copy is given the same pair, or its own run of the rules would be stopped where the
dry run was not.

### D3. The run says so

`Scan.stated` holds the (distribution, release) pair only when the statement decided something: the
code uses the library, no manifest declares it, nothing blocked. `packs[].stated` in `run.json` is
that release and is `null` otherwise. It is not `packs[].assumed` (ADR-056), which is what a pack
claims about a declaration that names no release: the person's word and the pack's claim are two
provenances and a reader has to tell them apart. The terminal and `REPORT.md` say that no manifest
declares the distribution and that the migration takes it as the release `--from` names.

## Consequences

- A dry run over a repository that never names the library can now show a plan. It takes the
  person's word for the release; only `--apply` checks it, since the trial installs that release in
  the first environment and runs the tests on it (ADR-065).
- A declaration that is looser than the floor still stops the plan. The alternative, that a
  statement the declaration admits decides, would plan a repository whose manifest installs a newer
  release today as the one named, on the person's word against the manifest's; it is left out until
  a measurement asks for it.
- `run.json` gains `packs[].stated`; the formats stay unstable through 0.x
  ([ADR-048](ADR-048-accepted-gaps-in-0-1-0.md)).
