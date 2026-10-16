"""What the PyPDF2 pack claims about the two projects, checked against both installed.

PyPDF2 3.0.1 and pypdf 6.19.0 are pinned in the dev group because these facts are about those
releases; each is a name, a member or a parameter, read from the module and never from a PDF. The
weekly job runs the file on the newest pypdf as well.
"""

from __future__ import annotations

import decimal
import importlib
import inspect
import io
import warnings
from collections.abc import Callable
from importlib.metadata import metadata, version
from typing import Any, cast

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from obelize.models import bounds
from obelize.packs import loader, schema

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import pypdf
    import PyPDF2

BUNDLED_ID = "py-pdf/pypdf2-to-pypdf"
BUNDLED = loader.load(BUNDLED_ID)
PACK = BUNDLED.pack
REMOVED = next(
    change.params
    for change in PACK.changes
    if change.id == "flag-removed-names" and isinstance(change, schema.FlagOnlyChange)
)
RENAME = next(change.params for change in PACK.changes if change.kind == "rename_import")
FLAGGED = {
    symbol
    for change in PACK.changes
    if isinstance(change, schema.FlagOnlyChange)
    for symbol in change.params.symbols
}


def _resolve(root: str, path: str) -> Any:
    """`Name`, or `<submodule>.Name`, on `root` (`PyPDF2` or `pypdf`)."""
    owner, _, name = path.rpartition(".")
    module = importlib.import_module(f"{root}.{owner}" if owner else root)
    return getattr(module, name)


def _kind(thing: Any) -> str:
    return "class" if inspect.isclass(thing) else "function"


def _defined(module: Any, root: str) -> set[str]:
    """The classes and functions `module` defines itself, not the ones it imports."""
    return {
        name
        for name, thing in vars(module).items()
        if not name.startswith("_")
        and (inspect.isclass(thing) or inspect.isfunction(thing))
        and getattr(thing, "__module__", "").startswith(root)
    }


def test_the_pack_is_the_migration_the_history_page_describes() -> None:
    assert PACK.from_.package == "PyPDF2"
    assert PACK.to.package == "pypdf"
    assert PACK.match.imports == ("PyPDF2",)
    assert PACK.match.prefilter_tokens == ("PyPDF2",)
    assert (RENAME.from_module, RENAME.to_module) == ("PyPDF2", "pypdf")


def test_the_installed_projects_are_inside_the_ranges_the_pack_was_measured_on() -> None:
    assert version("PyPDF2") in SpecifierSet(PACK.from_.version)
    assert version("pypdf") in SpecifierSet(PACK.to.version)
    assert version("PyPDF2") == "3.0.1"
    assert bounds(SpecifierSet(PACK.to.version))[0] == Version("6.19")


def test_the_newest_release_named_is_the_one_installed_and_it_lacks_the_removed_names() -> None:
    """What an unversioned requirement installs is a claim about PyPI; the weekly job checks it."""
    assert PACK.from_.newest == version("PyPDF2")
    removed = {
        symbol
        for change in PACK.changes
        if change.id == "flag-removed-names" and isinstance(change, schema.FlagOnlyChange)
        for symbol in change.params.symbols
    }
    assert removed
    assert set(PACK.from_.lacks) == removed
    assert set(PACK.from_.lacks) <= FLAGGED


def test_the_python_the_pack_requires_is_what_the_new_project_declares() -> None:
    assert metadata("pypdf")["Requires-Python"] == PACK.to.requires_python


@pytest.mark.parametrize("key", sorted(RENAME.symbol_map))
def test_a_mapped_name_is_the_same_kind_of_thing_on_both_sides(key: str) -> None:
    target = RENAME.symbol_map[key]
    assert target == key.rpartition(".")[2], "a rename is not an identity: this pack has none"
    assert _kind(_resolve("PyPDF2", key)) == _kind(_resolve("pypdf", key))


def test_every_submodule_the_pack_moves_exists_on_both_sides() -> None:
    for name, target in RENAME.submodule_map.items():
        assert importlib.import_module(f"PyPDF2.{name}") is not None
        assert importlib.import_module(target) is importlib.import_module(f"pypdf.{name}")


