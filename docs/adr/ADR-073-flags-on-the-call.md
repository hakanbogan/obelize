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
`positional_from` (a call with more positional arguments than the index), `omits` (names a call
must give, each by keyword or by the position its index says, `null` for a name only a keyword can
give) and `bases` (the class's bases changed, which no call passes). A call with a `*` or `**`
argument matches any shape that names a keyword, a position or a name, since it can pass any of them.
A shape names at least one of the four, sorted. It is data and closed: no pattern, no expression. A new kind
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
- A class whose bases changed is no finding at any call, a `*` or `**` one included: construction is
  what it was, and a use by name cannot see what the class derives from. What a changed base breaks
  is code that derives from the class (`class X(Column)`, which reaches the class through
  `super()`), so that stays a finding, with every other use this list keeps. A class with a shape of
  parameters as well is judged at its calls by the shape.
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
| bases changed | `bases` |
| deprecated, its message naming a parameter of the path that changed | the part of removing that parameter, so a call that passes it is one |

A required parameter that is new is `omits` by keyword only: one inserted before others moves what a
positional argument means, and a call that gives it by position cannot be told from a call that
shifted.

A deprecation is read as being about a parameter when its message holds, as a whole word, the name
of a parameter that the diff of this path reports changed (removed, renamed, kind, default or
required): `The 'fastpath' keyword in pd.Series is deprecated`, `The default of observed=False is
deprecated`. Its words stay in the flag's message as they were, and the calls it is about are the
ones that pass the parameter, whether the diff reports the parameter as removed or only as a default
that changed. A word inside another word (`copy` in `copying`), a parameter that did not change and a
message that names none leave the deprecation about the whole name, which it may be. A parameter
that is named and also left out makes every call a finding (`pandas.core.groupby.GroupBy` with
`observed`), and the negative fixture shows none of them.

A path that has any other change (removed, moved, kind), a kind change the calls do not show, or a
name that is not ASCII stays flagged wherever it is used, as before. So does a member of a class: a
call can pass its object by hand (`Class.method(obj, ...)`, which moves every index by one), and the
scan types a receiver only for the classes a pack renames members of.

The comparison reads `no_default`, `lib.no_default` and `NoDefault.no_default` as "not given", as it
does `_Unset`: a default that became one is no default change. pandas 3 gives 2,872 of its 4,284
default changes that name.

Messages are unchanged: a path's own words, grouped by identical words, folded past 60 groups. A
folded group no longer hides the parameter, since each call says it in `evidence`. The pack's
fixtures show both sides: the positive one calls each shaped name with what changed, and a class that
only its bases changed of is read to be derived from, and the negative one calls it with none of it,
which `pack test` scans and must find nothing in. `limitations` says what D2 leaves out.

### D4. `Finding.evidence` is a closed word and what it takes

`evidence` was always `null`. It is now `null` or one of `keyword <name>`, `omitted <name>`,
`position <index>` and `spread`, the words of SCAN_VOCABULARY §14 and the name or index that a pack
gave (an identifier, never text from the source or a message). `Finding` refuses anything else, so a
source excerpt still cannot get into a finding. The terminal table and `REPORT.md` print it beside
the code that withheld the row.

## Consequences

- On eight repositories of each frame, the places flagged went from 4, 163, 293 and 236 to 2, 122,
  27 and 41 (urllib3, pydantic, SQLAlchemy, pandas). The shape alone, before the bases, the
  deprecations and the sentinel were read, took them to 2, 122, 271 and 202: the names that dominate
  SQLAlchemy and pandas had also changed their bases or carried a deprecation.
- What is left is the work. In pydantic 105 of 122 are calls that leave out a parameter whose default
  changed (`validator` without `check_fields`, `dataclass` without `frozen`); such a call relies on
  the old default, which is the claim. In SQLAlchemy all 27 are functions that changed kind
  (`relationship`, `select`, `text`), which the comparison reads from an attribute that became a
  function and cannot tell from a change of meaning. In pandas 26 are calls that pass a removed or
  renamed keyword and 15 are deprecations whose message names no changed parameter
  (`is_bool_dtype`, `StringDtype`), and every method stays flagged wherever it is used. A name used
  any way D2 does not clear is a finding.
- A message may name more parameters than the call passes: a path's changes are one message, and the
  call's own `evidence` names the one that matched.
- A message that names a changed parameter by word is a reading of English. A deprecation of the
  whole name that happens to use the word of a changed parameter is read as being about it, and a
  call that passes none of what changed is then let by. A parameter reordered, or a default that
  changed behind the same name, is not seen by the comparison at all. The limitation of ADR-063 D4
  stands.
- `pack.schema.json` gains `calls`, the findings schemas gain nothing (the field is a string), and
  `ScanSpec.flag_only_calls` is not published. The formats stay unstable through 0.x
  ([ADR-048](ADR-048-accepted-gaps-in-0-1-0.md)).
