"""What the three packs of the Python itself claim, checked against the Python running this file.

None of them has a distribution to install and pin, so the facts are read from the interpreter: a
timestamp, a name the standard library defines or no longer does, a class and its base. CI runs the
suite on every Python from 3.12 to 3.15, so each claim is held on each; one that only a release
before them can show was measured by hand and is in the pack's SOURCES.md.
"""

from __future__ import annotations

import datetime
import importlib
import importlib.metadata
import importlib.resources
import random
import sys
import warnings
from typing import Any

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from obelize.models import bounds
from obelize.packs import loader, schema

DATETIME = loader.load("python/datetime-utcnow").pack
PKG_RESOURCES = loader.load("setuptools/pkg-resources-to-importlib").pack
REMOVED = loader.load("python/removed-stdlib-modules").pack
UTC = datetime.UTC
THIS = Version(".".join(map(str, sys.version_info[:3])))


def _flagged(pack: schema.PackDocument) -> set[str]:
    return {
        symbol
        for change in pack.changes
        if isinstance(change, schema.FlagOnlyChange)
        for symbol in change.params.symbols
    }


def _old(timestamp: Any) -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            return datetime.datetime.utcfromtimestamp(timestamp)
        except (OverflowError, OSError, ValueError) as error:
            return type(error)


def _new(timestamp: Any) -> Any:
    try:
        return datetime.datetime.fromtimestamp(timestamp, UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError) as error:
        return type(error)


def test_the_datetime_pack_is_the_deprecation_the_documentation_dates() -> None:
    assert (DATETIME.from_.python, DATETIME.to.python) == (">=3.12", ">=3.2")
    assert (DATETIME.from_.package, DATETIME.to.package) == (None, None)
    assert DATETIME.match.imports == ("datetime",)
    assert DATETIME.match.symbols == (
        "datetime.datetime.utcfromtimestamp",
        "datetime.datetime.utcnow",
    )
    assert DATETIME.to_modules() == ("datetime", "datetime.timezone")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="deprecated in 3.12")
def test_both_calls_warn_from_python_3_12_and_still_exist() -> None:
    for call, argument in (
        (datetime.datetime.utcnow, ()),
        (datetime.datetime.utcfromtimestamp, (0,)),
    ):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            call(*argument)


def test_the_timestamp_gives_the_same_naive_value_class_and_error_either_way() -> None:
    """Values, the class of the result, and the exception for what the platform cannot convert."""
    edges = [0, 1, -1, 1.5, -1.5, 1e9, 1700000000.123456, 1700000000.9999995, -1700000000.123456]
    edges += [253402300799, 253402300800, -62135596800, 2**31, 2**32, -(2**31), 1e20, float("inf")]
    random.seed(1)
    spread = [random.uniform(-1e10, 1e11) for _ in range(2000)]  # noqa: S311 - a seeded spread
    for timestamp in [*edges, *spread]:
        old, new = _old(timestamp), _new(timestamp)
        assert old == new, timestamp
        assert type(old) is type(new), timestamp
        if isinstance(old, datetime.datetime):
            assert old.tzinfo is None


def test_a_subclass_keeps_its_class_through_the_new_spelling() -> None:
    class Moment(datetime.datetime):
        pass

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old = [Moment.utcnow(), Moment.utcfromtimestamp(0)]
    new = [Moment.now(UTC).replace(tzinfo=None), Moment.fromtimestamp(0, UTC).replace(tzinfo=None)]
    assert [type(one) for one in old] == [type(one) for one in new] == [Moment, Moment]


def test_now_alone_is_aware_and_cannot_be_compared_with_the_naive_value() -> None:
    """Why the new spelling drops the zone: an aware value is another type of datetime."""
    aware, naive = datetime.datetime.now(UTC), datetime.datetime.now(UTC).replace(tzinfo=None)
    assert aware.tzinfo is not None
    assert naive.tzinfo is None
    with pytest.raises(TypeError):
        aware - naive
    with pytest.raises(TypeError):
        aware < naive  # noqa: B015 - the comparison is what raises


def test_the_pkg_resources_pack_is_the_removal_the_changelog_dates() -> None:
    assert (PKG_RESOURCES.from_.package, PKG_RESOURCES.from_.version) == ("setuptools", "<82")
    assert (PKG_RESOURCES.to.package, PKG_RESOURCES.to.python) == (None, ">=3.10")
    assert PKG_RESOURCES.match.imports == ("pkg_resources",)
    assert bounds(SpecifierSet(PKG_RESOURCES.to.python or ""))[0] == Version("3.10")


def test_the_names_the_pkg_resources_pack_matches_are_the_ones_it_flags() -> None:
    assert _flagged(PKG_RESOURCES) == set(PKG_RESOURCES.match.symbols)


