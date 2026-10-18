"""`obelize.archive`: what a stranger's archive may write, and every way it is refused."""

from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from typing import TYPE_CHECKING

import pytest

from obelize import archive
from obelize.archive import ArchiveError, unpack

if TYPE_CHECKING:
    from pathlib import Path


def wheel(files: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as handle:
        for name, data in files.items():
            handle.writestr(name, data)
    return buffer.getvalue()


def sdist(files: dict[str, bytes], *, mode: str = "w:gz") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as handle:  # type: ignore[call-overload]
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            handle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def tar_member(info: tarfile.TarInfo) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as handle:
        handle.addfile(info)
    return buffer.getvalue()


def names(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


# What is written.


def test_a_wheel_gives_its_source_and_what_describes_it_and_nothing_else(tmp_path: Path) -> None:
    data = wheel(
        {
            "acme/__init__.py": b"x = 1\n",
            "acme/core.pyi": b"def f() -> int: ...\n",
            "acme/_speedups.cpython-312-darwin.so": b"\x7fELF",
            "acme/data.json": b"{}",
            "acme-1.0.dist-info/METADATA": b"Name: acme\n",
            "acme-1.0.dist-info/RECORD": b"acme/__init__.py,,\n",
            "acme-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
            "acme-1.0.dist-info/top_level.txt": b"acme\n",
        }
    )
    done = unpack(data, "acme-1.0-py3-none-any.whl", tmp_path / "out")
    assert names(done.root) == [
        "acme-1.0.dist-info/METADATA",
        "acme-1.0.dist-info/RECORD",
        "acme-1.0.dist-info/top_level.txt",
        "acme/__init__.py",
        "acme/core.pyi",
    ]
    assert (done.files, done.left) == (5, 3)
    assert done.size == sum(
        len(path.read_bytes()) for path in done.root.rglob("*") if path.is_file()
    )


def test_a_source_distribution_loses_its_top_directory(tmp_path: Path) -> None:
    data = sdist({"acme-1.0/src/acme/__init__.py": b"x = 1\n", "acme-1.0/README.md": b"hi"})
    done = unpack(data, "acme-1.0.tar.gz", tmp_path / "out")
    assert names(done.root) == ["src/acme/__init__.py"]


@pytest.mark.parametrize("mode", ["w:gz", "w", "w:bz2", "w:xz"])
def test_every_tar_compression_python_reads_is_read(tmp_path: Path, mode: str) -> None:
    done = unpack(sdist({"acme-1.0/a.py": b"1\n"}, mode=mode), "acme-1.0.tar.gz", tmp_path / "o")
    assert names(done.root) == ["a.py"]


def test_a_zip_source_distribution_loses_its_top_directory_too(tmp_path: Path) -> None:
    done = unpack(wheel({"acme-1.0/acme/__init__.py": b"1\n"}), "acme-1.0.zip", tmp_path / "out")
    assert names(done.root) == ["acme/__init__.py"]


def test_a_directory_entry_writes_nothing(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        handle.writestr("acme/", b"")
        handle.writestr("acme/a.py", b"1\n")
    done = unpack(buffer.getvalue(), "a-1-py3-none-any.whl", tmp_path / "out")
    assert names(done.root) == ["acme/a.py"]


def test_a_member_that_is_a_directory_in_a_tar_is_skipped(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as handle:
        directory = tarfile.TarInfo("acme-1.0/src")
        directory.type = tarfile.DIRTYPE
        handle.addfile(directory)
    assert unpack(buffer.getvalue(), "acme-1.0.tar.gz", tmp_path / "out").files == 0


def test_the_directory_to_unpack_into_is_new(tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    with pytest.raises(FileExistsError):
        unpack(wheel({"a.py": b"1"}), "a-1-py3-none-any.whl", tmp_path / "out")


# What is refused.


@pytest.mark.parametrize(
    "name",
    [
        "../evil.py",
        "acme/../../evil.py",
        "/etc/evil.py",
        "..\\evil.py",
        "acme\\evil.py",
        "C:evil.py",
        "acme/app.py:stream",
        "acme/con.py",
        "acme/nul.txt",
        "acme/app.py.",
        "acme/app.py ",
        "",
    ],
)
def test_a_name_that_leaves_or_means_another_file_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(ArchiveError):
        unpack(wheel({name: b"x = 1\n"}), "a-1-py3-none-any.whl", tmp_path / "out")
    with pytest.raises(ArchiveError):
        unpack(sdist({name: b"x = 1\n"}), "a-1.tar.gz", tmp_path / "out2")
    assert not (tmp_path / "evil.py").exists()


@pytest.mark.parametrize(
    ("kind", "link"),
    [
        (tarfile.SYMTYPE, "../../etc/passwd"),
        (tarfile.LNKTYPE, "acme-1.0/a.py"),
        (tarfile.CHRTYPE, ""),
        (tarfile.FIFOTYPE, ""),
    ],
    ids=["symlink", "hardlink", "device", "fifo"],
)
def test_a_tar_member_that_is_not_a_file_is_refused(tmp_path: Path, kind: bytes, link: str) -> None:
    info = tarfile.TarInfo("acme-1.0/evil.py")
    info.type = kind
    info.linkname = link
    with pytest.raises(ArchiveError, match="is a link or a device"):
        unpack(tar_member(info), "acme-1.0.tar.gz", tmp_path / "out")


def test_a_zip_entry_that_is_a_link_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        info = zipfile.ZipInfo("acme/evil.py")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        handle.writestr(info, "../../etc/passwd")
    with pytest.raises(ArchiveError, match="is a link or a device"):
        unpack(buffer.getvalue(), "a-1-py3-none-any.whl", tmp_path / "out")


def test_two_names_that_are_one_where_case_is_ignored_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match="ignores case"):
        unpack(
            wheel({"acme/A.py": b"1", "acme/a.py": b"2"}), "a-1-py3-none-any.whl", tmp_path / "o"
        )


def test_a_file_over_the_limit_is_refused_before_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archive, "FILE_BYTES", 10)
    with pytest.raises(ArchiveError, match="holds more than 10 bytes"):
        unpack(wheel({"acme/a.py": b"x" * 11}), "a-1-py3-none-any.whl", tmp_path / "o")
    with pytest.raises(ArchiveError, match="holds more than 10 bytes"):
        unpack(sdist({"a-1/a.py": b"x" * 11}), "a-1.tar.gz", tmp_path / "o2")


def test_a_file_that_is_never_read_may_be_as_large_as_a_compiled_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archive, "FILE_BYTES", 10)
    done = unpack(
        wheel({"acme/a.py": b"x", "acme/.dylibs/libc.dylib": b"x" * 50}),
        "a-1-py3-none-any.whl",
        tmp_path / "o",
    )
    assert (done.files, done.left) == (1, 1)


def test_an_archive_that_unpacks_past_its_total_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archive, "TOTAL_BYTES", 15)
    with pytest.raises(ArchiveError, match="unpacks past 15 bytes"):
        unpack(
            wheel({"a.py": b"x" * 10, "b.py": b"y" * 10}), "a-1-py3-none-any.whl", tmp_path / "o"
        )


def test_an_archive_with_too_many_files_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(archive, "FILE_COUNT", 3)
    files = {f"p/{n}.txt": b"" for n in range(4)}
    with pytest.raises(ArchiveError, match="more than 3 files"):
        unpack(wheel(files), "a-1-py3-none-any.whl", tmp_path / "o")


def test_a_file_that_unpacks_to_far_more_than_it_holds_is_a_bomb(tmp_path: Path) -> None:
    data = wheel({"acme/bomb.py": b"#" * (4 << 20)})
    assert len(data) < 20_000
    with pytest.raises(ArchiveError, match="archive bomb"):
        unpack(data, "a-1-py3-none-any.whl", tmp_path / "out")


def test_a_big_file_that_compresses_as_source_does_is_no_bomb(tmp_path: Path) -> None:
    source = "".join(f"value_{n} = {n * 7919 % 10007}\n" for n in range(120_000)).encode()
    assert len(source) > 1 << 20
    done = unpack(wheel({"acme/big.py": source}), "a-1-py3-none-any.whl", tmp_path / "out")
    assert done.files == 1


@pytest.mark.parametrize("filename", ["a-1.tar.gz.sig", "a-1.egg", "a-1.exe", "a-1"])
def test_something_that_is_neither_wheel_nor_source_is_refused(
    tmp_path: Path, filename: str
) -> None:
    with pytest.raises(ArchiveError, match="neither a wheel nor a source distribution"):
        unpack(b"", filename, tmp_path / "out")


def test_bytes_that_are_not_an_archive_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match="not a zip archive"):
        unpack(b"not a zip", "a-1-py3-none-any.whl", tmp_path / "o")
    with pytest.raises(ArchiveError, match="not a tar archive"):
        unpack(b"not a tar", "a-1.tar.gz", tmp_path / "o2")


