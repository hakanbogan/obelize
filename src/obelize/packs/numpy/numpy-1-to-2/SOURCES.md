# Sources for `numpy/numpy-1-to-2`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The retrieved pages

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| NumPy 2.0 migration guide (the pack's `source`) | <https://numpy.org/doc/stable/numpy_2_0_migration_guide.html> | 2026-10-27 | `ef9b0ac609c4a8401594abfe20f77c5e8b21d48cb5974db7705b4a0c3ddc84e7` |
| NumPy 2.0.0 release notes | <https://numpy.org/doc/stable/release/2.0.0-notes.html> | 2026-10-27 | `58cfb4d550417d30f15b49d62a8f25770b5b4cb5194e4df6c043af66df5b57d7` |
| NumPy 2.4.0 release notes | <https://numpy.org/doc/stable/release/2.4.0-notes.html> | 2026-10-27 | `3c8614e6a49d6c9f87a67488e50e9f04de4155e671c75cb44671f47e591a7be1` |
| ruff, `numpy2-deprecation` (NPY201) | <https://docs.astral.sh/ruff/rules/numpy2-deprecation/> | 2026-10-27 | `ce672c2e14341aee1b50d9ba9d7ed6be15d3a66b7724938f18da7bbbeb8f9f47` |

The hash is of the page body as served. obelize never requests the URL.

## The measurement, and why it outranks the page

"Measured" means run, with no network call but the installer's, on CPython 3.12.

**NumPy.** Each name the pack rewrites was looked up with `hasattr(numpy, name)` beside the name it
becomes, on **1.26.4**, **2.0.2** and **2.5.4**. On 1.26.4 every one of the 23 exists and so does its
replacement: the nine type aliases (`float_`, `complex_`, `cfloat`, `longfloat`, `longcomplex`,
`clongfloat`, `singlecomplex`, `string_`, `unicode_`), `row_stack`, `mat` and the six constants
(`Inf`, `Infinity`, `infty`, `PINF`, `NaN`, `NAN`) are **the same object** as the name they become
(`numpy.float_ is numpy.float64`), and `alltrue`, `sometrue`, `cumproduct`, `product` and `round_`
are wrappers that returned the same value and dtype as `all`, `any`, `cumprod`, `prod` and `round`
for the arrays tried. The source of `numpy.safe_eval` on 1.26.4 is `return ast.literal_eval(source)`,
and its docstring says it is identical to it. On 2.0.2 none of the old names exists, so a use of one
is an `AttributeError` there, except `row_stack`, which 2.0.2 and 2.4.6 still have as a deprecated
wrapper and 2.5.0 removed. The code the pack writes therefore runs on 1.x and on 2.x alike, which is
why `from.version` states no floor.

Every public name of `dir(numpy)` on 1.26.4 (553) and the five that `dir` hides there but `hasattr`
finds (`AxisError`, `ComplexWarning`, `ModuleDeprecationWarning`, `TooHardError`,
`VisibleDeprecationWarning`) was looked up with `hasattr` on 2.0.2 and 2.5.4. 93 of the 553 and all
five are gone by 2.0.2 or 2.5.4 (`in1d`, `row_stack`, `trapz` and `chararray` go only with 2.5): 98.
The pack rewrites 23 and reports the other 75, so none of the 98 is silent. (`dir` is no test on the
other side either: on 2.0.2 it omits `numpy.version` and `numpy.chararray`, which `hasattr` finds.)
`numpy.in1d` and `numpy.trapz` exist on 1.26.4, 2.0.2 and 2.3.5 and on neither 2.4.0 nor later,
`numpy.row_stack` exists through 2.4.6 and not on 2.5.0, and `numpy.chararray` exists on 1.26.4 and
2.0.2 and not on 2.5.4. The pack flags `in1d`, `trapz` and `chararray`, because a repository moving
to a release of `>=2` cannot keep them, and rewrites `row_stack`, which the guide gives a drop-in
for. The five hidden names are `numpy.exceptions.X` on 1.26.4 as well (a module NumPy 1.25 added),
which is why they are reported with that suggestion and not rewritten: the pack states no floor.

A name written as a string is a second route to the same break. `numpy.dtype(key)` accepts all 108
string keys of `numpy.sctypeDict` on 1.26.4 and raises on 2.0.2 for sixteen (`bool8`, `bytes0`,
`cfloat`, `clongfloat`, `complex_`, `float_`, `int0`, `longcomplex`, `longfloat`, `object0`,
`singlecomplex`, `str0`, `string_`, `uint0`, `unicode_`, `void0`) and on 2.5.4 for `a` as well. The
scan reads names and not strings, so these are a limitation and not a row.

**ruff.** The pack's six fixtures that name the rewritten names (`aliases`, `constants`,
`functions`, `mixed`, `safe_eval`, `strings`) were run as `ruff check --isolated --select NPY201
--fix-only --stdin-filename=a.py -` under **every release from 0.6.2 to 0.17.3**: 116 releases, among
them 0.12.6, which PyPI marks as yanked. Every one wrote the same bytes and exited 0. Twenty-one of
them (0.6.2, 0.7.4, 0.9.10, 0.11.13, 0.12.6, 0.13.3, 0.14.10, 0.15.12, 0.16.0 and each from 0.16.3
to 0.17.3) were also started by the driver itself, and its output compared byte for byte with the
answer keys. Under 0.5.0 to 0.6.1 the output differs. `tests/packs/test_all_packs.py` runs the
fixtures under the ruff of the development environment; `transforms/fixers.py` names the range,
and a newer release is refused until it is run the same way. 0.17.3 was the newest release when it
was measured.

