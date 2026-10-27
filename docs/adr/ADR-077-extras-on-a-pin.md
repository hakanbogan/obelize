# ADR-077: Extras on a moved pin

## Status

Accepted.

## Decision

A requirement that names extras (`mcp[cli]>=1.28.1`) was left as it was by every pack, and the pin of a
pack with one distribution held the whole repository, because the extras are the old release's:
the new one may not have them, and a rewrite that keeps one it lacks is a line pip warns about. For
a move of one distribution the extras usually survive, so the rule is the smallest that can be
proved. The pin moves and the extras stay if every extra the line names is in the `Provides-Extra`
of the release it moves to, a fact the pack states and `pack synth` reads from that release's wheel;
otherwise the line is left as it was and named, as before. Nothing is guessed at scan time, and a
pack that states no extras behaves byte for byte as it did.

### D1. The fact is in the pack, as data a person can check

`manifest_dependency` takes `provides_extras`: sorted, de-duplicated names in the form PEP 685
gives (`^[a-z0-9]+(-[a-z0-9]+)*$`), default none. Names are compared in that form, so `Dev_Tools`,
`dev.tools` and `dev-tools` are one extra. The field is refused unless `from_name` and `to_name`
are one distribution: a renamed one (`PyPDF2[crypto]` to `pypdf`) is not known to have the old one's
extras, and stays withheld whatever a pack says. The scan's view of a pack (`ScanSpec.new_extras`)
leaves the digest while it is empty, so no measurement of an older pack moves.

The three older bundled packs and `numpy/numpy-1-to-2` state none, so their results are what they
were. A bundled pack states it by hand with a citation to the release metadata page; none does yet,
because `openai[datalib]` and the like need that page read and cited first.

### D2. One function decides, for the scan and for the rule

A declaration the reader finds with extras has no `pin`, as before, but carries `extras`: the names
and the span of what follows them. `editable_pin(declaration, provided)` returns the pin; or, for a
requirement with extras, that span if every name is in `provided`; else `None`. The scan asks it
with `ScanSpec.new_extras` where it grades a one-distribution pack, and the rule asks it with its own
`provides_extras`, so a row the scan calls eligible is one the rule writes (`_refused` withholds
the rest, as for any rule). A form that gave no pin for another reason gives no `extras`: every place
that cleared the pin for a hash, a continuation, an editable requirement, a file nobody writes or a
literal that is not whole clears them too. Reading a form wrongly therefore fails to a line left as it was.

### D3. What is edited and what is not

The edit replaces the specifier text after the extras and nothing else (the name is written as the
pack spells it, as for any pin, and a marker, a comment and the options stay).

Edited:

- a requirements file line (`requirements*.txt`, `requirements/*.txt`), with an environment marker,
  a comment or an option that is not a hash;
- a string of a PEP 621 or PEP 735 array, uv's, PDM's and Hatch's;
- a `setup.cfg` value in `install_requires`, `setup_requires`, `tests_require` or
  `extras_require`;
- a plain string literal under a requirement keyword of `setup.py`, or in the list one stands for;
- a Poetry or Pipfile inline table on one line that holds exactly `version` and `extras`, in either
  order, with every extra a quoted name: the string after `version` is replaced.

Withheld, as `manifest_pin_shape_unsupported`, with the line left as it was:

- a hash, a continuation, an editable requirement, a URL, an archive;
- a constraints file and a pip-tools input, which are read and never written;
- a `setup.cfg` line with a trailing comment, which setuptools refuses too;
- a `setup.py` literal that is not the whole requirement (concatenated, joined to a name, escaped
  or over two lines);
- a Poetry or Pipfile dependency given as a table of its own (`[tool.poetry.dependencies.mcp]`, the
  group and dev forms), whose version is on another line;
- an inline table with another key, an empty or multi-line `extras`, or an extra that is not a
  quoted name;
- a declaration that `declare_transitive` would need to write below: only a plain requirements line
  is a host, so the pin waits (`transitive_dependency_in_use`);
- a renamed distribution, and an extra the release does not list.

A requirement the code builds in `setup.py` (a variable, an f-string) is not read, as before.

### D4. `pack synth` reads it from the wheel it cites

`libdiff.compare` reads the `Provides-Extra` headers of the newer release, from the one
`*.dist-info/METADATA` of the unpacked wheel `choose` picked, the file the pack's `source` hashes:
the header block up to its first blank line, the first MiB of it, each name in its normal form and
valid as an extra, at most 128 of them. No wheel (a source distribution holds `PKG-INFO`, which
the archive does not unpack), no or several `dist-info` directories, or a metadata that predates the
field give none, and the pack states none. The pack's `dependency-line` carries the list, its
citation says the `Provides-Extra` lines of the release's METADATA are where it is from, and the
positive fixture gains a line with the first extra, so `pack test` shows one kept (the `.after`
file is what the rule wrote).

What the list proves is what the release declares: that pip will not warn about the extra, not that
what it installs works. A later release may drop one; pip then warns and installs without it, as it
would for a hand-written line, and nothing fails.

## Consequences

`docs/PACK_SPEC.md` has the field, `docs/SCAN_VOCABULARY.md` the narrowed reason, `docs/UPGRADING.md`
and `docs/KNOWN_ISSUES.md` what a person sees, and the negative corpus the three refusals of the
field. The bundled packs and their pack hashes are unchanged. Widening this to a renamed
distribution, to a source distribution's `PKG-INFO`, or to a table of its own in a TOML file is a
decision of its own.
