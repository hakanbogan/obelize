# ADR-063: Synthesized packs

## Status

Accepted.

## Decision

A library that has no pack can have one made from the public API of two of its releases. The pack is
data like any other and is held to the same checks; it differs in where its facts come from, and in
how little it claims. Each decision is numbered as it lands.

### D1. `pack synth` compares two releases and writes a pack

`obelize pack synth <distribution> --from <version> [--to <version>]` asks the package index for the
project (ADR-062), downloads the two releases and the newest final release between them, reads what
each exports, and writes `<provider>/<from>-to-<to>/` with `pack.yaml`, `SOURCES.md` and fixtures.
`--to` defaults to the newest release that is neither withdrawn nor a pre-release. The module
compared is the one both releases have, the one named like the library, or the one `--module` names.
A pack for a migration to another distribution is not made: the two sides would share no module, and
`pack new` is the tool for it.

### D2. A change is a rename, a move, a flag, or the dependency line

A name that left the API is renamed in place (`rename_symbol`, `renamed`) only when the library's own
deprecation message, in the release before the removal, says to use one name beside it that exists
in the newer release; it is moved up out of a submodule (`rename_symbol`, `symbols`) only when it kept
its name and signature, has a body, and the old release already exported it from the place that is
gone or no other name can be it. `calls: allowed` is written only for a name that kept its signature,
which is the claim the field makes. Every other change is a `flag_only` change in one of four
groups, removed, moved elsewhere, a changed signature and deprecated, whose message is the
library's own where it gave one and a plain statement where it did not. A pack never rewrites a
call it cannot show takes the arguments it took. The dependency line moves from the old release to
`>=<to>,<next major>` with `manifest_dependency`. The pack is `shared`, since it is one distribution.

A name under a flagged class is reported as the class, because two changes may not flag one
surface and the class's constructor is the usage the scan finds. A rename that would land on a name
the pack flags is flagged instead. More than sixty groups of one kind are folded into one that says
less.

### D3. The pack proves itself before it is kept

The fixtures are written from the comparison: one module that uses each renamed name the way a
reader finds it, one that uses each flagged name, one of code already on the new release, and the
two dependency files. The `.after` files are what the rules write into them. The pack is loaded,
checked with the checks of `pack test`, and the rename fixtures must equal the old spellings read as
the new, written independently of the rules. A pack that fails is removed and the command exits `1`,
because the fault is obelize's.

### D4. `api_diff` is a source type, and is never bundled

`source.type` gains `api_diff`: the pack cites the file of the newer release, with its sha256, and
`limitations` always says that a change in what a function does is not in it. A bundled pack is never
`api_diff` (tested), so the three packs that ship stay the reviewed ones.

### D5. The index is the user's to name

`~/.config/obelize/config.yml` holds `network.index` and `network.offline`; `OBELIZE_INDEX_URL`,
`OBELIZE_INDEX_AUTHORIZATION` and `OBELIZE_OFFLINE` do the same for one run. A repository's
`.obelize.yml` may not set any: the index decides which code obelize reads. `--offline` reaches no
host and uses the cache. Exit `6` is an index that could not be reached or answered, `2` a request
the index cannot meet, `1` a pack obelize made that fails its own checks.

## Consequences

`docs/CLI.md` documents the command, the user settings and the exit codes; `docs/PACK_SPEC.md` the
source type; `docs/PRIVACY.md` and `docs/THREAT_MODEL.md` the hosts, the cache and the boundary.
The synthesized pack finds usage reachable through the module; a method on an object whose class the
scan cannot tell stays unfound, as for any pack.