Which names ruff rewrites was found by writing every name above on a line of its own and running
the same command under the 23 releases installed for the driver check (these 21 and 0.6.0 and
0.6.1): 44 lines change under 0.6.0 to 0.15.12 and 43 under 0.16.0 to 0.17.3, the difference being
`np.in1d`. All 23 names the pack rewrites are among them. Eighteen of the rest are names the pack
reports (the moved names, the five exceptions, `NINF`, `NZERO`, `PZERO`, `source`, `issubclass_`
and `issubsctype`), and two, `np.DTypePromotionError` and `np.INF`, are defined by no NumPy 1.26.4
main namespace. For the five exceptions ruff writes `from numpy.exceptions import AxisError` and
uses the bare name, which exists on NumPy 1.25 and later and not before. `np.RankWarning` is an
unsafe fix, which `--fix-only` does not apply.

The same run showed what `--fix-only` leaves alone, which the pack therefore does not claim:
`np.in1d`, `np.trapz`, `np.asfarray`, `np.cast`, `np.find_common_type` and the rest of the
`flag_only` names have no fix, and the fix for `np.source` (`inspect.getsource`) and for
`np.issubclass_` (`issubclass`) are not the same call. `NINF` and `NZERO` are fixed, but as
`-np.inf` and `-0.0` written in place: `np.NINF ** 2` (`inf`) becomes `-np.inf ** 2` (`-inf`), and
`np.NZERO.hex()` becomes `-0.0.hex()`, a `TypeError`. The parse gate passes both, so they are
reported and not claimed.

---

## ruff-npy201

- NumPy 2.0 migration guide, *Ruff plugin*: "Many of the changes covered in the 2.0 release notes
  and in this migration guide can be automatically adapted in downstream code with a dedicated Ruff
  rule, namely rule NPY201." The rule's own page: "With the exception of renaming
  `numpy.byte_bounds` to `numpy.lib.array_utils.byte_bounds`, all such replacements are backwards
  compatible with earlier versions of NumPy."
- NumPy 2.0 migration guide, *Main namespace*, the table of removed members: "float_: Use np.float64
  instead", "complex_: Use np.complex128 instead", "cfloat: Use np.complex128 instead",
  "longfloat: Use np.longdouble instead", "longcomplex: Use np.clongdouble instead", "clongfloat:
  Use np.clongdouble instead", "singlecomplex: Use np.complex64 instead", "string_: Use np.bytes_
  instead", "unicode_: Use np.str_ instead", "alltrue: Use np.all instead", "sometrue: Use np.any
  instead", "cumproduct: Use np.cumprod instead", "product: Use np.prod instead", "round_: Use
  np.round instead", "mat: Use np.asmatrix instead", "Inf", "Infinity", "infty", "PINF: Use np.inf
  instead", "NaN: Use np.nan instead", "safe_eval: Use ast.literal_eval instead". And its table of
  deprecated members: "row_stack: Use np.vstack instead (row_stack was an alias for vstack)".
- NumPy 2.0.0 release notes: "Alias np.float_ has been removed. Use np.float64 instead", and the
  same sentence for `complex_`, `longfloat`, `singlecomplex`, `cfloat`, `longcomplex`,
  `clongfloat`, `string_`, `unicode_`, `Inf`, `Infinity`, `NaN`, `infty` and `mat`; "Alias
  np.row_stack has been deprecated. Use np.vstack directly."
- Measured: see above. `NAN` is in no table of the guide; it is the alias of `nan` on 1.26.4 (the
  same object) and absent from 2.0.2, and ruff's rule lists it.
- What the proof adds, and why a tool is not trusted on its word: ruff adds imports where its
  replacement is not in the module (`from ast import literal_eval` for `safe_eval`), which the
  fixer rule allows as the only line it may add; it leaves `from numpy import float_` standing and
  adds `float64` beside it, which the scan of its output shows is not migrated.

## flag-moved-names

- NumPy 2.0 migration guide, *Main namespace*: "add_docstring: It's still available as
  np.lib.add_docstring", "add_newdoc: It's still available as np.lib.add_newdoc", "byte_bounds: Now
  it's available under np.lib.array_utils.byte_bounds", "compare_chararrays: It's still available as
  np.char.compare_chararrays", "DataSource: It's still available as np.lib.npyio.DataSource",
  "format_parser: It's still available as np.rec.format_parser", "tracemalloc_domain: It's now
  available from np.lib". The guide's "charrarray: It's still available as np.char.chararray" is a
  misspelling of `chararray`.