def test_every_name_pypdf2_defines_is_mapped_or_reported() -> None:
    for module, owner in ((PyPDF2, ""), (PyPDF2.errors, "errors"), (PyPDF2.generic, "generic")):
        here = f"{owner}." if owner else ""
        defined = {f"{here}{name}" for name in _defined(module, "PyPDF2")}
        classes = {name for name in defined if inspect.isclass(_resolve("PyPDF2", name))}
        mapped = {key for key in RENAME.symbol_map if key.rpartition(".")[0] == owner}
        flagged = {
            name
            for name in (symbol.removeprefix("PyPDF2.") for symbol in FLAGGED)
            if name.rpartition(".")[0] == owner
        }
        assert classes <= mapped | flagged, sorted(classes - mapped - flagged)
        assert mapped <= defined, sorted(mapped - defined)


def test_a_mapped_name_is_defined_on_pypdf_and_a_reported_one_no_longer_is() -> None:
    for key in RENAME.symbol_map:
        _resolve("pypdf", key)
    for name in FLAGGED:
        relative = name.removeprefix("PyPDF2.")
        assert _resolve("PyPDF2", relative)
        with pytest.raises(AttributeError):
            _resolve("pypdf", relative)


@pytest.mark.parametrize("name", ["PdfFileReader", "PdfFileWriter", "PdfFileMerger"])
def test_a_camel_case_class_raises_on_the_version_the_pack_migrates_from(name: str) -> None:
    """Which is why it is reported: code naming it is already broken on PyPDF2 3."""
    with pytest.raises(PyPDF2.errors.DeprecationError, match=r"removed in PyPDF2 3\.0\.0"):
        getattr(PyPDF2, name)()
    assert f"PyPDF2.{name}" in FLAGGED


def _warns(call: Any) -> bool:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        call()
    return bool(caught)


def _writer_with_a_page(root: Any) -> Any:
    writer = root.PdfWriter()
    writer.add_blank_page(595.276, 841.89)
    return writer


def _pdf(root: Any, pages: int = 2) -> io.BytesIO:
    writer = root.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(595.276, 841.89)
    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    return buffer


def test_the_limitation_about_what_pypdf_lacks_is_what_the_two_do() -> None:
    """Out of the pack's reach (the engine follows no object); `limitations` names each."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        old = _writer_with_a_page(PyPDF2)
    assert not _warns(lambda: old.set_page_mode("/UseNone"))
    assert _warns(lambda: PyPDF2.PdfWriter().encrypt(user_pwd="x"))  # noqa: S106 - a probe
    assert _warns(lambda: old.get_page(pageNumber=0))
    assert _warns(lambda: old.pages[0].extract_text(Tj_sep=""))
    new = _writer_with_a_page(pypdf)
    assert not hasattr(new, "set_page_mode")
    assert "user_pwd" not in inspect.signature(new.encrypt).parameters
    assert "pageNumber" not in inspect.signature(new.get_page).parameters
    assert "Tj_sep" not in inspect.signature(new.pages[0].extract_text).parameters
    text = " ".join(PACK.limitations)
    for named in ("set_page_mode", "user_pwd", "pageNumber", "Tj_sep"):
        assert named in text


def test_a_writer_given_a_file_or_a_reader_holds_nothing_then_the_whole_of_it() -> None:
    """The limitation about `PdfWriter(path)`: the same call, a different object."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert len(PyPDF2.PdfWriter(_pdf(PyPDF2)).pages) == 0
        reader: Any = PyPDF2.PdfReader(_pdf(PyPDF2))  # PyPDF2 types the argument as a file
        assert len(PyPDF2.PdfWriter(reader).pages) == 0
    assert len(pypdf.PdfWriter(_pdf(pypdf)).pages) == 2
    assert len(pypdf.PdfWriter(pypdf.PdfReader(_pdf(pypdf))).pages) == 2
    assert "PdfWriter(path)" in " ".join(PACK.limitations)


def _page_drawing_two_words() -> io.BytesIO:
    """One page whose content draws Hello, moves 40 units right and draws World, built in memory."""
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(595.276, 841.89)
    font = pypdf.generic.DictionaryObject(
        {
            pypdf.generic.NameObject("/Type"): pypdf.generic.NameObject("/Font"),
            pypdf.generic.NameObject("/Subtype"): pypdf.generic.NameObject("/Type1"),
            pypdf.generic.NameObject("/BaseFont"): pypdf.generic.NameObject("/Helvetica"),
        }
    )
    page[pypdf.generic.NameObject("/Resources")] = pypdf.generic.DictionaryObject(
        {
            pypdf.generic.NameObject("/Font"): pypdf.generic.DictionaryObject(
                {pypdf.generic.NameObject("/F1"): font}
            )
        }
    )
    stream = pypdf.generic.DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Hello) Tj 40 0 Td (World) Tj ET")
    # Typed for a parsed content stream; any stream object is accepted.
    page.replace_contents(cast("Any", stream))
    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    return buffer


