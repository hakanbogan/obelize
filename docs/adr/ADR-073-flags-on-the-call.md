# ADR-073: Flags on the call

## Status

Accepted.

## Decision

A `flag_only` symbol is reported wherever it is used (ADR-018), and a pack made from two releases
flags a changed signature that way (ADR-063 D2). A signature change breaks a call that passes a
removed or renamed keyword, a positional argument at or past a removed place, a `*` or `**`
argument, or that leaves out a parameter that became required or whose default changed. Measured
over the public repositories of four migrations (pydantic 1 to 2, SQLAlchemy 1.4 to 2.0, urllib3 1
to 2, pandas 2 to 3), nearly every use of a name the pack flagged was reported, `sqlalchemy.Column`,
`Integer` and `String` among them, so a person read hundreds of rows to find the few that were
affected. A pack can now say which calls a flag is about, and the synthesis says it.

### D1. A shape per symbol, in `flag_only.params.calls`

`calls` maps a symbol of `symbols` to a shape: `keywords` (a call that passes one as a keyword),
`positional_from` (a call with more positional arguments than the index), and `omits` (names a call
must give, each by keyword or by the position its index says, `null` for a name only a keyword can
give). A call with a `*` or `**` argument matches any shape, since it can pass anything. A shape
names at least one of the three, sorted. It is data and closed: no pattern, no expression. A new kind
of change would have put one surface in two changes, which a pack may not do, and a field of
`ScanSpec` alone would have had no pack to write it.

`calls` is optional, and a symbol with no entry is flagged wherever it is used, so the packs that
exist read as they did. `ScanSpec.flag_only_calls` holds the shapes beside `flag_only_symbols`,
which still lists every flagged symbol, and `spec_digest` leaves the field out while it is empty:
the digest of each bundled pack is what it was. A shape for a symbol that `from.lacks` or
`from.since` lists, or sits under, is refused, because the scan reads those off its findings and a
call a shape passes over is none.

### D2. What the scan does with a symbol that has a shape

The shape decides for the symbol it is written for, when the pack flags no name above it whole:

- A call that matches is flagged (`flag_only_surface`), and says what matched in `Finding.evidence`.
- A call that matches none is the API as it was, and so is a name that is not called and is imported,
  annotated (a quoted annotation too) or handed to a call as an argument (`Column(Integer)`,
  `map(pd.to_datetime, rows)`, `isinstance(x, Series)`). Neither is a finding in a shared module. In a
  module that is not shared each is graded as if the symbol were not flagged, and the pack's other
  rules claim it. The code that receives a handed name may call it with anything, which the scan
  cannot follow, so the pack's `limitations` say it.
- Every other use is a finding as before: a class named as a base (its `__init__` runs through
  `super()`), a name assigned to another, a decorator, a default value, a name in a list, a name
  inside the symbol (`Column.something`), an import inside a function, a `mock.patch` target. When in
  doubt the use stays flagged.
- A method read off a receiver the scan types (`rename_member`'s reading) is flagged as before.
  Its call would have to be handed to the rule, and the synthesis writes no shape for a method (D3).

### D3. The synthesis writes the shape from the changes of one path

For a function or a class that is not a member of a class, each parameter change gives a part, from
where the old release has the parameter, and the parts of a path are joined:

| Change | Part |
|---|---|
| parameter removed | its keyword (none if positional-only); `positional_from` its index if a call can give it by position |
| parameter renamed | the old keyword |
| kind changed to keyword-only | `positional_from` its index |
| kind changed to positional-only | its keyword |
| default changed, or became required | `omits`: its name, by its index if a call can give it by position |
| required parameter added | `omits`: its name, by keyword only |

A required parameter that is new is `omits` by keyword only: one inserted before others moves what a
positional argument means, and a call that gives it by position cannot be told from a call that
shifted. A path that has any other change (removed, moved, deprecated, bases, kind), a kind change
the calls do not show, or a name that is not ASCII stays flagged wherever it is used, as before. So
does a member of a class: a call can pass its object by hand (`Class.method(obj, ...)`, which moves
every index by one), and the scan types a receiver only for the classes a pack renames members of.

Messages are unchanged: a path's own words, grouped by identical words, folded past 60 groups. A
folded group no longer hides the parameter, since each call says it in `evidence`. The pack's
fixtures show both sides: the positive one calls each shaped name with what changed, and the negative
one calls it with none of it, which `pack test` scans and must find nothing in. `limitations` says
what D2 leaves out.

### D4. `Finding.evidence` is a closed word and what it takes

`evidence` was always `null`. It is now `null` or one of `keyword <name>`, `omitted <name>`,
`position <index>` and `spread`, the words of SCAN_VOCABULARY §14 and the name or index that a pack
gave (an identifier, never text from the source or a message). `Finding` refuses anything else, so a
source excerpt still cannot get into a finding. The terminal table and `REPORT.md` print it beside
the code that withheld the row.

## Consequences

- A repository is told of fewer places where a library's changes are to parameters, and each says
  why. Where they are not, nothing changes: a class whose bases changed (`sqlalchemy.Column`,
  `Integer`, `String`), a function that changed kind (`relationship`, `select`) and a path that is
  also deprecated (`pandas.read_csv`, `pandas.Series`, whose library warns of one parameter in the
  body) stay whole, as does every method. A default that changed to a name that means "not given"
  (`lib.no_default`) is a default that changed, since `_SENTINEL` does not know it. A name used any way
  D2 does not clear is a finding.
- A message may name more parameters than the call passes: a path's changes are one message, and the
  call's own `evidence` names the one that matched.
- A shape finds a call by what it passes, so a change the signatures do not show is still not seen
  (a parameter reordered, a different default behind the same name). The limitation of ADR-063 D4
  stands.
- `pack.schema.json` gains `calls`, the findings schemas gain nothing (the field is a string), and
  `ScanSpec.flag_only_calls` is not published. The formats stay unstable through 0.x
  ([ADR-048](ADR-048-accepted-gaps-in-0-1-0.md)).
