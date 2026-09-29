"""`native._win32`: what the Windows file calls pass and answer, checked on any system.

The expected layouts are the documented 64-bit ones (`ntifs.h`, `winternl.h`, [MS-FSCC]), and
the errno each status becomes is the one POSIX raises for the same failure.
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import stat
import struct
import subprocess
import sys

import pytest

from obelize.native import _win32
from platforms import alive, windows_only

SIXTY_FOUR_BITS = pytest.mark.skipif(
    ctypes.sizeof(ctypes.c_void_p) != 8, reason="the documented layouts are the 64-bit ones"
)


@SIXTY_FOUR_BITS
@pytest.mark.parametrize(
    ("structure", "size", "fields"),
    [
        (
            _win32.UnicodeString,
            16,
            [("Length", 0, 2), ("MaximumLength", 2, 2), ("Buffer", 8, 8)],
        ),
        (
            _win32.ObjectAttributes,
            48,
            [
                ("Length", 0, 4),
                ("RootDirectory", 8, 8),
                ("ObjectName", 16, 8),
                ("Attributes", 24, 4),
                ("SecurityDescriptor", 32, 8),
                ("SecurityQualityOfService", 40, 8),
            ],
        ),
        (_win32.IoStatusBlock, 16, [("Pointer", 0, 8), ("Information", 8, 8)]),
        (
            _win32.FileBasicInformation,
            40,
            [
                ("CreationTime", 0, 8),
                ("LastAccessTime", 8, 8),
                ("LastWriteTime", 16, 8),
                ("ChangeTime", 24, 8),
                ("FileAttributes", 32, 4),
            ],
        ),
        (
            _win32.FileAttributeTagInformation,
            8,
            [("FileAttributes", 0, 4), ("ReparseTag", 4, 4)],
        ),
        (_win32.FileIdInformation, 24, [("VolumeSerialNumber", 0, 8), ("FileId", 8, 16)]),
        (
            _win32.FileRenameInformation,
            24,
            [
                ("Flags", 0, 4),
                ("RootDirectory", 8, 8),
                ("FileNameLength", 16, 4),
                ("FileName", 20, 2),
            ],
        ),
        (_win32.FileDispositionInformation, 1, [("DeleteFile", 0, 1)]),
        (_win32.FileDispositionInformationEx, 4, [("Flags", 0, 4)]),
        (
            _win32.FileIdBothDirectoryInformation,
            112,
            [
                ("NextEntryOffset", 0, 4),
                ("FileIndex", 4, 4),
                ("CreationTime", 8, 8),
                ("LastAccessTime", 16, 8),
                ("LastWriteTime", 24, 8),
                ("ChangeTime", 32, 8),
                ("EndOfFile", 40, 8),
                ("AllocationSize", 48, 8),
                ("FileAttributes", 56, 4),
                ("FileNameLength", 60, 4),
                ("EaSize", 64, 4),
                ("ShortNameLength", 68, 1),
                ("ShortName", 70, 24),
                ("FileId", 96, 8),
                ("FileName", 104, 2),
            ],
        ),
        (
            _win32.FileFsAttributeInformation,
            16,
            [
                ("FileSystemAttributes", 0, 4),
                ("MaximumComponentNameLength", 4, 4),
                ("FileSystemNameLength", 8, 4),
                ("FileSystemName", 12, 2),
            ],
        ),
        (
            _win32.JobObjectBasicLimitInformation,
            64,
            [
                ("PerProcessUserTimeLimit", 0, 8),
                ("PerJobUserTimeLimit", 8, 8),
                ("LimitFlags", 16, 4),
                ("MinimumWorkingSetSize", 24, 8),
                ("MaximumWorkingSetSize", 32, 8),
                ("ActiveProcessLimit", 40, 4),
                ("Affinity", 48, 8),
                ("PriorityClass", 56, 4),
                ("SchedulingClass", 60, 4),
            ],
        ),
        (
            _win32.IoCounters,
            48,
            [
                ("ReadOperationCount", 0, 8),
                ("WriteOperationCount", 8, 8),
                ("OtherOperationCount", 16, 8),
                ("ReadTransferCount", 24, 8),
                ("WriteTransferCount", 32, 8),
                ("OtherTransferCount", 40, 8),
            ],
        ),
        (
            _win32.JobObjectExtendedLimitInformation,
            144,
            [
                ("BasicLimitInformation", 0, 64),
                ("IoInfo", 64, 48),
                ("ProcessMemoryLimit", 112, 8),
                ("JobMemoryLimit", 120, 8),
                ("PeakProcessMemoryUsed", 128, 8),
                ("PeakJobMemoryUsed", 136, 8),
            ],
        ),
        (
            _win32.JobObjectBasicAccountingInformation,
            48,
            [
                ("TotalUserTime", 0, 8),
                ("TotalKernelTime", 8, 8),
                ("ThisPeriodTotalUserTime", 16, 8),
                ("ThisPeriodTotalKernelTime", 24, 8),
                ("TotalPageFaultCount", 32, 4),
                ("TotalProcesses", 36, 4),
                ("ActiveProcesses", 40, 4),
                ("TotalTerminatedProcesses", 44, 4),
            ],
        ),
    ],
    ids=[
        "UNICODE_STRING",
        "OBJECT_ATTRIBUTES",
        "IO_STATUS_BLOCK",
        "FILE_BASIC_INFORMATION",
        "FILE_ATTRIBUTE_TAG_INFORMATION",
        "FILE_ID_INFORMATION",
        "FILE_RENAME_INFORMATION",
        "FILE_DISPOSITION_INFORMATION",
        "FILE_DISPOSITION_INFORMATION_EX",
        "FILE_ID_BOTH_DIR_INFORMATION",
        "FILE_FS_ATTRIBUTE_INFORMATION",
        "JOBOBJECT_BASIC_LIMIT_INFORMATION",
        "IO_COUNTERS",
        "JOBOBJECT_EXTENDED_LIMIT_INFORMATION",
        "JOBOBJECT_BASIC_ACCOUNTING_INFORMATION",
    ],
)
def test_each_structure_has_the_documented_fields_offsets_and_widths(
    structure: type[ctypes.Structure], size: int, fields: list[tuple[str, int, int]]
) -> None:
    """A field at the wrong offset or of the wrong width is not refused by the kernel: a rename
    lands under a name read from the wrong bytes. A variable-length name is declared as one
    UTF-16 unit."""
    declared = [
        (name, getattr(structure, name).offset, getattr(structure, name).size)
        for name, *_ in structure._fields_
    ]
    assert declared == fields
    assert ctypes.sizeof(structure) == size


@SIXTY_FOUR_BITS
def test_each_call_takes_the_documented_parameters_and_answers_an_unsigned_status() -> None:
    """Sizes in bytes, in order; a pointer or a handle is eight, a `ULONG` four, a `BOOLEAN` one."""
    documented = {
        "NtClose": [8],
        "NtCreateFile": [8, 4, 8, 8, 8, 4, 4, 4, 4, 8, 4],
        "NtQueryDirectoryFile": [8, 8, 8, 8, 8, 8, 4, 4, 1, 8, 1],
        "NtQueryInformationFile": [8, 8, 8, 4, 4],
        "NtQueryVolumeInformationFile": [8, 8, 8, 4, 4],
        "NtResumeProcess": [8],
        "NtSetInformationFile": [8, 8, 8, 4, 4],
    }
    declared = {
        name: [ctypes.sizeof(parameter) for parameter in parameters]
        for name, (_, *parameters) in _win32.PROTOTYPES.items()
    }
    assert declared == documented
    for result, *_ in _win32.PROTOTYPES.values():
        assert result(0xC0000034).value == 0xC0000034


@SIXTY_FOUR_BITS
def test_each_job_call_takes_the_documented_parameters_and_answers_a_handle_or_a_bool() -> None:
    """`winbase.h` and `jobapi2.h`: a `BOOL` is four bytes and zero means failure; a `HANDLE`
    result is a pointer, null on failure; an information class is a four-byte enum."""
    documented = {
        "AssignProcessToJobObject": (4, [8, 8]),
        "CreateJobObjectW": (8, [8, 8]),
        "OpenProcess": (8, [4, 4, 4]),
        "QueryInformationJobObject": (4, [8, 4, 8, 4, 8]),
        "SetInformationJobObject": (4, [8, 4, 8, 4]),
        "TerminateJobObject": (4, [8, 4]),
    }
    declared = {
        name: (ctypes.sizeof(result), [ctypes.sizeof(parameter) for parameter in parameters])
        for name, (result, *parameters) in _win32.KERNEL32_PROTOTYPES.items()
    }
    assert declared == documented


def test_the_job_and_process_constants_have_their_documented_values() -> None:
    """`winnt.h`, `WinBase.h` and `ntstatus.h`; a wrong bit here asks Windows for something else
    and nothing fails."""
    assert _win32.CREATE_SUSPENDED == 0x00000004
    assert _win32.CREATE_NEW_PROCESS_GROUP == 0x00000200
    assert _win32.PROCESS_TERMINATE == 0x0001
    assert _win32.PROCESS_SET_QUOTA == 0x0100
    assert _win32.PROCESS_SUSPEND_RESUME == 0x0800
    assert _win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x00002000
    assert _win32.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION == 1
    assert _win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION == 9
    # What a console program exits with on Ctrl+C, read back unsigned as 3221225786.
    assert _win32.STATUS_CONTROL_C_EXIT == 0xC000013A == 3221225786


def test_a_job_kills_what_it_holds_when_closed_and_lets_nothing_break_away() -> None:
    """Only `KILL_ON_JOB_CLOSE` is set: `BREAKAWAY_OK` (0x800) or `SILENT_BREAKAWAY_OK` (0x1000)
    would let a process start a child outside the job, and every other limit stays unset."""
    raw = bytes(_win32.limits())
    assert len(raw) == ctypes.sizeof(_win32.JobObjectExtendedLimitInformation)
    assert struct.unpack_from("<I", raw, 16) == (0x00002000,)
    assert raw[:16] == bytes(16)
    assert raw[20:] == bytes(len(raw) - 20)


def _sleeping() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE
    )


@pytest.mark.parametrize("error", [KeyboardInterrupt, OSError, SystemExit])
def test_a_process_is_killed_and_reaped_whatever_the_block_raises(
    error: type[BaseException],
) -> None:
    """A command started suspended would otherwise wait for a resume that never comes.

    Control: a block that raises nothing leaves the process running.
    """
    left = _sleeping()
    try:
        with _win32.killed_on_error(left):
            pass
        assert left.poll() is None, "the process was ended although nothing went wrong"
    finally:
        with left:
            left.kill()

    process = _sleeping()
    with pytest.raises(error), _win32.killed_on_error(process):
        raise error
    assert process.returncode not in (None, 0), "the process was not killed and reaped"
    assert process.stdout is not None
    assert process.stdout.closed
    assert not alive(process.pid)


def test_a_kernel32_call_that_answers_zero_or_null_failed_and_says_which() -> None:
    """A `BOOL` of zero, or a `HANDLE` of null, which ctypes gives as `None`."""
    with pytest.raises(OSError, match="AssignProcessToJobObject failed"):
        _win32.nonzero(0, "AssignProcessToJobObject")
    with pytest.raises(OSError, match="CreateJobObjectW failed"):
        _win32.nonzero(None, "CreateJobObjectW")
    assert _win32.nonzero(1, "TerminateJobObject") == 1
    assert _win32.nonzero(0x1234, "OpenProcess") == 0x1234


@pytest.mark.parametrize(
    ("status", "number", "kind"),
    [
        (0xC0000034, errno.ENOENT, FileNotFoundError),
        (0xC000003A, errno.ENOENT, FileNotFoundError),
        (0xC000000F, errno.ENOENT, FileNotFoundError),
        (0xC0000056, errno.ENOENT, FileNotFoundError),
        (0xC0000123, errno.ENOENT, FileNotFoundError),
        (0xC0000035, errno.EEXIST, FileExistsError),
        (0xC0000022, errno.EACCES, PermissionError),
        (0xC0000043, errno.EACCES, PermissionError),
        (0xC0000121, errno.EACCES, PermissionError),
        (0xC0000054, errno.EACCES, PermissionError),
        (0xC0000061, errno.EPERM, PermissionError),
        (0xC0000103, errno.ENOTDIR, NotADirectoryError),
        (0xC00000BA, errno.EISDIR, IsADirectoryError),
        (0xC0000101, errno.ENOTEMPTY, OSError),
        (0xC0000033, errno.EINVAL, OSError),
        (0xC000000D, errno.EINVAL, OSError),
        (0xC0000004, errno.EINVAL, OSError),
        (0xC0000106, errno.ENAMETOOLONG, OSError),
        (0xC000007F, errno.ENOSPC, OSError),
        (0xC00000A2, errno.EROFS, OSError),
        (0xC00000D4, errno.EXDEV, OSError),
        (0xC000011F, errno.EMFILE, OSError),
        (0xC000009A, errno.ENOMEM, OSError),
        (0xC0000008, errno.EBADF, OSError),
        (0xC0000003, errno.EOPNOTSUPP, OSError),
        (0xC00000BB, errno.EOPNOTSUPP, OSError),
        (0xC0000010, errno.EOPNOTSUPP, OSError),
        (0x8000002D, errno.ELOOP, OSError),
        (0xC000050B, errno.ELOOP, OSError),
        (0xC0000001, errno.EIO, OSError),
    ],
)
def test_a_failed_status_raises_what_posix_raises_for_the_same_failure(
    status: int, number: int, kind: type[OSError]
) -> None:
    """The callers ask for `FileNotFoundError`, `FileExistsError`, `ELOOP` and `ENOTDIR` by
    kind; an unknown status is `EIO` and names itself."""
    with pytest.raises(OSError, match=f"0x{status:08X}") as raised:
        _win32.check(status, "app.py")
    assert type(raised.value) is kind
    assert raised.value.errno == number
    assert raised.value.filename == "app.py"


@pytest.mark.parametrize("status", [0x00000000, 0x00000103, 0x40000000])
def test_a_success_or_an_informational_status_raises_nothing(status: int) -> None:
    _win32.check(status)


def test_a_warning_is_a_failure() -> None:
    """`STATUS_BUFFER_OVERFLOW`: the answer did not fit, so what was read is not all of it."""
    with pytest.raises(OSError, match="0x80000005") as raised:
        _win32.check(0x80000005)
    assert raised.value.errno == errno.EIO


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("app.py", b"a\x00p\x00p\x00.\x00p\x00y\x00"),
        ("é", b"\xe9\x00"),
        ("\U0001d11e", b"\x34\xd8\x1e\xdd"),
        ("\udc80", b"\x80\xdc"),
        (".hidden", b".\x00h\x00i\x00d\x00d\x00e\x00n\x00"),
        ("...", b".\x00.\x00.\x00"),
    ],
    ids=["ascii", "latin", "astral", "lone-surrogate", "dotted", "three-dots"],
)
def test_a_name_is_encoded_as_the_utf_16_nt_reads(name: str, encoded: bytes) -> None:
    """A lone surrogate is a name NTFS holds and a Windows listing gives back; it round-trips."""
    assert _win32.encode(name) == encoded
    assert encoded.decode("utf-16-le", "surrogatepass") == name


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "pkg/app.py", "pkg\\app.py", "app.py:stream", "C:app.py"],
    ids=["empty", "dot", "dot-dot", "slash", "backslash", "stream", "drive"],
)
def test_a_name_that_reaches_past_one_directory_entry_is_invalid(name: str) -> None:
    """Relative to a directory handle, an empty name opens the directory itself."""
    with pytest.raises(OSError, match="Not a name within one directory") as raised:
        _win32.encode(name)
    assert raised.value.errno == errno.EINVAL


def test_a_name_longer_than_a_counted_string_holds_is_too_long() -> None:
    """The length is 16 bits of bytes; past it, it would wrap to a short name."""
    assert len(_win32.encode("a" * 32767)) == 65534
    with pytest.raises(OSError, match=re.escape(os.strerror(errno.ENAMETOOLONG))) as raised:
        _win32.encode("a" * 32768)
    assert raised.value.errno == errno.ENAMETOOLONG


MODES = pytest.mark.parametrize(
    ("attributes", "tag", "expected"),
    [
        (0x00000020, 0, stat.S_IFREG | 0o666),
        (0x00000021, 0, stat.S_IFREG | 0o444),
        (0x00000010, 0, stat.S_IFDIR | 0o777),
        (0x00000011, 0, stat.S_IFDIR | 0o555),
        (0x00000410, 0xA0000003, stat.S_IFDIR | 0o777),
        (0x00000410, 0xA000000C, stat.S_IFLNK | 0o777),
        (0x00000420, 0xA000000C, stat.S_IFLNK | 0o666),
        (0x00000020, 0xA000000C, stat.S_IFREG | 0o666),
        (0x00000420, 0x9000001A, stat.S_IFREG | 0o666),
    ],
    ids=[
        "file",
        "read-only",
        "directory",
        "read-only-directory",
        "junction",
        "directory-symlink",
        "file-symlink",
        "tag-without-the-bit",
        "cloud-placeholder",
    ],
)


@MODES
def test_the_mode_is_the_one_cpython_s_lstat_gives(
    attributes: int, tag: int, expected: int
) -> None:
    """Only a symbolic link is `S_IFLNK`; a junction is a directory whose tag says what it is."""
    assert _win32.mode(attributes, tag) == expected


@windows_only("from 3.13 os.stat_result refuses fields this system's lstat does not have")
@MODES
def test_the_status_carries_the_mode_the_attributes_and_the_tag(
    attributes: int, tag: int, expected: int
) -> None:
    result = _win32.stat_result(attributes, tag)
    fields = ("st_mode", "st_file_attributes", "st_reparse_tag")
    assert [getattr(result, field) for field in fields] == [expected, attributes, tag]


@pytest.mark.parametrize(
    ("current", "readonly", "expected"),
    [
        (0x00000020, True, 0x00000021),
        (0x00000021, False, 0x00000020),
        (0x00000001, False, 0x00000080),
        (0x00000080, True, 0x00000001),
        (0x00000080, False, 0x00000080),
        (0x00002022, True, 0x00002023),
        (0x00000010, False, 0x00000080),
        (0x00000820, False, 0x00000020),
    ],
    ids=[
        "set",
        "clear",
        "clear-the-last",
        "set-on-normal",
        "normal-stays",
        "others-kept",
        "directory-bit-dropped",
        "compressed-bit-dropped",
    ],
)
def test_the_read_only_bit_is_set_or_cleared_and_only_settable_bits_are_written(
    current: int, readonly: bool, expected: int
) -> None:
    """Zero would leave the attributes as they are, so clearing the last one writes `NORMAL`."""
    assert _win32.attributes(current, readonly=readonly) == expected


@pytest.mark.parametrize(
    ("posix", "information_class", "flags"),
    [(True, 65, 0x43), (False, 10, 0x01)],
    ids=["posix-semantics", "classic"],
)
def test_a_rename_names_its_target_relative_to_the_directory(
    posix: bool, information_class: int, flags: int
) -> None:
    """`FileRenameInformationEx` replaces a target held open or read-only; the classic class sets
    only `ReplaceIfExists`."""
    chosen, buffer = _win32.renaming("new.py", 0x1234, posix=posix)
    assert chosen == information_class
    raw = bytes(buffer)
    assert struct.unpack_from("<IxxxxQI", raw) == (flags, 0x1234, 12)
    assert raw[20:32] == "new.py".encode("utf-16-le")
    assert len(raw) >= 32


def test_a_rename_to_a_one_letter_name_passes_the_whole_structure() -> None:
    _, buffer = _win32.renaming("a", 0, posix=True)
    assert len(bytes(buffer)) == 24


def test_a_rename_to_a_name_past_the_directory_is_refused() -> None:
    with pytest.raises(OSError, match="Not a name within one directory") as raised:
        _win32.renaming("..\\outside.py", 0, posix=True)
    assert raised.value.errno == errno.EINVAL


@pytest.mark.parametrize(
    ("posix", "information_class", "raw"),
    [(True, 64, b"\x13\x00\x00\x00"), (False, 13, b"\x01")],
    ids=["posix-semantics", "classic"],
)
def test_a_delete_asks_for_posix_semantics_where_the_volume_has_them(
    posix: bool, information_class: int, raw: bytes
) -> None:
    """Delete, POSIX semantics and ignore the read-only attribute; the classic class says only
    `DeleteFile`."""
    chosen, information = _win32.disposal(posix=posix)
    assert chosen == information_class
    assert bytes(information) == raw


def _entry(name: str, attributes: int, following: int) -> bytes:
    """One `FILE_ID_BOTH_DIR_INFORMATION`, laid out by the documented offsets."""
    encoded = name.encode("utf-16-le", "surrogatepass")
    entry = bytearray(104 + len(encoded))
    struct.pack_into("<I", entry, 0, following)
    struct.pack_into("<II", entry, 56, attributes, len(encoded))
    entry[104:] = encoded
    return bytes(entry)


def test_a_listing_gives_each_name_with_its_attributes_and_leaves_out_the_dots() -> None:
    names = [(".", 0x10), ("..", 0x10), ("app.py", 0x20), ("pkg", 0x10), ("\udc80.py", 0x420)]
    answer = b""
    for index, (name, attributes) in enumerate(names):
        entry = _entry(name, attributes, 0)
        padded = entry + b"\x00" * (-len(entry) % 8)
        following = len(padded) if index < len(names) - 1 else 0
        answer += _entry(name, attributes, following) + padded[len(entry) :]
    answer += b"\xff" * 64
    assert list(_win32.entries(answer)) == names[2:]
