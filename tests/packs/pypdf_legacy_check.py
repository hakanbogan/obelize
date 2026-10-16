"""What `py-pdf/pypdf2-to-pypdf` says of the camelCase API, read from PyPDF2 1.26.0 or 2.12.1
beside pypdf 6.19.0.

Neither can share an environment with the PyPDF2 3.0.1 the unit tests import, so each runs in a
clean one, by hand. Standard library only, so nothing but the two projects is installed. It names
each claim that does not hold and exits 1 if there is one.

    uv run --isolated --no-project --python 3.12 --with PyPDF2==1.26.0 --with pypdf==6.19.0 \
        python -I tests/packs/pypdf_legacy_check.py
"""

from __future__ import annotations

import importlib
import inspect
import io
import sys
import warnings
from collections.abc import Callable
from typing import Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import pypdf
    import PyPDF2

# Both define names the installed stubs do not, so each is read untyped.
old: Any = PyPDF2
new: Any = pypdf
generic: Any = new.generic


def _pdf(content: bytes = b"") -> bytes:
    """Three pages, 100, 200 and 300 wide, the first drawing `content` in Helvetica; built by
    pypdf, read by both."""
    writer = new.PdfWriter()
    for width in (100, 200, 300):
        writer.add_blank_page(width, 400)
    if content:
        name = generic.NameObject
        font = generic.DictionaryObject(
            {name("/Type"): name("/Font"), name("/Subtype"): name("/Type1")}
            | {name("/BaseFont"): name("/Helvetica")}
        )
        fonts = generic.DictionaryObject({name("/F1"): font})
        writer.pages[0][name("/Resources")] = generic.DictionaryObject({name("/Font"): fonts})
        stream = generic.DecodedStreamObject()
        stream.set_data(content)
        writer.pages[0].replace_contents(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


GOOD = _pdf()
# The start of the cross-reference table is wrong, which only a strict reader refuses.
BROKEN = GOOD.replace(b"startxref\n", b"startxref\n9")
HELLO = _pdf(b"BT /F1 12 Tf 72 720 Td (Hello) Tj 40 0 Td (World) Tj ET")
INLINE = _pdf(b"q 10 0 0 10 0 0 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI Q")


def _file(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


def _page(data: bytes = GOOD, index: int = 0) -> tuple[Any, Any]:
    """The same page, read by the old reader and by the new one."""
    return old.PdfFileReader(_file(data)).getPage(index), new.PdfReader(_file(data)).pages[index]


def _fails(call: Callable[[], object]) -> str:
    """The name of the exception `call` raises, or an empty one."""
    try:
        call()
    except Exception as error:
        return type(error).__name__
    return ""


def _prefix(pairs: dict[str, str], was: Any, now: Any) -> bool:
    """Whether each legacy method takes the positions its replacement takes first, defaults too."""
    for before, after in pairs.items():
        legacy = list(inspect.signature(getattr(was, before)).parameters.values())[1:]
        current = list(inspect.signature(getattr(now, after)).parameters.values())[1:]
        if [(p.kind, p.default) for p in legacy] != [(p.kind, p.default) for p in current][
            : len(legacy)
        ]:
            return False
    return True


def _writers(data: bytes = GOOD) -> tuple[Any, Any]:
    """One writer of each, holding the first page of `data`."""
    before, after = old.PdfFileWriter(), new.PdfWriter()
    before.addPage(_page(data)[0])
    after.add_page(_page(data)[1])
    return before, after


def strict_reading() -> bool:
    """PdfFileReader reads a damaged file strictly, PdfReader only with strict=True."""
    return (
        _fails(lambda: old.PdfFileReader(_file(BROKEN))) == "PdfReadError"
        and len(new.PdfReader(_file(BROKEN)).pages) == 3
        and _fails(lambda: new.PdfReader(_file(BROKEN), strict=True)) == "PdfReadError"
    )


def empty_writers() -> bool:
    """PdfFileWriter() and PdfWriter() are empty; PdfWriter(path) holds the file's pages."""
    return (
        old.PdfFileWriter().getNumPages() == len(new.PdfWriter().pages) == 0
        and len(new.PdfWriter(_file(GOOD)).pages) == 3
        and _fails(lambda: old.PdfFileWriter(_file(GOOD)).getNumPages()) in {"TypeError", ""}
    )


def page_access() -> bool:
    """getPage(i) is pages[i]; numPages and getNumPages() are len(pages)."""
    reader, other = old.PdfFileReader(_file(GOOD)), new.PdfReader(_file(GOOD))
    return (
        all(
            reader.getPage(i).mediaBox.getWidth() == other.pages[i].mediabox.width
            for i in range(-1, 3)
        )
        and reader.numPages == reader.getNumPages() == len(other.pages) == 3
        and _fails(lambda: reader.getPage(3)) == _fails(lambda: other.pages[3]) == "IndexError"
    )


def boxes() -> bool:
    """mediaBox is mediabox, read and set."""
    before, after = _page()
    before.mediaBox = old.generic.RectangleObject([0, 0, 10, 20])
    after.mediabox = generic.RectangleObject([0, 0, 10, 20])
    return bool(
        before["/MediaBox"] == after["/MediaBox"]
        and before.mediaBox.getWidth() == after.mediabox.width == 10
    )


def rotation() -> bool:
    """rotateClockwise(a) is rotate(a); rotateCounterClockwise(a) is rotate(-a)."""
    results = []
    for was, angle in (("rotateClockwise", 90), ("rotateCounterClockwise", -90)):
        before, after = _page()
        getattr(before, was)(abs(angle))
        after.rotate(angle)
        results.append(before.get("/Rotate") == after.get("/Rotate") == angle)
    return all(results)


def renames() -> bool:
    """addPage, addBlankPage, addMetadata, mergePage, scaleBy and scaleTo take what their
    snake_case names take first, and give the same pages."""
    before, after = _writers()
    before.addBlankPage(10, 20)
    after.add_blank_page(10, 20)
    before.addMetadata({"/Title": "x"})
    after.add_metadata({"/Title": "x"})
    first, second = _page(), _page(GOOD, 1)
    first[0].mergePage(second[0])
    first[1].merge_page(second[1])
    first[0].scaleBy(2)
    first[1].scale_by(2)
    first[0].scaleTo(7, 9)
    first[1].scale_to(7, 9)
    files = (io.BytesIO(), io.BytesIO())
    before.write(files[0])
    after.write(files[1])
    read = old.PdfFileReader(files[0]), new.PdfReader(files[1])
    return (
        _prefix(
            {"addPage": "add_page", "addBlankPage": "add_blank_page"},
            old.PdfFileWriter,
            new.PdfWriter,
        )
        and _prefix({"addMetadata": "add_metadata"}, old.PdfFileWriter, new.PdfWriter)
        and _prefix(
            {"mergePage": "merge_page", "scaleBy": "scale_by", "scaleTo": "scale_to"},
            type(first[0]),
            new.PageObject,
        )
        and [read[0].numPages, len(read[1].pages)] == [2, 2]
        and read[0].getPage(1).mediaBox.getWidth() == read[1].pages[1].mediabox.width == 10
        and read[0].getDocumentInfo()["/Title"] == read[1].metadata["/Title"] == "x"
        and [round(float(x), 6) for x in first[0].mediaBox] == [0, 0, 7, 9]
        and [round(float(x), 6) for x in first[1].mediabox] == [0, 0, 7, 9]
    )


def text_spacing() -> bool:
    """extractText and extract_text space the pieces of a line differently."""
    return bool(
        _page(HELLO)[0].extractText() == "HelloWorld"
        and _page(HELLO)[1].extract_text() == "Hello World"
    )


def merge_expand() -> bool:
    """The fourth argument of merge*Page is expand, then over."""
    before, after = _page()
    before.mergeTranslatedPage(_page()[0], 5, 6, True)
    after.merge_translated_page(_page()[1], 5, 6, True)
    return bool(before.mediaBox.getWidth() == 105 and after.mediabox.width == 100)


def removals() -> bool:
    """removeImages leaves inline images and remove_images does not; removeText and removeImages
    take a flag, remove_text a list."""
    before, after = _writers(INLINE)
    kept = _fails(lambda: before.removeText(True)) + _fails(lambda: before.removeImages(True))
    before.removeImages()
    after.remove_images()
    return (
        b"BI" in before.getPage(0).getContents().getData()
        and b"BI" not in after.pages[0].get_contents().get_data()
        and kept == ""
        and _fails(lambda: after.remove_text(True)) == "TypeError"
        and _fails(lambda: after.remove_images(True)) == ""
    )


def merger() -> bool:
    """PdfFileMerger is strict and PdfWriter.append is not, and its keywords moved."""
    return (
        _fails(lambda: old.PdfFileMerger().append(_file(BROKEN))) == "PdfReadError"
        and _fails(lambda: new.PdfWriter(strict=True).append(_file(BROKEN))) == ""
        and _fails(lambda: new.PdfWriter().append(_file(GOOD), bookmark="x")) == "TypeError"
        and _fails(lambda: new.PdfWriter().append(_file(GOOD), outline_item="x")) == ""
        and list(inspect.signature(old.PdfFileMerger.append).parameters)[3]
        == list(inspect.signature(new.PdfWriter.append).parameters)[3]
        == "pages"
    )


def encryption() -> bool:
    """encrypt takes user_pwd and owner_pwd, then user_password and owner_password."""
    before, after = _writers()
    return (
        _fails(lambda: before.encrypt(user_pwd="a", owner_pwd="b")) == ""  # noqa: S106 - a probe
        and _fails(lambda: after.encrypt(user_pwd="a", owner_pwd="b")) == "TypeError"  # noqa: S106
        and _fails(lambda: after.encrypt("a", "b")) == ""
    )


def _import(name: str) -> str:
    return _fails(lambda: importlib.import_module(name))


def modules() -> bool:
    """PyPDF2.pdf, utils and merger import on 1.x and not from 2.0.0; what they hold is in pypdf."""
    results = [_import(f"PyPDF2.{name}") for name in ("pdf", "utils", "merger")]
    if not old.__version__.startswith("1."):
        return results == ["ModuleNotFoundError"] * 3
    names = ("PdfReadError", "PdfStreamError", "PyPdfError", "PageSizeNotDefinedError")
    classes = (*names, "PdfReadWarning")
    utils = importlib.import_module("PyPDF2.utils")
    return (
        results == [""] * 3
        and all(hasattr(utils, name) and hasattr(new.errors, name) for name in classes)
        and hasattr(importlib.import_module("PyPDF2.pdf"), "PageObject")
        and hasattr(new, "PageObject")
    )


def written() -> bool:
    """write returns a tuple on pypdf 6, and on PyPDF2 from 2.0."""
    before, after = _writers()
    return isinstance(after.write(io.BytesIO()), tuple) and (
        isinstance(before.write(io.BytesIO()), tuple) != old.__version__.startswith("1.")
    )


CHECKS = (
    strict_reading,
    empty_writers,
    page_access,
    boxes,
    rotation,
    renames,
    text_spacing,
    merge_expand,
    removals,
    merger,
    encryption,
    modules,
    written,
)


def main() -> int:
    failed = []
    for check in CHECKS:
        try:
            held = check()
        except Exception as error:
            held = False
            print(f"{error!r}", file=sys.stderr)
        if not held:
            failed.append(check.__doc__)
    for claim in failed:
        print(claim, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
