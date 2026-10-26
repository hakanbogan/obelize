# ADR-069: Rewrite a call from the shape of its arguments

## Status

Accepted; amended by [ADR-071](ADR-071-runtime-packs.md) (D3).

## Decision

A library often replaces a call by one of another shape: `parse_obj_as(T, v)` is
`TypeAdapter(T).validate_python(v)`, `model.dict(exclude=e)` is `model.model_dump(exclude=e)`.
`rewrite_call` expresses a move to a call on a client with a fixed table of arguments, and
`rename_member` a rename with the arguments kept. A call that changes shape in a way neither names
was a flag. A new kind, `rewrite_pattern`, takes the shape from two templates a pack's author writes.

### D1. Two templates

`before` is a call and `after` the expression that replaces it, each a Python expression on one
line, at most 2000 characters and 40 levels deep in Python's syntax tree, in which `$name` stands
for any expression. A template is parsed once by libcst, never run and never read as a regular
expression. Its depth is counted by `ast` first, since libcst's native parser overruns the stack of
a Windows process on a deeper one. It holds only names, attributes, calls, numbers, strings,
tuples, lists, dictionaries, subscripts with one index and unary operators; a `*` or `**` argument,
a lambda, an operator between two values and the rest are refused when the pack loads, so what a
pattern matches is what a person reading it sees. A metavariable stands for an expression and never
names an attribute or a keyword.

### D2. A call is found by its name and compared by its arguments

The call is of a qualified name written out (`pydantic.parse_obj_as(...)`), or a member of a class
(`$m.dict(...)` with `where: {m: pydantic.BaseModel}`, found as `rename_member` finds it, so that
what `where` names is read off a receiver as `rename_member`'s classes are). The scan finds the call
by that name, as it finds any use of a name, so a module spelled by an alias, or the class written
through its module, is found whichever way it is written. The rule then compares the arguments with
`before` by form: the positional arguments in order, the keywords by name and not by order, a number
or a string by value, the rest structurally, a metavariable used twice by the same text. A call of
another shape (another number of arguments, a keyword `before` lacks, a `*` or `**` argument) is
`pattern_unmatched`, a new code, and is left for a person: a pattern is no claim about calls it did
not cover.

### D3. What `after` may spell

A name `after` writes out must stand where the old name stood: in the same module
(`pydantic.TypeAdapter` for `pydantic.parse_obj_as`), spelled as the file spelled the module (`pd.`
for `import pydantic as pd`); a call written without its module (`from pydantic import
parse_obj_as`) has none to spell it by, and is `from_import_unmigrated_symbol`, as `rewrite_call`
rooted on a module is. Metavariables and a short list of builtins that only build a value from
their arguments (`int`, `str`, `list`, `len`, ...) may be written without a root; `open`, `eval`,
`exec`, `getattr` and every dunder name may not, since a pack is data and writes no code that
reaches out of the program. A pattern that needs a module the file may not import lists it in
`imports`, and may spell names one segment below it, but only for a module of a closed list of those
that build or read a value and reach nothing else ([ADR-071](ADR-071-runtime-packs.md) D4). This
rule held while a pack could name no module, so ADR-071 keeps it by listing the modules instead of
dropping it. The schema refuses a name beyond these, one `match.symbols` lists as legacy, `after` calling the name `before` is found by
(or reading the member a member pattern is found by, or another member of its class that
`match.symbols` lists), so the result is no new finding.

### D4. What a rewrite does not change

An expression a pattern binds is written once in the new call as it was in the old, and is run once.
One that `after` writes twice or not at all is rewritten only where running it twice, or never, is no
different from once (a name, an attribute of one, a number or a string); otherwise the call is
`pattern_unmatched`. A metavariable written twice in `before` stands for one expression, so it is
bound only to such a pure one. The order a pattern writes its arguments in may differ between
`before` and `after`, and then so may the order in which side effects run. The new expression
stands where the call stood and keeps its meaning there: it is in parentheses unless it is as tight
as a name or the call was all there was to a statement, a right-hand side, a returned value or one
argument, and it is on one line; a generator, a walrus or a `yield` that a call's own brackets held
is put in brackets of its own. A call written inside an f-string is left where `after` writes a
string, whose quotes may be the f-string's. A template reads no `$name` inside a string.

### D5. What it reads off a receiver, it reads as `rename_member` does

A `where` class and the member called are read off a receiver by the scan of ADR-068, with all its
limits: a receiver nothing types is left as it is. An expression put before a dot, or where a
call or a subscript is read, is written in parentheses unless it is as tight as a name.

## Consequences

The pack schema, `docs/PACK_SPEC.md`, `docs/SCAN_VOCABULARY.md`, the JSON schemas and the negative
corpus describe and refuse the new fields. `obelize.pattern` is a module of its own, loaded only by
what reads a template.
