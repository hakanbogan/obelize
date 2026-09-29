# ADR-031: The codemod driver

## Status

Accepted.

## Decision

### D1. The order is stated here, and it is two orders

Within a file the rules run in `registry.rules(pack)` order, the pack's declaration order, and that
order is a dependency: `rename_import` reserves the names, `configure_to_client` spells `Client(...)`
against the alias it bound, `generative_model_calls` reads both, and its chat half reads its model
half's output. A pack that inverts it refuses the file with `alias_collision` rather than writing a
wrong one, so rules declare no dependencies. Across tables: every `Rule` over every parsed file,
then F-2's survey of the plans they leave, then every `ManifestRule`, because the last reads what
the first decided.

### D2. F-1 is one function with two callers, and the driver brings it rows

`impact.planner.atomicity(findings, policy)` is public and serves the planner and the driver. It
takes no extra causes, because `caused_by` is exactly the bails the other findings carry (ADR-012),
so the driver first puts each fix-time code on its row: a rule's withheld `Edit` goes to the row that
rule claims on that line (never ambiguous, since ADR-030 D2 lets no row have two claimants), and an
unclaimed row gets D3's code. A rule's refusal is folded in only over rows the scan graded
`eligible`, so `flag_only`'s edits never demote an `unsupported` row or drop its neighbours'
`caused_by`.

### D3. `usage_unmapped`: the code for a row every rule declined

An `eligible` row no rule claims is withheld as `usage_unmapped`: a legacy free function referenced
and not called, or a `methods` entry with no `rewrites`. It is the row's own code, so the rows that
were ready name it in `caused_by`, and its `Edit` carries no `rule_id` because no rule produced it.
One code for every shape, because the reader does the same thing: this pack does not migrate this
usage.

### D4. The output gate is `parse.gates` again, and nothing new

The driver asks `parse.gates` of the bytes it produced (libcst parses them, `compile()` accepts
them) and withholds the file on every row as `output_does_not_parse` when it fails. The gate is
asked only of a file the run would write and whose bytes changed. The round-trip gate has no output
counterpart: the output is libcst's own serialisation, so nothing can make it fire. `ReadRefusal`
stays at three members, because a refused rewrite is an `Edit`, not an unreadable file.

### D5. Neither new code gets a rung on the merged ladder, for two reasons

`impact.planner.LADDER` orders scan-time codes on one row. `usage_unmapped` is a fix-time code, like
section 4's call-rewrite bails. `output_does_not_parse` is asked only of a file where nothing else
fired, so a rung would never have anything to displace; section 6's rung-2 row still says where it
sits. D10's and D11's codes stay out of `LADDER` for the same reasons (`codemod.BAILS`).

### D6. The `dual` import policy is refused, because no *rule* implements it

Under `dual` the planner withholds nothing for atomicity, but no rule leaves both imports in place,
so a run would rename the import and leave the refused group calling a module that is gone. The
driver raises `CodemodError` rather than treating `dual` as `atomic`, because a silently ignored
policy makes a measurement mean something else. `dual` stays a scan-time parameter until a rule
implements it.

### D7. A run is bytes in memory, and a `Run` is what a caller may refuse

`codemod.run` writes nothing: it is a pure function of the scan, the bytes and the pack. So the
oracle grades whole repositories without a write, and `obelize fix`'s default dry run is the apply's
code path minus the write. `Outcome.after` is the input for every file the run does not write,
including one F-1 refused after its rules produced good bytes and one whose parse does not reproduce
its own bytes (ADR-017's round-trip gate, asked again), so writing `after` unconditionally is right.

### D8. The driver takes one mapping of bytes, and refuses two ways of getting it wrong

`sources` maps each scanned path to its bytes, manifests included, partitioned with
`manifests.is_manifest`, the walker's own predicate. A scanned file absent from it is left alone,
which is how a caller migrates part of a repository. `CodemodError` refuses a file with an
`eligible` row and no bytes, which F-2 would report migrated while nothing was written, and a path
no scan looked at, which has no plan.

### D9. The corpus is four repositories, and the two measurements are not in it

`tests/fixtures/transforms/codemod/` holds one small repository per shape of a run, because a run's
unit is a repository; `clear/` and `blocked/` scan identically and write two different manifests.
The acceptance measurements are outside it: one driver call reproduces `tests/fixtures/scan/basic/`'s
two hand-written keys byte for byte, and `examples/gemini-legacy-app/`, with its own `.obelize.yml`,
is withheld whole: two of its modules run on `summarizer/config.py`'s `configure` (D11), so a run
writes nothing and the manifest keeps its legacy pin.

### D10. A second output gate: every name the output reads is bound

Bytes that pass D4's gate are asked, through libcst's scope analysis, which names they read that
nothing binds, builtins aside. A name unbound in the output and not in the input was introduced by a
rule, and the file is withheld as `output_names_unresolved` on every row; comparing with the input
lets a module that already reads such a name (a star import's) migrate. Hand-written keys meet no
gate, so `tests/oracle/test_written_names_resolve.py` puts every `complete: true` key, and the
codemod oracle everything it writes, through ruff's F821, F811, F823 and TC004.

### D11. A `configure` another module runs on is not deleted

`configure` sets a process-wide default. If, after every file has been through the rules, any
module with no `configure` of its own stays on the legacy SDK (a row that imports it is withheld),
every file whose `configure` the run would rewrite is left as it was: `configure_consumed_elsewhere`
on the `configure`, F-1 naming it on every other row. It is asked of the run's plans, because a rule
can leave on legacy a module the scan graded `eligible` (`tests/fixtures/scan/COVERAGE.md` gap 21).
One reliant module holds them all, since which `configure` runs first is decided at run time; a
`mock.patch` target is not reliance.

## Consequences

- Finding 7: a file the scan already refused produces findings and no `Edit`, because every rule
  skips rows that are not `eligible`; its report is its findings (ADR-034 D10).
- D10 cannot see a name bound to the wrong thing or bound only on some paths.
- A run keeps every produced byte in memory until the caller decides; no repository too large for
  that has been measured.
