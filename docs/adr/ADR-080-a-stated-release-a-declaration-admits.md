# ADR-080: A stated release that a declaration admits

## Status

Accepted. Amends ADR-072 (D1's last paragraph).

## Decision

`obelize upgrade <distribution> --from <release>` stands for the legacy release in use where every
manifest declaration of the library admits it, and not only where none declares it. ADR-072 took the
person's word only for a library no manifest names, and left the other case "until a measurement
asks for it". The measurement did: of the 80 repositories of the 0.9.0 dry run, 18 stopped with
`legacy_version_unsupported` on a manifest that declares the library loosely (`pydantic`,
`pydantic<2`, `^1.9.1`, `pydantic>=1.8`) though the `--from` they were given lay inside the pack's
range.

### D1. What stands

The run is an `upgrade` that was given `--from`; a `fix`, a `scan`, a pack named with `--pack` and an
`upgrade` without the flag are gated as they were. The pack's `from.version` has a floor and covers
the release (`ScanSpec.legacy_range` contains it, a pre-release too), and the code uses the library.
Then the release is taken for the one in use when every declaration of the legacy distribution
admits it:

- A declaration admits a release when some alternative of its version set contains it. The set is
  read as `Declaration.spec` already is, so `^`, `~`, `||`, a bare version, `~=`, an epoch and a
  pre-release mean what the scan has always taken them to mean; a declaration that names no version
  admits every release.
- Every declaration counts: a second manifest, an included file, a constraints file, and a lock
  that is a requirements file (`requirements-lock.txt`). One that does not admit the release stops
  the run, whichever file it is in.
- A declaration nobody can read (a direct URL, an editable requirement, a version string no parser
  takes) does not admit it, since it may name another release; this is today's "cannot be read"
  stop with the release said beside it.
- An environment marker or extras change nothing: the version set is what is asked.

The pack's own inference (`from.newest`, `from.since`, ADR-056) still comes first where it lets a
declaration pass, and is what the run says it took. The person's word is taken where the declarations
would otherwise stop the run: when something in the repository contradicts that inference (a lock, a
constraints file, a resolver setting), a release the declarations admit stands instead.

### D2. What stops

A declaration that rules the release out stops the run with `legacy_version_unsupported`, and names
that declaration and says it rules the release out (`pydantic==2.5.0`, `pydantic>=2`,
`pydantic<1.5`), with what to do: admit the release, or name one it admits. This holds whatever the
declaration's floor. Before this decision a declaration that reached the pack's floor on its own
(`pydantic==2.5.0`) was not stopped and `--from` was not looked at, so a release and a pin that
contradict each other were planned as if the pin were the release; now they are a block. A release the
pack does not cover stops as it did, and the message says the migration does not cover it. No new
code joins the closed vocabulary.

### D3. The run says so

`Scan.stated` and `packs[].stated` stay set only where the statement decided something: the
declarations would have stopped the run, or there were none, and the release let it pass. A
declaration that passes the floor on its own and admits the release leaves them empty. Where a
manifest declares the library the summary and `REPORT.md` say "is declared with a range that admits
(release) and other releases, so this migration takes it as (release), the release `--from` names";
where none does, ADR-072's words. A block carries `covered`, which says that the pack covers the
release and a declaration is why it did not stand; `run.json` gains no field.

## Consequences

- A dry run over a repository whose manifest says `pydantic>=1.8` can now plan the move for a
  `--from 1.10.26`. It takes the person's word against the manifest's, and `pydantic>=1.8` installs
  a newer release today, so the word can be wrong. A dry run does not check it. `--apply` does: the
  trial installs the stated release itself over the repository's recipe in the first environment
  and compares each test that passes there with the release moved to. A wrong word shows as tests
  that do not pass on the stated release, which are no evidence, and a trial with none is
  `inconclusive` and writes nothing.
- The pin check is the one it was. A declaration that admits the release and others is rewritten by
  the pack's manifest rule as any declaration that reaches the pack's range is, and one that already
  pins the new range (`_arrived`) is left alone; the statement changes which run is planned, not
  how a pin is written.
- A lock file that is not a requirements file (`uv.lock`, `poetry.lock`, `Pipfile.lock`,
  `pdm.lock`) is not read, as it is not for a library no manifest declares, so a lock that holds
  the new release is not known to contradict the statement. The trial's environment is made from
  such a lock and then has the stated release installed over it.
- The decision does not change what is written once a plan exists, the `fix` and `scan` gates, a
  pack named with `--pack`, the Python gate, or a release the pack does not cover.
