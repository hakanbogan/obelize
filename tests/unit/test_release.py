"""What a release's METADATA says of its extras, read once its wheel is unpacked (ADR-077)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obelize import release

if TYPE_CHECKING:
    from pathlib import Path


def unpacked(root: Path, metadata: bytes | str, dist_info: str = "kit-2.0.dist-info") -> Path:
    folder = root / dist_info
    folder.mkdir(parents=True)
    data = metadata.encode() if isinstance(metadata, str) else metadata
    (folder / "METADATA").write_bytes(data)
    return root


def test_the_extras_are_the_provides_extra_headers_in_their_normal_form_sorted(
    tmp_path: Path,
) -> None:
    metadata = (
        "Metadata-Version: 2.3\nName: kit\nVersion: 2.0\n"
        "Provides-Extra: Dev_Tools\nProvides-Extra: cli\nprovides-extra: c.li\n"
        "Provides-Extra:   grpc  \nProvides-Extra: cli\nRequires-Dist: x ; extra == 'cli'\n"
    )
    assert release.provides_extras(unpacked(tmp_path, metadata)) == (
        "c-li",
        "cli",
        "dev-tools",
        "grpc",
    )


def test_only_the_headers_are_read_not_the_description_that_follows_them(tmp_path: Path) -> None:
    metadata = "Name: kit\nProvides-Extra: cli\n\nProvides-Extra: fake\n\nA README that says more."
    assert release.provides_extras(unpacked(tmp_path, metadata)) == ("cli",)


@pytest.mark.parametrize(
    "value", ["", "has space", "two words", "semi;colon", "-x", "x-", "über", "a/b", "[cli]"]
)
def test_a_name_that_is_no_extra_is_left_out_and_the_rest_are_kept(
    tmp_path: Path, value: str
) -> None:
    metadata = f"Name: kit\nProvides-Extra: {value}\nProvides-Extra: cli\n"
    assert release.provides_extras(unpacked(tmp_path, metadata)) == ("cli",)


def test_a_header_in_bytes_that_are_not_utf_8_is_still_read(tmp_path: Path) -> None:
    metadata = b"Name: k\xff\nSummary: \xe9\xe9\nProvides-Extra: cli\n"
    assert release.provides_extras(unpacked(tmp_path, metadata)) == ("cli",)


def test_a_release_that_lists_none_provides_none(tmp_path: Path) -> None:
    assert release.provides_extras(unpacked(tmp_path, "Name: kit\nVersion: 2.0\n")) == ()
    assert release.provides_extras(unpacked(tmp_path / "empty", "")) == ()


def test_nothing_is_read_unless_there_is_exactly_one_dist_info(tmp_path: Path) -> None:
    """A source distribution unpacks none, and a wheel holding two does not say which is its own."""
    assert release.provides_extras(tmp_path) == ()
    two = unpacked(tmp_path / "two", "Provides-Extra: cli\n")
    unpacked(two, "Provides-Extra: other\n", "vendored-1.dist-info")
    assert release.provides_extras(two) == ()


def test_a_metadata_file_deeper_in_the_wheel_is_not_its_own(tmp_path: Path) -> None:
    nested = tmp_path / "kit" / "data" / "kit-2.0.dist-info"
    nested.mkdir(parents=True)
    (nested / "METADATA").write_text("Provides-Extra: cli\n", encoding="utf-8")
    assert release.provides_extras(tmp_path) == ()


def test_no_more_than_the_limit_of_extras_are_kept_and_the_first_in_order_are(
    tmp_path: Path,
) -> None:
    names = [f"e{number:04d}" for number in range(release.MAX_EXTRAS + 5)]
    metadata = "".join(f"Provides-Extra: {name}\n" for name in reversed(names))
    found = release.provides_extras(unpacked(tmp_path, metadata))
    assert found == tuple(names[: release.MAX_EXTRAS])


def test_a_header_block_past_the_read_limit_is_cut_where_the_limit_falls(tmp_path: Path) -> None:
    filler = "X-Filler: " + "x" * 1000 + "\n"
    head = filler * (release.METADATA_BYTES // len(filler) + 1)
    metadata = "Provides-Extra: before\n" + head + "Provides-Extra: after\n"
    assert release.provides_extras(unpacked(tmp_path, metadata)) == ("before",)


@pytest.mark.parametrize("separator", [chr(0x0C), chr(0x85), chr(0x2028), chr(0x2029)])
def test_a_separator_inside_a_value_does_not_start_a_header(tmp_path: Path, separator: str) -> None:
    """`str.splitlines` ends a line at these; a header does not."""
    metadata = f"Name: kit\nSummary: a{separator}Provides-Extra: evil\nProvides-Extra: cli\n\n"
    assert release.provides_extras(unpacked(tmp_path, metadata)) == ("cli",)


def test_a_header_block_ending_in_carriage_returns_is_read_all_the_same(tmp_path: Path) -> None:
    metadata = (
        "Name: kit\r\nProvides-Extra: cli\r\nProvides-Extra: grpc\r\n\r\nProvides-Extra: no\r\n"
    )
    assert release.provides_extras(unpacked(tmp_path, metadata)) == ("cli", "grpc")
