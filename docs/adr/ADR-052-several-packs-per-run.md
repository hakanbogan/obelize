# ADR-052: Several packs per run

## Status

Accepted; amended by ADR-053.

## Decision

A run may use several packs. The single-pack pipeline stays as it is and runs once per pack, in
id order, over what the packs before it wrote; one gate, journal, write, verification, report and
`undo` serve all of them.

### D1. Packs come from the wheel, the user's directories and `--pack`

`pack_dirs` in `~/.config/obelize/config.yml` adds directories laid out like the wheel's
(`<provider>/<slug>/pack.yaml`); `--pack <path>` names a file. A repository's `.obelize.yml` may not
name a directory, for the reason it may not name a model: a pack decides what is written and which
imports a model may add (B1, TM-1). An id in two places is refused (`loader.known`), and a pack
loaded by id must carry that id.

### D2. Without `--pack`, every pack the repository uses runs

Every known pack is scanned over one read; one with a finding that is not `not_a_usage` is chosen.
`--pack` is repeatable and names exactly the packs that run. None chosen is not a failure: the run
says which packs it checked, writes a run folder with `packs: []`, and exits `0`.

### D3. Two packs that could feed each other are refused

`loader.conflict`: legacy modules that overlap, one pack writing a module the other migrates, or one
distribution named by both (`from`, `to` or `transitive`). Without those neither can see the other's
output through a module, so the order between packs breaks ties and decides nothing else. Exit `2`.

### D4. Each pack's turn is the single-pack run

A pack is scanned again only when an earlier one wrote a file it has a finding in, since the lines
have moved. File atomicity (F-1) and the manifest verdict (F-2) are each pack's own: one pack can
leave a file as it was while another writes it. `codemod.chained` joins the turns: a file keeps
the first `before` and the last `after`, an edit's `rule_id` is `<pack id>:<rule id>`, and its
`line` is in the file as its pack saw it. `setup.py` is read as a source and as a manifest, so the
passes of one or several packs can return it twice; `chained` joins every return of a path into one
outcome from its first bytes to its last, whichever list a pass put it in.

### D5. A blocked pack is withheld alone

A pack the repository rules out (ADR-050 D4, D5) has every eligible row withheld for its
reason by `codemod.blocked` and plans nothing; the other packs run. `packs[].blocked` in `run.json`
carries the reason, and the withheld rows make the exit `4`, so a run that wrote for one pack and
stopped for another does not read as finished.

### D6. A model is asked about one pack

The guard authorises the imports of one pack's targets (TM-4), so `--model` and `--accept-model`
with several packs exit `2`, as does `--show-context`; a model only the user's file configures is skipped, with a line on stderr. A pack that is its
own target ([ADR-053](ADR-053-shared-module-migrations.md) D13) is never asked about either, since
a proposal is one row and the pack writes a whole repository or none: `--model`, `--accept-model`
and `--show-context` with one exit `2`, and a configured model is skipped with a line on stderr.

### D7. The evidence says which packs

`findings.json`, `plan.json` and `run.json` carry `packs[]`, ordered by id; `run.json`'s
`blocked` moves into each row. A pack's bytes and hash are copied to
`packs/<provider>/<slug>/`. A pack id has no dot, so the path cannot leave the folder.

### D8. The repository is read once

`runner.read` walks and reads every selected path once into a `Tree`, keeping the bytes only where a
pack's prefilter token or a module only the legacy distribution installs occurs. Every read of a
scan goes through `Tree.contents`, and `fix` no longer reads the files a second time between the
scan and the plan.

## Consequences

- Every document and the run folder's layout change; CHANGELOG lists it (ADR-048).
- A pack scanned again after an earlier pack wrote costs a second pass over its own candidates;
  `bench/crossover.py` is where to measure it if a repository makes it matter.
- Two packs sharing a target distribution are refused together until a pack needs it.
