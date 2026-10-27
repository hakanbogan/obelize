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
give) and `bases` (the class's bases changed, which no call passes). A `*` argument can pass
positions, so a call with one matches a shape that has `positional_from` or an indexed `omits` name,
and a `**` argument can pass keywords and names, so a call with one matches a shape that has
`keywords` or `omits`; where it is in doubt, a call matches. A shape names at least one of the four,
sorted. It is data and closed: no pattern, no expression. A new kind of change would have put one
surface in two changes, which a pack may not do, and a field of `ScanSpec` alone would have had no
pack to write it.

`calls` is optional, and a symbol with no entry is flagged wherever it is used, so the packs that
exist read as they did. `ScanSpec.flag_only_calls` holds the shapes beside `flag_only_symbols`,
which still lists every flagged symbol, and `spec_digest` leaves the field out while it is empty:
the digest of each bundled pack is what it was. A shape for a symbol that `from.lacks` or
`from.since` lists, or sits under, is refused, because the scan reads those off its findings and a
call a shape passes over is none.

### D2. What the scan does with a symbol that has a shape

The shape decides for the symbol it is written for, when the pack flags no name above it whole:

- A call that matches is flagged (`flag_only_surface`), and says what matched in `Finding.evidence`.
  The arguments judged are those of the call that names the symbol: in `validator("x", pre=True)(fn)`
  the `pre`, not the `fn`. A decorator is judged by what it names, `@f(...)` by its call and a bare
  `@f` as a name used any other way, so it is one finding and not two.
- A call that matches none is the API as it was, and so is a name that is not called and is imported,
  annotated (a quoted annotation too) or handed to a call as an argument (`Column(Integer)`,
  `map(pd.to_datetime, rows)`, `isinstance(x, Series)`). Neither is a finding in a shared module. In a
  module that is not shared each is graded as if the symbol were not flagged, and the pack's other
  rules claim it. The code that receives a handed name may call it with anything, which the scan
  cannot follow, so the pack's `limitations` say it. Where the call it is handed to passes a keyword
  that the shape lists (`partial(f, removed=1)`, `executor.submit(f, x, removed=1)`,
  `df.pipe(f, removed=2)`), the keywords after the name are almost surely `f`'s, and the use stays a
  finding. A positional argument after it cannot be told from `map(f, rows)`, and is let by.
- Every other use is a finding as before: a class named as a base (its `__init__` runs through
  `super()`), a name assigned to another, a decorator, a default value, a name in a list, a name
  inside the symbol (`Column.something`), an import inside a function, a `mock.patch` target. When in
  doubt the use stays flagged.
- A class whose bases changed, and is built with what it was (D3), is no finding at any call, a `*`
  or `**` one included: construction is what it was, and a use by name cannot see what the class
  derives from. What a changed base breaks is code that derives from the class (`class X(Column)`,
  which reaches the class through `super()`), so that stays a finding, with every other use this
  list keeps. A class with a shape of parameters as well is judged at its calls by the shape.
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
| bases changed | `bases`, where the class is built as it was |
| deprecated, its message naming a parameter of the path that changed | the part of removing that parameter, so a call that passes it is one |

A parameter that a new `**kwargs` takes is a removal all the same, and the flag says so
(`sessionmaker(autocommit=True)` raises in SQLAlchemy 2.0, though `**kw` accepts the word). The
first parameter of a method is its receiver when it is called `self` or `cls` or starts with two
underscores (`__pydantic_self__`), so the reader does not count it: counted, pydantic's `BaseModel`
becomes a class whose parameters changed, stands for its members, and is flagged as a base 82 times.
A parameter named `__name`, the old convention for one only a position can give, is never a
keyword, a removal or a change by name.

A class whose bases changed is built as it was when both releases give it an `__init__` of its own
(the diff compares those), or when what it gets from its bases takes what it took: the first base
that has one is found by the name it is written with, in the same release, and a name that two
classes go by, or none, leaves the class flagged wherever it is used. urllib3's `NewConnectionError`
has none of its own in either release and gets its constructor from `HTTPError`, which changed.

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
does `_Unset`: a default that became one is no default change. pandas 3.1 gives 2,872 of its 4,284
default changes that name. A private name that does not say it is a sentinel (`_DEFAULT_TIMEOUT`)
is a value, and a default that became one is a default that changed, which over-flags urllib3's own
token of that name; `_Default` alone is read as a sentinel.

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

- On eight repositories of each frame, the same comparison read without shapes flagged 4, 163, 293
  and 220 places (4, 120, 195 and 219 distinct sites). With them it flags 2, 98, 28 and 41 (as many
  sites): urllib3, pydantic, SQLAlchemy, pandas. The shape alone, before the bases, the
  deprecations and the sentinel were read, left 2, 122 (82 sites), 27 and 41.
- What is left is the work, by what the finding says. urllib3's two are a call that passes
  `method_whitelist` and one that leaves out `allowed_methods`. In pydantic 98 are 44 calls that leave
  out a parameter whose default changed (`validator` without `check_fields` 36, `create_model` 5,
  `constr` 3), 18 that pass a keyword that went (`Field` with `regex` or `min_items` 15, which
  `**extra` takes without a word), 6 with a `*` or `**` argument, and 30 with no evidence: 11 bare `@dataclass` decorators
  (each leaves out `frozen` and `init`), 14 uses of the deprecated `Extra`, and 5 others. In
  SQLAlchemy 27 are functions that changed kind (`relationship` 25, `select`, `text`), which the
  comparison reads from an attribute that became a function and cannot tell from a change of meaning,
  and one is `sessionmaker(autocommit=True)`. In pandas 15 have evidence (7 pass a keyword that went,
  5 leave one out, 3 have a `*` or `**` argument) and 26 have none: 10 uses of `Series` that are no
  call (5 in a tuple handed to `isinstance`, 4 in another tuple or list, 1 assigned), 14 of
  deprecations whose message names no changed parameter (`is_bool_dtype` 8, `StringDtype` 3,
  `from_records` 3) and 2 others. Every method stays flagged wherever it is used. A name used any way
  D2 does not clear is a finding.
- A message may name more parameters than the call passes: a path's changes are one message, and the
  call's own `evidence` names the one that matched.
- A message that names a changed parameter by word is a reading of English. A deprecation of the
  whole name that happens to use the word of a changed parameter is read as being about it, and a
  call that passes none of what changed is then let by. A parameter reordered, an optional one
  inserted before others, and a default that changed behind the same name are not seen by the
  comparison at all. The limitation of ADR-063 D4 stands.
- Two things are let by that a reader could take to be flagged: a positional argument after a name
  handed to a call (D2), and an object built by a class whose bases changed, which no longer passes an
  `isinstance` check against a base it lost.
- `pack.schema.json` gains `calls`, the findings schemas gain nothing (the field is a string), and
  `ScanSpec.flag_only_calls` is not published. The formats stay unstable through 0.x
  ([ADR-048](ADR-048-accepted-gaps-in-0-1-0.md)).
