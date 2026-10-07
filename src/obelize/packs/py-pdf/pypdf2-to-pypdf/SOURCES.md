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
  class names are.

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
