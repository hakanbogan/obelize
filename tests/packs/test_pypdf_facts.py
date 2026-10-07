"""What the PyPDF2 pack claims about the two projects, checked against both installed.

PyPDF2 3.0.1 and pypdf 6.19.0 are pinned in the dev group because these facts are about those
releases; each is a name, a member or a parameter, read from the module and never from a PDF.
"""

from __future__ import annotations

import decimal
import importlib
import inspect
import io
import warnings
from importlib.metadata import metadata, version
from typing import Any

import pytest
from packaging.specifiers import SpecifierSet

from obelize.packs import loader, schema

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import pypdf
    import PyPDF2

BUNDLED_ID = "py-pdf/pypdf2-to-pypdf"
BUNDLED = loader.load(BUNDLED_ID)
PACK = BUNDLED.pack
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


def test_the_installed_projects_are_the_ones_the_pack_was_measured_on() -> None:
    assert version("PyPDF2") in SpecifierSet(PACK.from_.version)
    assert version("pypdf") in SpecifierSet(PACK.to.version)
    assert version("PyPDF2") == "3.0.1"
    assert version("pypdf") == "6.19.0"


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