- NumPy 2.0.0 release notes: "Warnings and exceptions present in numpy.exceptions (e.g,
  ComplexWarning, VisibleDeprecationWarning) are no longer exposed in the main namespace." The
  guide's tables do not list them.
- Measured: each of those exists on 1.26.4 and on neither 2.0.2 nor later, except `chararray`, which
  is defined on 1.26.4 and 2.0.2 and gone on 2.5.4, with `numpy.char.chararray` on all three.
  `numpy.RankWarning` is gone on 2.0.2 and later, and `numpy.exceptions.RankWarning` exists on
  2.0.2 and 2.5.4 and not on 1.26.4. The other five exceptions are in `numpy.exceptions` on all
  three, and in the main namespace on 1.26.4 only.

## flag-removed-names

- NumPy 2.0 migration guide, *Main namespace*, the tables of removed and deprecated members, for
  each of the names listed, among them "in1d: Use np.isin instead" and "trapz: Use np.trapezoid or a
  scipy.integrate function instead".
- NumPy 2.4.0 release notes: "Removed numpy.in1d: numpy.in1d has been deprecated since NumPy 2.0
  and is now removed in favor of numpy.isin", and "numpy.trapz: deprecated since NumPy 2.0. Use
  numpy.trapezoid or scipy.integrate functions instead."
- NumPy 2.0.0 release notes: "np.numarray, np.oldnumeric" among the "expired members and functions"
  removed from the main namespace.
- Measured: `in1d` and `trapz` exist on 1.26.4, 2.0.2 and 2.3.5 and not on 2.4.0 or later. The rest
  exist on 1.26.4 and not on 2.0.2. `numpy.msort` is none of the guide's tables; NumPy 1.26.4's own
  warning says "msort is deprecated, use np.sort(a, axis=0) instead", and the two gave equal arrays
  for the one tried, so the suggestion is that. `numpy.numarray` and `numpy.oldnumeric` are the
  string `'removed'` on 1.26.4.

## flag-internal-constants

- NumPy 2.0 migration guide, *Main namespace*: "Finally, a set of internal enums has been removed.
  As they weren't used in downstream libraries we don't provide any information on how to replace
  them": FLOATING_POINT_SUPPORT, FPE_DIVIDEBYZERO, FPE_INVALID, FPE_OVERFLOW, FPE_UNDERFLOW,
  UFUNC_BUFSIZE_DEFAULT, UFUNC_PYVALS_NAME, CLIP, WRAP, RAISE, BUFSIZE, ALLOW_THREADS, MAXDIMS,
  MAY_SHARE_EXACT, MAY_SHARE_BOUNDS.
- NumPy 2.0.0 release notes: "Multiple niche enums, expired members and functions have been removed
  from the main namespace, such as: ERR_*, SHIFT_*, np.fastCopyAndTranspose, ...".
- Measured: all 26 (the fifteen, the seven `ERR_*` and the four `SHIFT_*`) exist on 1.26.4 and on
  neither 2.0.2 nor 2.5.4. The release notes say np.geterrobj and np.seterrobj are replaced by
  np.errstate, which is all the suggestion claims.

## flag-signed-constants

- NumPy 2.0 migration guide, *Main namespace*: "NINF: Use -np.inf instead", "NZERO: Use -0.0
  instead", "PZERO: Use 0.0 instead".
- Measured with ruff 0.16.8: `np.NINF ** 2` becomes `-np.inf ** 2`, `np.NINF.real` becomes
  `-np.inf.real` and `np.NZERO.hex()` becomes `-0.0.hex()`. On CPython 3.12 `(-math.inf) ** 2` is
  `inf` and `-math.inf ** 2` is `-inf`, and `-0.0.hex()` raises `TypeError`.

## dependency

- NumPy 2.0 migration guide, the introduction: "This document contains a set of instructions on how
  to update your code to work with NumPy 2.0." The pin follows the code, and only when every place
  in the repository has moved.
- Measured: `Requires-Python` of numpy 2.0.0 on PyPI is `>=3.9`; 2.1 and 2.2 ask for `>=3.10`, 2.3
  and 2.4 for `>=3.11`, so `to.requires_python` is the set a release of `>=2` installs on.
- Which requirement moves: only one that excludes NumPy 2 (`numpy==1.26.4`, `numpy<2`,
  `numpy~=1.22`), to `numpy>=2`. The code the pack writes runs on 1.26.4 and on 2.x (measured above),
  so a requirement that admits NumPy 2 (`numpy>=1.22`, `numpy>=1.22,<3`, `numpy`) has nothing to
  move, and its floor is not raised. A requirement with an environment marker is reported: NumPy
  2.0 has no release for Python 3.8, so `numpy>=2; python_version < '3.9'` could not be installed.
