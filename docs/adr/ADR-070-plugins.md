# ADR-070: Plugins

## Status

Accepted.

## Decision

The kinds of rule are closed in the code, and ADR-006 says a pack carries no code. A library that
changes in a way none of them says (a call that must be rebuilt from three of its arguments and a
lookup) was either a flag or a change to this repository. A plugin is a third way: a kind of rule a
person installs from a distribution of their own, which a pack can then name.

### D1. A plugin is trusted code, so only its user can say it may run

A plugin runs in obelize's process with the user's rights and reads every file the run reads. It is
not a pack and no check of a pack makes it safe. So nothing is imported before the user has allowed
it, in their own `~/.config/obelize/config.yml`, under `plugins`, as a pair: a distribution and an
entry point it provides. A name alone would not do, since any dependency of the environment can
register one. A repository's `.obelize.yml` may not set `plugins`, a bundled pack never requires one,
and a pack of the user's own directories is held to the same rule as any other.

### D2. A pack names the plugin by its entry point and release

A pack that uses one lists it in `requires_plugins` (an entry point `name` and a PEP 440 `version` of
the distribution that provides it) and writes the change as `kind: plugin`, `plugin: <name>`,
`params: {...}`. The schema checks that the two agree, that none is listed for nothing and that none
is used unlisted. A run that cannot load a plugin the pack requires stops before any file is read,
with exit 7 and the reason: nothing provides it, none that does is allowed, the release is outside
the range, it did not import (named by the class of the error, never its message), or it does not
speak the interface.

### D3. The interface is small

`obelize.plugin` is what a plugin imports: `Params` (a closed pydantic model its `params` derive
from), `Rule`, `RuleContext`, `Edit`, `Finding`, `Tree`, `BailError` and `API`. An entry point names an
object with `api = 1`, a `params` model and a `rule(change_id, params)` method, which returns the same
kind of rule the kinds in this repository are. The params of each change are read by that model
when the plugin is loaded, so a mistyped key stops the run. Because a rule reads and writes libcst
nodes, the range of libcst that obelize installs is part of the interface; names in the module do not
change in 0.x without a line in the changelog.

A plugin is found with the working directory taken off the import path, which `python -m obelize`
puts first: a repository the person stands in could hold a distribution of the allowed name, or a
module of the allowed plugin's, and it would be found before the one installed. A run for every
known pack (none named) leaves out a pack whose plugin cannot run, and says so; a run for a pack
the person named stops.

### D4. What a run records

The run folder records, for each plugin a pack required, its entry point, distribution, release and
the sha256 of the bytes of the distribution's `RECORD` (which lists the hash of each file it
installed), so a run can be told apart from one with another build of the same release. A
distribution with no `RECORD` of its own, or one that cannot be read, leaves it `null`.

### D5. What stays the same

A plugin's rule reaches the repository through the same gates as any rule: what it writes parses and
binds no new name, a file with a refusal is left whole, and the run can be undone. What a plugin does
beside editing (reading files, starting programs, using the network) is not contained: obelize does
not sandbox it, and the user's allowing it is the only guard.

## Consequences

The pack schema, `docs/PACK_SPEC.md`, `docs/PLUGINS.md`, the JSON schemas, `docs/RUN_FOLDER.md` and
`docs/THREAT_MODEL.md` (TM-14) describe it.
