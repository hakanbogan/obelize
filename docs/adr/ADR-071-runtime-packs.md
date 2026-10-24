# ADR-071: Runtime packs

## Status

Accepted.

## Decision

A change of the interpreter or its standard library is no change of a library you install.
`datetime.utcnow()` is deprecated in Python 3.12, `asyncore` left the standard library in the same
release, and setuptools 82 removed `pkg_resources`. A pack named a distribution and a range of it on
each side (ADR-018) and gated the run on the Pythons that distribution installs on (ADR-050 D4), so
each of these was left to a person. A side of a pack may now be the Python.

### D1. A side is a distribution or the Pythons it runs on

`package` and `version` name a distribution together, and `python` is a PEP 440 set of Pythons. A
side is one of the two, never both and never neither, and `to.requires_python` stays what a
distribution says of the Pythons it installs on. `newest`, `lacks`, `since`, `requires_python` and
`introduces` are about the releases of a distribution, `match.transitive` is about what one
installed, and a `manifest_dependency` moves a line from one distribution to another, so a pack with
a Python on the side one of them is about is refused, and the schema says which. The two sides are
independent: `setuptools/pkg-resources-to-importlib` moves from `setuptools` below 82, the releases
that ship `pkg_resources`, to `python: ">=3.10"`.

### D2. The gate is the Python the repository declares

`ScanSpec.requires_python` is `to.requires_python` for a distribution and `to.python` for the Python,
and ADR-050 D4's check is unchanged: every Python from 2.7 and 3.0 to 3.29 is asked of the
repository's declaration, one that admits a Python outside the set blocks the run
(`runtime_unsupported`), and one that declares none does not. The sentence a report prints names no
distribution when there is none. `from.python` says on which Pythons the old spelling is deprecated
or gone. It blocks nothing, since a repository on an older Python is not harmed by the rewrite;
`pack validate` prints it and the facts test of the packs holds it against the interpreter (the
warning from 3.12, the release that removed each module).

### D3. No distribution, no pin

`ScanSpec.legacy_distribution` and `new_distribution` are empty for a side that is the Python, as
`legacy_range` is empty where there is none, so the three bundled packs of 0.8.0 project the same
spec and keep their `spec_digest`. Everything that read a distribution reads that:

- `manifests.coupled` is false for two empty names, and `manifests.plan` returns the declarations of
  the old distribution as context when the new side is the Python, as an inventory's are. No pin
  moves, and no file is held back by one.
- `loader.conflict` names a distribution only where there is one.
- `upgrade` never chooses a pack whose new side has no distribution to move a dependency to.
  `obelize upgrade <module>` for a module such a pack matches (`pkg_resources`) that no manifest
  declares as a distribution stops with exit `2`, names the pack and says to run `fix --pack`.
  `outdated` lists a pack against the distribution that is its old side, `setuptools`, whatever its
  new side is.
- `Consultation.to_package` is `None` there, and the prompt to a model says the target is the Python
  itself.

### D4. A pattern may spell names through the modules it lists

This amends ADR-069 D3, which made a pattern that needs an import the file does not have
inexpressible. A `rewrite_pattern` takes `imports`, a sorted list of importable dotted paths, modules
or names inside them (`importlib.metadata`, `datetime.timezone`). A name `after` spells beside the
name called keeps D3's rule, written as the file spelled the module, and any other name must be under
a listed path. The schema refuses a path `after` spells nothing under, a path that is `builtins`
(whose names D3's list of pure functions keeps out), and a name under a path that `match.symbols`
lists as legacy.

The rule reaches a path in this order. It uses the first listed path the file already imports at its
top level above the call (`import m`, `import m as x`, `from p import m [as x]`) and binds nowhere
else in the file, written as the file spelled it. A parameter, a local or a second import of the name
could stand in its place where the call is, so a name bound twice is not used. Failing that it adds
`from p import m` or `import m` for the last path, on a line of its own below the last top-level
import above the first call, through the `ImportPlan` that `rename_import` uses (`offer`,
`take`, `require`), under a name nothing in the file binds. If the name is bound, the call is left
for a person as `alias_collision`; if no top-level import lies above the call for the new line to
follow, as `local_import`. Both reasons exist already.

A pack was already trusted to name the modules a repository imports (`rename_import`) and the
distribution a pin adds. What `imports` adds is that it may call a function of a module it names, so
a pack written by someone else is read before it is run (TM-1): the list is in the pack the run
folder keeps, and `PackDocument.to_modules()` returns it with the modules a rename writes.

### D5. A module whose name sits inside a word is left out

A prefilter token has to sit inside a module's name, so that no file importing it is skipped. For
`imp`, `uu`, `nis`, `crypt` and `chunk` the only tokens are parts of `import`, `uuid`, `finish`,
`encrypt` and `chunk`. A pack with `imp` for a token parsed 273 of the 297 files of an installed
library in 51.6 seconds, where one with `PyPDF2` parsed none in 0.1. `python/removed-stdlib-modules`
names the other twenty modules PEP 594, PEP 632 and the 3.12 notes removed and says in its
limitations that these five are left to a person. A scan that selected files by their import
statements would remove the limit; the token is what a pack has.

## Consequences

The pack schema, `docs/PACK_SPEC.md`, `docs/SCAN_VOCABULARY.md`, `docs/RUN_FOLDER.md`, the JSON
Schemas and the negative corpus describe and refuse the new shapes. Three packs ship with them:
`python/datetime-utcnow`, `setuptools/pkg-resources-to-importlib` and
`python/removed-stdlib-modules`. Each cites the documentation it rests on, its facts are held by
`tests/packs/test_runtime_facts.py` on the Python that runs the tests, and none has a Gate 1
measurement (ADR-059 D3). A default scan runs every known pack, so it parses the files that hold
`datetime`, `pkg_resources` or a removed module's name once more for each of them.
