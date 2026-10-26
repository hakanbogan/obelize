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
warning from 3.12, the release that removed each module). That is all that reads it, which amends
ADR-050 D1 ("a field no code reads is deleted"): a field may be there to be shown if a test holds
what it says, and this is the one.

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
  new side is. `obelize upgrade setuptools` from a release inside that old side goes on as it did,
  and says on stderr that the pack moves what that release holds onto the Python and is run by
  `fix --pack`. I decided against running the pack inside `upgrade`: a trial installs the release
  moved to into an environment, and a move onto the Python names none.
- `Consultation.to_package` is `None` there, and the prompt to a model says the target is the Python
  itself.

### D4. A pattern may spell names through the modules it lists

This amends ADR-069 D3, which made a pattern that needs an import the file does not have
inexpressible. A `rewrite_pattern` takes `imports`, a sorted list of importable dotted paths, each a
module of a closed list, `obelize.pattern.IMPORTABLE`, which PACK_SPEC names, or a name inside one
(`importlib.metadata`, `datetime.timezone`). A name `after` spells beside the name called keeps D3's
rule, written as the file spelled the module. Any other must be one segment below a listed path
(`datetime.timezone.utc` below `datetime.timezone`), so a module that itself imports `os` cannot be
walked through (`importlib.metadata.os.system` has two). The schema also refuses a path `after`
spells nothing under, and a name under a path that `match.symbols` lists as legacy.

The list is closed, and not a list of modules that are refused, because a pack is data. D3's rule
that a pack writes no code that reaches out of the program held while `after` spelled only names
beside the module called and a short list of pure builtins (`PURE`). A refusal list would name what
is known today (`os`, `sys`, `subprocess`, `importlib`, `runpy`, `ctypes`, `builtins`, `code`,
`pickle`, `marshal`, `shelve`, `socket`, `shutil`, `webbrowser`, `multiprocessing`, `signal`, `pty`
and their submodules) and let through what it does not: `tempfile`, `http.client`, `asyncio`, a
third-party package. A closed list allows a module by putting it there, as `PURE` allows a builtin,
and what nobody has looked at stays out. It holds the modules that only build or read a value;
`importlib.metadata` and `importlib.resources` are on it by name, so `importlib`, `importlib.util`
and the rest are not. A pack names a module it may call into and a person reads it first: `pack
validate` and the header of `fix` print the paths (`PackDocument.pattern_imports()`, with the
modules a rename writes), and the run folder keeps the pack.

The rule reaches a path in this order. It uses the first listed path the file already imports at its
top level above the call (`import m`, `import m as x`, `from p import m [as x]`) and binds nowhere
else. A parameter, a local, a `case` capture, a `del` or a second import of the name could stand in
its place where the call is, so a name bound twice, or by a capture or a `del`, is not used (the
scope analysis does not see the last two, so `ImportPlan` reads them off the tree itself). Failing
that it adds `from p import m` or `import m` for the last path, on a line of its own below the last
top-level import above the earliest call of the file that any rule rewrites, through the
`ImportPlan` that `rename_import` uses (`offer`, `take`, `require`), under a name nothing in the file
binds. If the name is bound, or the file has a star import anywhere, which may bind it where it
stands, the call is left for a person as `alias_collision`; if no top-level import lies above the
earliest call, as `local_import`. The module a call is made on is checked too: a `case` capture or a
`del` of its name leaves the call as `module_alias_rebound`. The reasons exist already.

### D5. A module whose name sits inside a word is left out

A prefilter token has to sit inside a module's name, so that no file importing it is skipped. For
`imp`, `uu`, `nis`, `crypt` and `chunk` the only tokens are parts of `import`, `uuid`, `finish`,
`encrypt` and `chunk`. A pack with `imp` for a token parsed 273 of the 297 files of an installed
library in 51.6 seconds, where one with `PyPDF2` parsed none in 0.1. `python/removed-stdlib-modules`
names the other twenty modules PEP 594, PEP 632 and the 3.12 notes removed and says in its
limitations that these five are left to a person. A scan that selected files by their import
statements would remove the limit; the token is what a pack has.

### D6. A shared pack's token may be the last segment of its symbols

A prefilter token has to be sure not to skip a file that uses the legacy surface. For a module a
pack matches by its name that means a token inside the name, so every file importing it holds one.
For a shared module (the new release keeps its name, and only `match.symbols` is legacy) a file can
import the module in a hundred files without using a symbol, and the name is the token of all of
them: with `datetime` for a token, a default scan of 4,000 files of 279 lines, a third of them naming
`datetime` and none calling `utcnow`, took 47.5 s where it had taken 2.5 s (the review measured 63
to 84 s on a repository of 4,040). So a module of a shared pack with no token in its
name is accepted when every symbol under it ends in a token. A file that spells a symbol holds its
last segment, however the module came into it: an attribute read (`dt.datetime.utcnow`), a name
imported with or without `as` (`from datetime import datetime as D`, then `D.utcnow`), a string
given to `getattr`, or a name a star import brought in, because each is the symbol's last segment
written out, so the file is parsed and the scan sees what it saw with `datetime` for the token (it
reports every spelling but a name given to `getattr`). What this does not cover is a name assembled
at run time, which no token finds either. A file that holds only the module's name is not parsed,
and a pack with a `flag_only` pattern is refused such a token, because a pattern finds the module
by its name in a string or a call. The datetime pack's tokens are `utcnow` and `utcfromtimestamp`; its default scan of the same 4,000 files
takes 2.3 s. The soundness is held by `tests/unit/test_runtime_packs.py`, which scans a file that
spells each symbol each of these ways.

The counts of a run follow what was done: `files_parsed` is the files any pack that was tried
parsed, where it was those of the packs that applied, and `0` when none did.

## Consequences

The pack schema, `docs/PACK_SPEC.md`, `docs/SCAN_VOCABULARY.md`, `docs/RUN_FOLDER.md`, the JSON
Schemas and the negative corpus describe and refuse the new shapes. Three packs ship with them:
`python/datetime-utcnow`, `setuptools/pkg-resources-to-importlib` and
`python/removed-stdlib-modules`. Each cites the documentation it rests on, its facts are held by
`tests/packs/test_runtime_facts.py` on the Python that runs the tests, and none has a Gate 1
measurement (ADR-059 D3). A default scan runs every known pack, so it parses the files that hold
`pkg_resources` or a removed module's name once more for each of them, and those that spell
`utcnow` or `utcfromtimestamp` for the datetime pack. The exit codes of `fix` and of `scan
--fail-on`, and so of the GitHub Action's defaults, change for a repository that uses what these
packs report, since a finding that holds a file is a finding.