def test_extract_text_spaces_the_pieces_of_a_line_differently_on_a_valid_file() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        old = PyPDF2.PdfReader(_page_drawing_two_words()).pages[0].extract_text()
    new = pypdf.PdfReader(_page_drawing_two_words()).pages[0].extract_text()
    assert (old, new) == ("HelloWorld", "Hello World")
    assert "extract_text puts different whitespace" in " ".join(PACK.limitations)


def test_page_boxes_and_float_objects_change_numeric_type() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        old_width = PyPDF2.PdfReader(_pdf(PyPDF2)).pages[0].mediabox.width
    new_width = pypdf.PdfReader(_pdf(pypdf)).pages[0].mediabox.width
    assert isinstance(old_width, decimal.Decimal)
    assert isinstance(new_width, float)
    assert issubclass(PyPDF2.generic.FloatObject, decimal.Decimal)
    assert issubclass(pypdf.generic.FloatObject, float)
    assert "decimal.Decimal" in " ".join(PACK.limitations)


# What the suggestion of `flag-removed-names` names, as a call on a reader, a writer and a page.
CAMEL_CASE: dict[str, Callable[[Any, Any, Any], object]] = {
    "getPage": lambda reader, writer, page: reader.getPage(0),
    "numPages": lambda reader, writer, page: reader.numPages,
    "getNumPages": lambda reader, writer, page: reader.getNumPages(),
    "mediaBox": lambda reader, writer, page: page.mediaBox,
    "addPage": lambda reader, writer, page: writer.addPage(page),
    "mergePage": lambda reader, writer, page: page.mergePage(page),
    "scaleBy": lambda reader, writer, page: page.scaleBy(2),
    "extractText": lambda reader, writer, page: page.extractText(),
    "rotateCounterClockwise": lambda reader, writer, page: page.rotateCounterClockwise(90),
    "removeImages": lambda reader, writer, page: writer.removeImages(),
    "removeText": lambda reader, writer, page: writer.removeText(),
}


@pytest.mark.parametrize("name", CAMEL_CASE)
def test_a_camel_case_member_the_suggestion_names_raises_on_the_version_the_pack_migrates_from(
    name: str,
) -> None:
    reader = PyPDF2.PdfReader(_pdf(PyPDF2))
    with pytest.raises(PyPDF2.errors.DeprecationError, match=r"removed in PyPDF2 3\.0\.0"):
        CAMEL_CASE[name](reader, PyPDF2.PdfWriter(), reader.pages[0])
    assert name in REMOVED.suggestion


def test_the_replacements_the_suggestion_names_exist_in_pypdf() -> None:
    reader = pypdf.PdfReader(_pdf(pypdf))
    page = reader.pages[0]
    writer = pypdf.PdfWriter()
    named = {
        "pages": reader,
        "mediabox": page,
        "extract_text": page,
        "merge_page": page,
        "scale_by": page,
        "rotate": page,
        "add_page": writer,
        "append": writer,
        "merge": writer,
    }
    assert all(hasattr(owner, name) and name in REMOVED.suggestion for name, owner in named.items())
    assert "strict=True" in REMOVED.suggestion
    assert inspect.signature(pypdf.PdfReader).parameters["strict"].default is False


def test_the_names_the_limitations_say_pypdf_changed_are_the_ones_it_has() -> None:
    """What a rename by name alone gets wrong: a move of position, of keyword or of meaning."""
    fourth = [
        list(inspect.signature(method).parameters)[4]
        for method in (
            PyPDF2.PageObject.mergeTranslatedPage,
            pypdf.PageObject.merge_translated_page,
        )
    ]
    assert fourth == ["expand", "over"]
    assert "the fourth positional of merge*Page is over, not expand" in REMOVED.suggestion
    parameters = {
        name: set(inspect.signature(getattr(pypdf.PdfWriter, name)).parameters)
        for name in ("append", "merge", "remove_images", "remove_text", "encrypt")
    }
    assert {"outline_item", "import_outline"} <= parameters["append"] & parameters["merge"]
    assert "to_delete" in parameters["remove_images"]
    assert "font_names" in parameters["remove_text"]
    assert {"user_password", "owner_password"} <= parameters["encrypt"]
    text = " ".join(PACK.limitations)
    for named in ("outline_item", "import_outline", "font_names", "to_delete", "user_password"):
        assert named in text
