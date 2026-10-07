# ADR-051: Second migration family

## Status

Accepted.

## Decision

A migration family joins the bundled packs only after a Gate 0 that measures every fact its rules
rest on, with a stop condition: a fact that fails ends the pack, not the measurement. The second
family is **`PyPDF2` -> `pypdf`**, `py-pdf/pypdf2-to-pypdf`, chosen because it needs none of what
Gemini needs (no client, no object to follow) and so shows that the pack format, not the SDK, is
what the engine depends on (ADR-050).

### D1. The Gate 0 measured, and the target moved because of it

Run on PyPDF2 3.0.1 and pypdf 3.17.4, 4.3.1, 5.9.0 and 6.19.0:

- PyPDF2 3.0.1 imports on CPython 3.12, 3.13 and 3.14, and the project itself says it is deprecated.
- Its camelCase API raises `DeprecationError` rather than warn, so a name that still uses it is
  already broken on the versions the pack migrates from.
- pypdf 3.17.4 has PyPDF2 3.0.1's public surface exactly, but 97 advisories name it, all denial of
  service on a crafted file, some rated high, each first fixed in the 6 line. pypdf 6.19.0 has
  none and lacks four things PyPDF2 3.0.1 accepts, all on an object.

The pack therefore targets `pypdf >=6.19` and says in `limitations` what it cannot see, rather than
pin the line whose surface matches and leave the user on known vulnerabilities. This is the one
place a pack's `to.version` is chosen over the surface that would make the migration provable.

### D2. A pack's facts are tests against both installed projects

`tests/packs/test_pypdf_facts.py` reads the names, kinds and parameters from the two modules and
fails when a mapped name stops being the same kind of thing, when a class PyPDF2 defines is neither
mapped nor reported, or when `to.requires_python` differs from pypdf's metadata. The generic
contract (`tests/packs/test_all_packs.py`) runs over every bundled pack.

### D3. The pack reports instead of guessing about objects

There is no rule kind that follows an object, so a method or a parameter is never rewritten or
reported. The four losses D1 names are in the pack's `limitations`, and the verification phase
(`--verify`) is what finds the rest in a repository.

## Consequences

- A repository that declares Python below 3.9, or PyPDF2 below 3, or uses PyPDF2 and declares it
  nowhere obelize reads, is blocked, not migrated.
- Gate 1 is not measured for this pack: the README and BENCHMARK say so.
- `pypdf` and `PyPDF2` are development dependencies pinned to the measured releases, and Dependabot
  leaves them alone.
