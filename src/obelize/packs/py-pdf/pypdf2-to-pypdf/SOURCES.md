# Sources for `py-pdf/pypdf2-to-pypdf`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The retrieved page

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| History of pypdf (the pack's `source`) | <https://pypdf.readthedocs.io/en/stable/meta/history.html> | 2026-10-06 | `ff4e6b86b2feefe99d1faec468d7f2bcd0641769afe96da5f93ff5feb811e218` |

The hash is of the page body as served. obelize never requests the URL.

## The measurement, and why it outranks the page

"Measured" means checked against **PyPDF2 3.0.1** and **pypdf 6.19.0**
(also 3.17.4, 4.3.1 and 5.9.0 where a claim names them) installed on CPython
3.12, with PyPDF2 3.0.1 also imported on 3.13 and 3.14. The page says that the
two projects are one; it does not say which names moved, so the pack follows the
measurement.

The camelCase members that `flag-removed-names` points to were measured on the releases the code
that names them runs on as well, PyPDF2 1.26.0 and 2.12.1, each beside pypdf 6.19.0 in a clean
environment, since neither can share one with the PyPDF2 3.0.1 the unit tests import:

    uv run --isolated --no-project --python 3.12 --with PyPDF2==2.12.1 --with pypdf==6.19.0 \
        python -I tests/packs/pypdf_legacy_check.py

It prints each claim that does not hold and exits 1 if there is one; it holds on both releases and
fails on 3.0.1, whose camelCase members raise. The weekly job does not run it.

## The newest release

`from.newest` is `3.0.1`, and `from.lacks` is the three classes `flag-removed-names` reports and the
three modules `flag-removed-modules` reports.

| Source | URL | Checked | What it shows |
|---|---|---|---|
| The release list of PyPDF2 on PyPI | <https://pypi.org/pypi/PyPDF2/json> | 2026-10-15 | 3.0.1, uploaded 2022-12-31, is the last release; 3.0.0 and 3.0.1 are the only two in `>=3,<4`. |

Measured (see `flag-removed-names`): `PdfFileMerger`, `PdfFileReader` and `PdfFileWriter` each raise
`DeprecationError` when constructed on PyPDF2 3.0.1, which is what makes code that names one
evidence of an older release.
`tests/packs/test_pypdf_facts.py` holds `from.newest` equal to the installed PyPDF2 and `from.lacks`
equal to the names of both. The weekly end-to-end run reads the release list and
fails when a final release that is not yanked is newer than `from.newest`. obelize never requests the
URL.

---

## rename-import

- History of pypdf: "PyPDF2 was merged back into pypdf. Now all lowercase,
  without a number. [...] Compared to PyPDF2 >= 3.0.0, pypdf >= 3.1.0 now
  offers: AES reading and writing support."
- Measured: the names mapped to themselves are the classes and functions
  PyPDF2 defines at its top level (`PdfFileReader`, `PdfFileWriter`,
  `PdfFileMerger` and `PdfMerger` excepted) and the classes of `errors` and
  `generic` (`AnnotationBuilder` and `Bookmark` excepted), each defined in the
  same place of pypdf 6.19.0.
- Measured: all eight submodules (`constants`, `errors`, `filters`, `generic`,
  `pagerange`, `papersizes`, `types`, `xmp`) exist in both.
- Measured: `types` is the standard library's name for another module, so the
  submodule's alias falls back when the file already binds it.
- Measured: the same names are not the same behaviour, and each of these is out
  of this pack's reach because it is on an object:
  `PdfWriter("out.pdf")` and `PdfWriter(reader)` hold no page on PyPDF2 3.0.1
  and every page of the file on pypdf 6.19.0; `page.mediabox.width` and
  `generic.FloatObject` are `decimal.Decimal` on PyPDF2 3.0.1 and `float` on
  6.19.0; and pypdf 6.19.0 lacks `PdfWriter.set_page_mode`, the `user_pwd` and
  `owner_pwd` parameters of `PdfWriter.encrypt`, the `pageNumber` parameter of
  `PdfWriter.get_page` and the `Tj_sep` and `TJ_sep` parameters of
  `PageObject.extract_text`, which the last four of these warn about on 3.0.1.

## flag-removed-names

- Measured: on PyPDF2 3.0.1 on CPython 3.12, 3.13 and 3.14,
  `PyPDF2.PdfFileReader("x")` raises `DeprecationError: PdfFileReader is
  deprecated and was removed in PyPDF2 3.0.0. Use PdfReader instead.`, and
  `PdfFileMerger()` raises `DeprecationError` too. pypdf 6.19.0 defines none of
  the three.
- Measured: the camelCase members of PyPDF2 3.0.1's classes raise the same
  error (`PdfWriter.addBlankPage`, for one). Members cannot be reported without
  tracking the object, which this pack has no rule kind for, so only the three
  class names are, and the suggestion says what the members become.
- Measured on PyPDF2 3.0.1 (`tests/packs/test_pypdf_facts.py`): each camelCase
  member the suggestion names raises `DeprecationError`, and each replacement
  it names exists in pypdf 6.19.0.
- Measured on PyPDF2 1.26.0 and 2.12.1 (`tests/packs/pypdf_legacy_check.py`),
  with the same result on both unless a release is named: `getPage(i)` and
  `pages[i]` give the same page for 0, 2 and -1 and raise `IndexError` at 3;
  `numPages` and `getNumPages()` equal `len(reader.pages)`; `mediaBox` and
  `mediabox` read and set the same box; `addPage`, `addBlankPage`,
  `addMetadata`, `mergePage`, `scaleBy` and `scaleTo` take what their snake_case
  names take first, with the same defaults, and write the same pages.
- Measured, the same: `rotateClockwise(90)` sets `/Rotate` to 90 as `rotate(90)`
  does, and `rotateCounterClockwise(90)` sets -90 as `rotate(-90)` does, so
  `rotate(90)` turns the other way.
- Measured, the same: `PdfFileReader(f)` raises `PdfReadError` on a file whose
  `startxref` is wrong, `PdfReader(f)` opens it and `PdfReader(f, strict=True)`
  raises; `PdfFileMerger().append` raises on it and
  `PdfWriter(strict=True).append` does not. `PdfFileWriter()` and `PdfWriter()`
  are empty; `PdfWriter(path)` holds the pages of the file, and
  `PdfFileWriter(path)` is a `TypeError` on 1.26.0 and empty on 2.12.1.
- Measured, the same: the fourth positional of `mergeTranslatedPage` is `expand`
  and that of `merge_translated_page` is `over`, so `(page, 5, 6, True)` grows
  the page on PyPDF2 and does not on pypdf 6.
- Measured, the same: `removeImages()` keeps an inline image that
  `remove_images()` removes; `removeText(True)` and `removeImages(True)` run on
  PyPDF2 and `remove_text(True)` is a `TypeError`; `encrypt(user_pwd=,
  owner_pwd=)` runs on PyPDF2 and is a `TypeError` on pypdf 6; `write` returns
  a tuple on pypdf 6, and on PyPDF2 from 2.0 but not on 1.26.0, which returns
  `None`; the `bookmark` keyword of `PdfFileMerger.append` is a `TypeError` on
  `PdfWriter.append`, which takes `outline_item`.
- Measured, the same: `extractText()` reads `HelloWorld` and `extract_text()`
  reads `Hello World` for two pieces of a line 40 units apart.
- Not measured: AES encryption, the output of the `merge*Page` methods beyond
  the size of the page, and any file a person wrote rather than one built here.

## flag-removed-modules

- Measured on PyPDF2 1.26.0, 1.27.12, 1.28.0, 1.28.6, 2.0.0, 2.10.9, 2.12.1, 3.0.0 and 3.0.1, each
  installed on CPython 3.12 alone: `PyPDF2.pdf`, `PyPDF2.utils` and `PyPDF2.merger` import on the four
  1.x releases and on none from 2.0.0 on, so code that imports one ran on PyPDF2 1 and cannot run on
  3.0.1 or on pypdf 6. `PyPDF2.errors` exists from 1.27.12 and `PyPDF2.generic` on all of them.
- Measured: on 1.26.0, 1.27.12, 1.28.0 and 1.28.6 `PyPDF2.utils` defines `PdfReadError`,
  `PdfStreamError`, `PyPdfError`, `PageSizeNotDefinedError`, `PdfReadWarning`, `isString` and `b_`;
  the five classes are in `pypdf.errors` under the same name, and `isString` and `b_` are in no
  module of pypdf 6.19.0. `PyPDF2.pdf.PageObject` is `pypdf.PageObject`.
- `tests/packs/test_pypdf_facts.py` holds that none of the three imports on PyPDF2 3.0.1 or pypdf
  6.19.0 and that the suggestion names what exists. `tests/packs/pypdf_legacy_check.py` holds the
  rest on 1.26.0 and 2.12.1. The other releases were imported one by one by hand.
- A module is a prefix: `PyPDF2.utils.PdfReadError` and a call on `PyPDF2.pdf.PdfFileReader` are
  reported, and are what the version gate reads as code that cannot have run on 3.0.1. `from PyPDF2
  import utils` alone names no module the scan can tell from a name, so it is not reported.
- A file that names one of these three modules, or one of the three classes above, anywhere git
  lists, a notebook or a Python 2 file included, also counts for that gate.

## flag-names-pypdf-dropped

- Measured: `PdfMerger` is defined in PyPDF2 3.0.1, pypdf 3.17.4, 4.3.1 and
  5.9.0 and is absent from 6.19.0; `generic.Bookmark` is absent from 4.3.1 and
  `generic.AnnotationBuilder` from 6.19.0.

## flag-indirect-use

- A string target in a `mock.patch`, an `importlib.import_module` or a
  `sys.modules` stub names the old module and never meets an import statement.

## dependency

- History of pypdf, as above: the distribution is named `pypdf` from 3.1.0.
- Measured: `Requires-Python` is `>=3.6` for PyPDF2 3.0.1 and `>=3.9` for
  pypdf 6.19.0, and both are BSD-licensed.
- Measured (OSV, retrieved 2026-10-06): 97 advisories name pypdf 3.17.4, all
  denial of service on a crafted file and some rated high, with the first fixed
  release in the 6 line each time; none names 6.19.0. The pin is `>=6.19`
  for that reason.