def test_a_damaged_archive_is_refused_and_not_a_crash(tmp_path: Path) -> None:
    good = wheel({"acme/a.py": b"x = 1\n" * 5000}, compression=zipfile.ZIP_STORED)
    damaged = bytearray(good)
    damaged[40] ^= 0xFF
    with pytest.raises(ArchiveError):
        unpack(bytes(damaged), "a-1-py3-none-any.whl", tmp_path / "o")
    tarred = sdist({"a-1/a.py": b"x = 1\n" * 5000}, mode="w")
    with pytest.raises(ArchiveError, match="cannot be read"):
        unpack(tarred[:700], "a-1.tar", tmp_path / "o2")


def test_a_compressed_member_that_cannot_be_inflated_is_refused(tmp_path: Path) -> None:
    good = wheel({"acme/a.py": b"x = 1\n" * 5000})
    damaged = bytearray(good)
    damaged[60] ^= 0xFF
    with pytest.raises(ArchiveError):
        unpack(bytes(damaged), "a-1-py3-none-any.whl", tmp_path / "o")


def test_a_name_with_a_nul_is_refused() -> None:
    with pytest.raises(ArchiveError, match="not a name inside an archive"):
        archive._checked("acme/a\x00b.py", strip=False)


def test_the_top_directory_of_a_source_distribution_is_dropped_whole(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as handle:
        top = tarfile.TarInfo("acme-1.0")
        top.type = tarfile.DIRTYPE
        handle.addfile(top)
    assert unpack(buffer.getvalue(), "acme-1.0.tar.gz", tmp_path / "out").files == 0