def test_the_replacements_the_pkg_resources_pack_names_exist() -> None:
    metadata, resources = importlib.metadata, importlib.resources
    for name in ("version", "distribution", "distributions", "entry_points"):
        assert callable(getattr(metadata, name)), name
    for name in ("files", "as_file"):
        assert callable(getattr(resources, name)), name
    assert metadata.entry_points(group="console_scripts") is not None
    assert isinstance(metadata.PackageNotFoundError("x"), ModuleNotFoundError)


def test_a_distribution_that_is_not_installed_raises_the_error_the_pack_names() -> None:
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.version("a-distribution-nobody-installed")


def test_an_importlib_entry_point_has_no_require_or_resolve() -> None:
    """The flag says so; the guide of importlib_metadata says the rest: a pkg_resources entry point
    validates when read, and its load() checks the extras."""
    entry = next(iter(importlib.metadata.entry_points(group="console_scripts")), None)
    if entry is None:
        pytest.skip("no console script is installed to read")
    for name in ("name", "value", "group", "dist", "load"):
        assert hasattr(entry, name), name
    for name in ("require", "resolve"):
        assert not hasattr(entry, name), name


def test_what_files_returns_reads_as_the_flag_says() -> None:
    root = importlib.resources.files("importlib")
    for name in ("read_bytes", "read_text", "open", "is_file", "is_dir", "iterdir"):
        assert hasattr(root, name), name
    with importlib.resources.as_file(root / "__init__.py") as path:
        assert path.is_file()


# Where each module of the removed-modules pack left the standard library: the pack's `from.python`
# is the earliest of them, and the replacements it names exist on the Python running this file.
REMOVED_IN = {
    "aifc": (3, 13),
    "asynchat": (3, 12),
    "asyncore": (3, 12),
    "audioop": (3, 13),
    "cgi": (3, 13),
    "cgitb": (3, 13),
    "distutils": (3, 12),
    "imghdr": (3, 13),
    "lib2to3": (3, 13),
    "mailcap": (3, 13),
    "msilib": (3, 13),
    "nntplib": (3, 13),
    "ossaudiodev": (3, 13),
    "pipes": (3, 13),
    "smtpd": (3, 12),
    "sndhdr": (3, 13),
    "spwd": (3, 13),
    "sunau": (3, 13),
    "telnetlib": (3, 13),
    "xdrlib": (3, 13),
}


def test_the_removed_modules_pack_matches_exactly_the_modules_it_knows_the_removal_of() -> None:
    assert set(REMOVED.match.imports) == set(REMOVED_IN)
    assert bounds(SpecifierSet(REMOVED.from_.python or ""))[0] == Version(
        ".".join(map(str, min(REMOVED_IN.values())))
    )
    assert (REMOVED.from_.package, REMOVED.to.package) == (None, None)


@pytest.mark.parametrize("module", sorted(REMOVED_IN))
def test_a_module_is_in_the_standard_library_until_the_release_that_removed_it(module: str) -> None:
    assert (module in sys.stdlib_module_names) is (sys.version_info[:2] < REMOVED_IN[module])


def test_no_module_left_out_of_the_pack_is_one_a_token_could_tell_from_a_word() -> None:
    """`imp`, `uu`, `nis`, `crypt` and `chunk` were removed too, and are words inside others."""
    for module in ("imp", "uu", "nis", "crypt", "chunk"):
        assert module not in REMOVED.match.imports
        assert any(module in word for word in ("import", "uuid", "finish", "encrypt", "chunk"))


@pytest.mark.skipif(sys.version_info >= (3, 13), reason="pipes was removed in 3.13")
def test_pipes_quote_is_shlex_quote_where_pipes_still_ships() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        pipes = importlib.import_module("pipes")
    shlex = importlib.import_module("shlex")
    assert pipes.quote is shlex.quote


def test_the_rename_is_the_only_one_and_what_it_names_exists() -> None:
    rename = next(change.params for change in REMOVED.changes if change.kind == "rename_import")
    assert (rename.from_module, rename.to_module, rename.symbol_map) == (
        "pipes",
        "shlex",
        {"quote": "quote"},
    )
    assert SpecifierSet(REMOVED.to.python or "").contains(THIS)
    assert callable(importlib.import_module(rename.to_module).quote)


def test_the_replacements_the_removed_modules_pack_names_exist() -> None:
    names = {
        "urllib.parse": ("parse_qs", "parse_qsl"),
        "email.message": ("Message",),
        "shutil": ("which",),
        "subprocess": ("run",),
        "sysconfig": ("get_paths",),
        "platform": ("platform",),
        "argparse": ("ArgumentParser",),
        "asyncio": ("start_server",),
    }
    for module, members in names.items():
        for member in members:
            assert hasattr(importlib.import_module(module), member), f"{module}.{member}"


def test_every_removed_name_the_pack_flags_is_under_a_module_it_matches() -> None:
    for symbol in _flagged(REMOVED):
        assert schema.under_any(symbol, REMOVED.match.imports), symbol
