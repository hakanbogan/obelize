# ADR-030: Flagged surfaces and dependency line

## Status

Accepted; amended by ADR-053.

## Decision

### D1. `flag_only` produces an edit, and the edit's whole content is `rule_id`

A `flag_only` rule claims the rows the scan withheld under `flag_only_surface` or
`attribute_removed`, writes nothing, and returns one `Edit` per claimed row carrying the change's
id, the only link from a report line to the pack's `message` and `suggestion`. `ScanSpec` keeps
only the union of refused surfaces, because prose in it would invalidate ADR-005's findings cache
whenever a sentence was reworded.

### D2. Three channels, and the finding's own `kind` decides which one is asking

- `symbols` matches the resolved qualified name by prefix at a dot, as `analysis._grade` does:
  `google.generativeai.protos` claims `google.generativeai.protos.Schema`.
- `attributes` matches whole.
- `patterns` matches the confidence reason, and only on a `dynamic` or `text_mention` finding.

A resolved name is never `dynamic` or `text_mention`, so the channels are disjoint and no row (a
`mock.patch` target naming a refused symbol, say) is claimed, or reported, twice.

### D3. The status is read off the finding, never re-derived

The rule reports `finding.scan_status` (`attribute_removed` is `unsupported`, `flag_only_surface`
is `needs_review`), narrowed to the statuses an edit may carry, because a second mapping would
drift from `analysis._grade`.

### D4. A manifest rule is not a `Rule`, and the registry has two tables

`manifest_dependency` implements `ManifestRule`, a second protocol over the repository-wide verdict
and one manifest's lines, registered in `registry.MANIFEST_RULES`, because a manifest has no libcst
module, `ImpactPlan` or import manager for `Rule.apply`. `registry.IMPLEMENTED` is the union of both
tables and equals `CHANGE_KINDS`. `rule_for` answers `None` for the manifest kind and
`manifest_rule_for` for every other kind, so a driver cannot hand either rule the other's input.

### D5. Manifest rule order carries nothing, and is stated so it cannot acquire any

`manifest_rules()` run in the pack's order for the reader's sake only: a manifest rule reads the
repository-wide verdict and one file's bytes, and no other manifest rule writes either. The order
between the two tables is ADR-031 D1's.

### D6. One edit shape, two placements, five layouts

A declaration is two spans, the distribution (`column` to `end`) and the version (`pin`). The new
declaration is the legacy line with both swapped:

```
line[:column] + to_name + line[end:pin[0]] + to_spec + line[pin[1]:]
```

Applied in place it is the replacement; written as a new line below, the insertion. The rule names
no layout: everything outside the two spans (indent, quotes, trailing comma, a trailing comment, an
environment marker) is the author's and is kept. Per F-2, an `eligible` row naming the legacy
distribution is a replacement, and one at the same address naming the new distribution is an
insertion. The insertion goes below, so the legacy pin keeps the line number every report names.

### D7. One code for what the rule will not write, and it names a shape

`manifest_pin_shape_unsupported` (`needs_review`; fix time, and the scan for a pack whose one
distribution holds both APIs, [ADR-053](ADR-053-shared-module-migrations.md) D12) covers a line that says more than
this distribution at this version: extras, a direct URL, a table value that is not one version
string; and, for an insertion only, a line that also carries the array's or field's key or a second
declaration, which a copy would duplicate. One code, because the reader does the same thing in every
case; the scan still reports every such row. It has no rung in the bail ladder: like
`manifest_code_mismatch` it names one declaration and cannot fire on a row another code could.

### D8. The extent lives in the reader

`scan/manifests.py`'s `Declaration` carries `end` and `pin` beside `column` (ADR-021 D8), because
the reader knows the five layouts (requirements files, PEP 621 and Poetry `pyproject.toml`,
`Pipfile`, `setup.cfg`, `setup.py`), so the extent it records and the extent an edit uses cannot
disagree. `pin` is `None` when the declaration is not a plain pin: found, with nothing to write into.

### D9. An answer key is a promise about manifests too

`tests/fixtures/scan/basic/` carries `requirements.after.txt`, and `tests/oracle/harness.yaml`'s
shared exclusion is `**/*.after.*`, so a key is not read as a second declaration.
`examples/gemini-legacy-app` has no key, because a real `obelize scan` of it has no harness
exclusion and would report one as `manifest_code_mismatch`; its expected bytes live in the oracle
test.

### D10. A `not_a_usage` manifest row is not an edit

A legacy pin in a repository where nothing migrated and nothing imports the distribution gets no
edit: removing it would tidy a manifest on the strength of a migration this run did not make, and no
`Edit` status could carry it.

## Consequences

- `REPORT.md` prints each edit's `rule_id`; printing the pack's `message` and `suggestion` beside it
  is still open.
- Two of the pack's four `attributes` are reported only as a class read, never on a `get_model` or
  `list_models` result (`tests/fixtures/scan/COVERAGE.md` gap 22).
- An inline dependency array is read and not written (gap 23).
- A repository that does not migrate whole in one run keeps both pins; no rule later removes the
  legacy one.
