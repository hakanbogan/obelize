# Sources for `python/removed-stdlib-modules`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The retrieved pages

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| PEP 594, Removing dead batteries from the standard library (the pack's `source`) | <https://peps.python.org/pep-0594/> | 2026-10-24 | `50e541d9d19dd1ed46531e9596174efe9030cb66cf8ac186f13cce50b7eb394d` |
| PEP 632, Deprecate distutils module | <https://peps.python.org/pep-0632/> | 2026-10-24 | `184166968b142772b07f24128f51f3430249b8080e598032c4eea396354a2873` |
| What's New In Python 3.12 | <https://docs.python.org/3/whatsnew/3.12.html> | 2026-10-24 | `bc1ab5402bf32240db0da103113feced72ab8e1dbd94bf368d161c1eb0874abc` |
| What's New In Python 3.13 | <https://docs.python.org/3/whatsnew/3.13.html> | 2026-10-24 | `30d3d3d419b3e527dc6dee993f4fd046a77013c7537145fa7a81f81e49dbba22` |
| Python documentation, shlex | <https://docs.python.org/3/library/shlex.html> | 2026-10-24 | `6552ab8040383c9aa41e5ad1d3c928517068cb104d58f4582d44193e1e085abe` |

The hash is of the page body as served. obelize never requests the URL. Where a sentence of a flag
text is not in a page above, the section for that flag says it is mine.

## The measurement, and why it outranks the page

"Measured" means run on CPython 3.9.6, 3.10.14, 3.11.11, 3.12.9, 3.13.5, 3.14.7 and 3.15.0rc2 on macOS:
`sys.stdlib_module_names` (from 3.10) lists `asynchat`, `asyncore`, `distutils` and `smtpd` on 3.10 and
3.11 and none of them from 3.12, and the other sixteen modules of the pack up to 3.12 and none from
3.13, as the two release notes say; `import asyncore` and the other imports of removed modules raise
`ModuleNotFoundError` on 3.13; and where `pipes` ships (3.9 to 3.12), `pipes.quote is shlex.quote`. `tests/packs/test_runtime_facts.py` holds both on the Python that runs the tests, and
CI runs it on every Python from 3.12 to 3.15. `pipes.py` of 3.11.11 says why: "we import the
quote function rather than the module for backward compat (quote used to be an undocumented but
used function in pipes)" above `from shlex import quote`.

`imp`, `uu`, `nis`, `crypt` and `chunk` were removed in the same releases (3.12 for `imp`, 3.13 for
the rest), and are measured to be gone from the same Pythons, but they are not in the pack: a
prefilter token has to sit inside the module's name, and `imp`, `uu`, `nis`, `crypt` and `chunk` sit
inside `import`, `uuid`, `finish`, `encrypt` and `chunk`. Run over the 297 files of an installed
library, a pack whose token was `imp` parsed 273 of them in 51.6 seconds, and the one whose token
was `PyPDF2` none in 0.1.

---

## rename-pipes

- Python documentation, shlex: "`shlex.quote(s)` Return a shell-escaped version of the string `s`."
  PEP 594 lists `pipes` as removed in 3.13 and names `subprocess` as its replacement for the module;
  the function everyone calls from it, `quote`, is the one `shlex` defines.
- Measured: `pipes.quote is shlex.quote` on 3.9 to 3.12 (the same function object), so a call is
  the same call under another name. `shlex.quote` exists from 3.3, which is `to.python`.
- `pipes.Template` has no counterpart in `shlex` and is flagged by `flag-replaced-elsewhere`.

## flag-event-loops

- What's New In Python 3.12, Removed: "`asynchat` and `asyncore`: These two modules have been removed
  according to the schedule in PEP 594, having been deprecated in Python 3.6. Use `asyncio` instead."
  PEP 594 lists `asyncio` as the replacement of both.

## flag-smtpd

- What's New In Python 3.12, Removed: "`smtpd`: The `smtpd` module has been removed according to the
  schedule in PEP 594, having been deprecated in Python 3.4.7 and 3.5.4. Use the `aiosmtpd` PyPI
  module or any other `asyncio`-based server instead."

## flag-distutils

- What's New In Python 3.12: "the `distutils` package has been removed from the standard library",
  and "Do not pre-install setuptools in virtual environments created with `venv`. This means that
  `distutils`, `setuptools`, `pkg_resources`, and `easy_install` will no longer be available by
  default".
- PEP 632, Migration Advice: "`distutils.version` — use the `packaging` package. `distutils.fancy_getopt`
  — use the `argparse` module. `distutils.spawn.find_executable` — use the `shutil.which` function.
  `distutils.spawn.spawn` — use the `subprocess.run` function. `distutils.sysconfig` — use the
  `sysconfig` module. `distutils.util.get_platform` — use the `platform` module." (The pack does not
  repeat the last: measured on 3.12 with `setuptools` 81.0.0 alone, `distutils.util.get_platform()`
  and `sysconfig.get_platform()` both return `macosx-15.0-arm64`, and the `platform` module has no
  `get_platform`. `sysconfig.get_platform` is my correction of the PEP.) And: setuptools
  is "the best substitute" for `ccompiler`, `cmd.Command`, `command`, `config`, `core.Distribution`
  and `errors`; for `dir_util.create_tree`, `util.change_root` and `util.strtobool` "you will need to
  reimplement the functionality yourself."
- Measured on 3.12 with `setuptools` 81.0.0 alone: `import distutils` and `from distutils.version
  import LooseVersion` work, from `setuptools/_distutils`; with nothing installed beside the
  interpreter, `import distutils` raises `ModuleNotFoundError`.

## flag-cgi

- What's New In Python 3.13: PEP 594 removed `cgi` and `cgitb`.
- PEP 594, cgi: "Replacements for the various parts of cgi which are not directly related to
  executing code are: `parse` with `urllib.parse.parse_qs`; `parse_header` with
  `email.message.Message`; `parse_multipart` with `email.message.Message`; `FieldStorage` /
  `MiniFieldStorage` has no direct replacement, but can typically be replaced by using `multipart`
  (for POST and PUT requests) or `urllib.parse.parse_qsl` (for GET and HEAD requests)". Table 1
  of the PEP gives `cgitb` no replacement.

## flag-replaced-elsewhere

- PEP 594, Table 1, the Replacement column: `imghdr`: `filetype`, `puremagic`, `python-magic`;
  `pipes`: `subprocess`; `sndhdr`: `filetype`, `puremagic`, `python-magic`; `spwd`: `python-pam`;
  `telnetlib`: `telnetlib3`, `Exscript`.
- What's New In Python 3.13: these are among the nineteen modules PEP 594 removed.

## flag-without-replacement

- PEP 594, Table 1: `aifc`, `audioop`, `mailcap`, `msilib`, `nntplib`, `ossaudiodev`, `sunau` and
  `xdrlib` have `-` in the Replacement column. What's New In Python 3.13 removed all of them, and
  "the 2to3 tool and lib2to3 module".
- PEP 594 says of `audioop` that `aifc`, `sunau` and `wave` depend on it for some operations. That
  is the PEP's account of the standard library as it was in 2022; measured, `import wave` does not
  load `audioop` on 3.12 or 3.13, and the pack does not repeat the sentence.
- The text of this flag is mine where it names the modules without a replacement; the PEP's table
  has `-` for each, and `lib2to3` is not in the PEP but in the 3.13 notes.

## flag-indirect-use

- PEP 594, Rationale. A removed module reached as a string, or through a dynamic import, is read by
  shape and is never rewritten.
