"""`obelize.index` and `obelize.release`: what an index lists, which file is read, and the hash."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from packaging.version import Version

import fakeindex
from obelize import index, release
from obelize.net import Cache, Fetcher, NetworkError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def served() -> Iterator[fakeindex.FakeIndex]:
    yield from fakeindex.FakeIndex().serve()


def _fetcher(served: fakeindex.FakeIndex, **kwargs: object) -> Fetcher:
    return Fetcher(index=served.url, **kwargs)  # type: ignore[arg-type]


# The project page.


def test_a_project_lists_its_files_with_the_hashes_the_index_gives(
    served: fakeindex.FakeIndex,
) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": "x = 1\n"})
    served.add("acme-kit", "2.0", {"__init__.py": "x = 2\n"}, kind="sdist")
    found = index.project(_fetcher(served), "Acme_Kit")
    assert found.name == "acme-kit"
    assert found.versions == (Version("1.0"), Version("2.0"))
    first, second = found.files
    assert (first.kind, second.kind) == ("wheel", "sdist")
    assert first.pure is True
    assert len(first.sha256) == 64
    assert first.url == f"{served.origin}/files/{first.filename}"
    assert served.asked == ["/simple/acme-kit/"]


def test_an_index_url_may_end_in_simple_or_not() -> None:
    assert index.simple_root("https://pypi.org") == "https://pypi.org/simple"
    assert index.simple_root("https://pypi.org/") == "https://pypi.org/simple"
    assert (
        index.simple_root("https://example.com/root/simple/") == "https://example.com/root/simple"
    )


def test_a_project_the_index_does_not_have_is_not_found(served: fakeindex.FakeIndex) -> None:
    with pytest.raises(NetworkError) as raised:
        index.project(_fetcher(served), "nothing-here")
    assert raised.value.reason == "not_found"


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"files": 3}', b"[" * 100_000])
def test_a_page_that_is_not_a_project_page_is_refused(
    served: fakeindex.FakeIndex, body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": ""})
    monkeypatch.setattr(served, "_page", lambda _project: body)
    with pytest.raises(NetworkError) as raised:
        index.project(_fetcher(served), "acme-kit")
    assert raised.value.reason == "refused"


def test_a_file_without_a_hash_or_a_known_name_is_left_out(
    served: fakeindex.FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = (
        b'{"files": ['
        b'{"filename": "ok-1.0-py3-none-any.whl", "url": "/f/ok", "hashes": {"sha256": "AA"}},'
        b'{"filename": "nohash-1.0-py3-none-any.whl", "url": "/f/n", "hashes": {}},'
        b'{"filename": "nourl-1.0-py3-none-any.whl", "hashes": {"sha256": "bb"}},'
        b'{"filename": "ok-1.0.egg", "url": "/f/e", "hashes": {"sha256": "cc"}},'
        b'{"filename": "bad-name.whl", "url": "/f/b", "hashes": {"sha256": "dd"}},'
        b'{"filename": "x-1.0.tar.gz", "url": "/f/x", "hashes": {"sha256": "ee"}},'
        b'"not an entry"]}'
    )
    served.add("ok", "1.0", {"__init__.py": ""})
    monkeypatch.setattr(served, "_page", lambda _project: page)
    found = index.project(_fetcher(served), "ok")
    assert [one.filename for one in found.files] == ["ok-1.0-py3-none-any.whl", "x-1.0.tar.gz"]
    assert found.files[0].sha256 == "aa"


def test_a_withdrawn_release_is_known_and_never_chosen(served: fakeindex.FakeIndex) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": ""})
    served.add("acme-kit", "2.0", {"__init__.py": ""}, yanked="broken")
    served.add("acme-kit", "2.1", {"__init__.py": ""}, yanked="")
    found = index.project(_fetcher(served), "acme-kit")
    assert [one.yanked for one in found.files] == [None, "broken", ""]
    assert found.newest() == Version("1.0")
    assert found.choose(Version("2.0")) is None


# Which release and which file.


def _project(*names: tuple[str, str | None]) -> index.Project:
    files = []
    for filename, yanked in names:
        version = filename.split("-")[1].removesuffix(".tar.gz")
        files.append(
            index.File(
                filename=filename,
                url="u",
                sha256="0" * 64,
                version=Version(version),
                kind="sdist" if filename.endswith(".tar.gz") else "wheel",
                yanked=yanked,
                pure=filename.endswith("none-any.whl"),
                requires_python=">=3.10" if "py310" in filename else None,
            )
        )
    return index.Project("p", tuple(files))


def test_the_newest_release_is_a_final_one_unless_only_pre_releases_exist() -> None:
    assert _project(("p-1.0.tar.gz", None), ("p-2.0rc1.tar.gz", None)).newest() == Version("1.0")
    assert _project(("p-1.0.tar.gz", None), ("p-2.0rc1.tar.gz", None)).newest(
        prereleases=True
    ) == Version("2.0rc1")
    assert _project(("p-1.0a1.tar.gz", None), ("p-1.0b1.tar.gz", None)).newest() == Version("1.0b1")
    assert (
        _project(
            ("p-1.0.tar.gz", "gone"),
        ).newest()
        is None
    )
    assert index.Project("p", ()).newest() is None


def test_a_file_that_runs_anywhere_is_read_before_one_that_does_not_and_source_last() -> None:
    found = _project(
        ("p-1.0.tar.gz", None),
        ("p-1.0-cp312-cp312-manylinux_2_17_x86_64.whl", None),
        ("p-1.0-py3-none-any.whl", None),
    )
    chosen = found.choose(Version("1.0"))
    assert chosen is not None
    assert chosen.filename == "p-1.0-py3-none-any.whl"
    platform = _project(("p-1.0.tar.gz", None), ("p-1.0-cp312-cp312-win_amd64.whl", None))
    only_platform = platform.choose(Version("1.0"))
    assert only_platform is not None
    assert only_platform.filename == "p-1.0-cp312-cp312-win_amd64.whl"
    source = _project(("p-1.0.tar.gz", None)).choose(Version("1.0"))
    assert source is not None
    assert source.kind == "sdist"
    assert found.choose(Version("9.9")) is None


def test_a_file_the_python_cannot_install_is_not_chosen() -> None:
    found = _project(("p-1.0-py310-none-any.whl", None), ("p-1.0.tar.gz", None))
    old = found.choose(Version("1.0"), Version("3.9"))
    assert old is not None
    assert old.kind == "sdist"
    new = found.choose(Version("1.0"), Version("3.12"))
    assert new is not None
    assert new.kind == "wheel"


def test_a_requirement_nobody_can_read_admits_every_python() -> None:
    odd = index.File(
        "p-1.tar.gz", "u", "0" * 64, Version("1"), "sdist", requires_python="not a spec"
    )
    assert odd.admits(Version("3.12"))


# PyPI's JSON API.


def test_what_a_project_says_of_itself_is_read(served: fakeindex.FakeIndex) -> None:
    served.add(
        "acme-kit",
        "1.0",
        {"__init__.py": ""},
        classifiers=["Development Status :: 7 - Inactive"],
        project_urls={"Changelog": "https://example.com/changes", "bad": 3},
        summary="A kit.",
    )
    served.projects["acme-kit"].info["requires_python"] = ">=3.9"
    served.projects["acme-kit"].vulnerabilities = [
        {"id": "PYSEC-1", "summary": "bad", "fixed_in": ["1.1", 5]},
        {"id": "PYSEC-2", "withdrawn": "2026-01-01"},
        {"summary": "no id"},
    ]
    found = index.metadata(_fetcher(served), "acme-kit")
    assert found is not None
    assert found.classifiers == ("Development Status :: 7 - Inactive",)
    assert found.project_urls == {"Changelog": "https://example.com/changes"}
    assert found.summary == "A kit."
    assert found.requires_python == ">=3.9"
    assert found.vulnerabilities == (index.Vulnerability("PYSEC-1", "bad", ("1.1",)),)


def test_an_index_without_the_json_api_or_the_project_has_no_metadata(
    served: fakeindex.FakeIndex,
) -> None:
    assert index.metadata(_fetcher(served), "nothing-here") is None


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"info": 3}', b"[" * 100_000])
def test_metadata_that_is_not_the_json_api_is_no_metadata(
    served: fakeindex.FakeIndex, body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": ""})
    monkeypatch.setattr(served, "_json", lambda *_args: body)
    assert index.metadata(_fetcher(served), "acme-kit") is None


def test_an_index_that_is_down_is_an_error_and_not_no_metadata() -> None:
    with pytest.raises(NetworkError) as raised:
        index.metadata(Fetcher(index="http://127.0.0.1:1/simple"), "acme-kit")
    assert raised.value.reason == "unreachable"


# A release.


def test_a_release_is_read_into_a_directory_that_goes_away(served: fakeindex.FakeIndex) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": "x = 1\n", "core.py": "def f(): ...\n"})
    found = index.project(_fetcher(served), "acme-kit")
    file = found.choose(Version("1.0"))
    assert file is not None
    with release.read(_fetcher(served), file) as unpacked:
        assert (unpacked.root / "acme_kit" / "core.py").read_text() == "def f(): ...\n"
        root = unpacked.root
    assert not root.exists()


def test_a_file_whose_bytes_are_not_the_ones_the_index_promised_is_refused(
    served: fakeindex.FakeIndex,
) -> None:
    name = served.add("acme-kit", "1.0", {"__init__.py": ""})
    file = index.project(_fetcher(served), "acme-kit").files[0]
    served.corrupt.add(name)
    with pytest.raises(release.ReleaseError, match="does not have the sha256"):
        release.download(_fetcher(served), file)


def test_a_poisoned_cache_entry_is_not_believed(
    served: fakeindex.FakeIndex, tmp_path: Path
) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": ""})
    file = index.project(_fetcher(served), "acme-kit").files[0]
    cache = Cache(tmp_path / "cache")
    cache.put(Cache.key("file", file.sha256), b"somebody else's bytes")
    with pytest.raises(release.ReleaseError):
        release.download(_fetcher(served, cache=cache), file)


def test_a_file_is_asked_for_once_and_then_kept_by_its_hash(
    served: fakeindex.FakeIndex, tmp_path: Path
) -> None:
    served.add("acme-kit", "1.0", {"__init__.py": ""})
    file = index.project(_fetcher(served), "acme-kit").files[0]
    cache = Cache(tmp_path / "cache")
    first = release.download(_fetcher(served, cache=cache), file)
    second = release.download(_fetcher(served, cache=cache, offline=True), file)
    assert first == second
    assert served.asked.count(f"/files/{file.filename}") == 1
