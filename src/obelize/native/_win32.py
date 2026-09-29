"""The NT file calls behind `files_windows`, the job calls behind `processes_windows`, through
ctypes, and the data they pass.

ntdll and kernel32 load on first use, so this module imports on any system, where its structures
are checked against the documented 64-bit layouts and its status table and name encoding are
tested.
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import functools
import os
import stat
import struct
import subprocess
from collections.abc import Callable, Iterator
from typing import Any

# Access rights.
DELETE = 0x00010000
SYNCHRONIZE = 0x00100000
FILE_LIST_DIRECTORY = 0x00000001
FILE_TRAVERSE = 0x00000020
FILE_READ_ATTRIBUTES = 0x00000080
FILE_WRITE_ATTRIBUTES = 0x00000100
FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_WRITE = 0x00120116

# Read, write and delete: POSIX has no share modes, so no open here keeps another program out.
FILE_SHARE_ALL = 0x00000007

# `NtCreateFile`'s dispositions and options.
FILE_OPEN = 1
FILE_CREATE = 2
FILE_DIRECTORY_FILE = 0x00000001
FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_OBJ_CASE_INSENSITIVE = 0x00000040

# `CreateFileW`'s, for the two opens by path.
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

FILE_ATTRIBUTE_READONLY = 0x00000001
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
# What `FileBasicInformation` may set, less `NORMAL`, which is valid only alone.
_SETTABLE = 0x000031A7 & ~FILE_ATTRIBUTE_NORMAL

# Set in the tag of a symbolic link or a junction, which name another path.
NAME_SURROGATE = 0x20000000
_IO_REPARSE_TAG_SYMLINK = 0xA000000C

# `FILE_INFORMATION_CLASS` and `FS_INFORMATION_CLASS` values.
_FILE_BASIC_INFORMATION = 4
_FILE_RENAME_INFORMATION = 10
_FILE_DISPOSITION_INFORMATION = 13
_FILE_ATTRIBUTE_TAG_INFORMATION = 35
_FILE_ID_BOTH_DIRECTORY_INFORMATION = 37
_FILE_ID_INFORMATION = 59
_FILE_DISPOSITION_INFORMATION_EX = 64
_FILE_RENAME_INFORMATION_EX = 65
_FILE_FS_ATTRIBUTE_INFORMATION = 5

_FILE_SUPPORTS_POSIX_UNLINK_RENAME = 0x00000400
# Replace if exists, POSIX semantics, ignore the read-only attribute.
_RENAME_FLAGS = 0x00000001 | 0x00000002 | 0x00000040
# Delete, POSIX semantics, ignore the read-only attribute.
_DISPOSITION_FLAGS = 0x00000001 | 0x00000002 | 0x00000010

STATUS_NO_MORE_FILES = 0x80000006

# `CreateProcess` flags: the command waits for its job, and Windows disables Ctrl+C in a new group,
# so an interrupted obelize ends the job itself.
CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200

# What `open_process` asks for: assigning takes the first two, resuming the third.
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_SUSPEND_RESUME = 0x0800

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
# `JOBOBJECTINFOCLASS` values.
JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

# The code a stopped job's processes exit with: what a console program ended by Ctrl+C gives.
STATUS_CONTROL_C_EXIT = 0xC000013A


class UnicodeString(ctypes.Structure):
    _fields_ = (
        ("Length", ctypes.c_uint16),
        ("MaximumLength", ctypes.c_uint16),
        ("Buffer", ctypes.c_void_p),
    )


class ObjectAttributes(ctypes.Structure):
    _fields_ = (
        ("Length", ctypes.c_uint32),
        ("RootDirectory", ctypes.c_void_p),
        ("ObjectName", ctypes.c_void_p),
        ("Attributes", ctypes.c_uint32),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    )


class IoStatusBlock(ctypes.Structure):
    """Filled by every call and never read, since each also returns its status."""

    # The status shares its eight bytes with a pointer.
    _fields_ = (("Pointer", ctypes.c_void_p), ("Information", ctypes.c_size_t))


class FileBasicInformation(ctypes.Structure):
    """A time left at zero is left as it is."""

    _fields_ = (
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
    )


class FileAttributeTagInformation(ctypes.Structure):
    _fields_ = (("FileAttributes", ctypes.c_uint32), ("ReparseTag", ctypes.c_uint32))


class FileIdInformation(ctypes.Structure):
    _fields_ = (("VolumeSerialNumber", ctypes.c_uint64), ("FileId", ctypes.c_uint8 * 16))


class FileRenameInformation(ctypes.Structure):
    """The fixed part; the name follows at `FileName`. The classic class reads only the low byte
    of `Flags`, as `ReplaceIfExists`."""

    _fields_ = (
        ("Flags", ctypes.c_uint32),
        ("RootDirectory", ctypes.c_void_p),
        ("FileNameLength", ctypes.c_uint32),
        ("FileName", ctypes.c_uint16 * 1),
    )


class FileDispositionInformation(ctypes.Structure):
    _fields_ = (("DeleteFile", ctypes.c_uint8),)


class FileDispositionInformationEx(ctypes.Structure):
    _fields_ = (("Flags", ctypes.c_uint32),)


class FileIdBothDirectoryInformation(ctypes.Structure):
    """One entry of a listing, whose name follows at `FileName`."""

    _fields_ = (
        ("NextEntryOffset", ctypes.c_uint32),
        ("FileIndex", ctypes.c_uint32),
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("AllocationSize", ctypes.c_int64),
        ("FileAttributes", ctypes.c_uint32),
        ("FileNameLength", ctypes.c_uint32),
        ("EaSize", ctypes.c_uint32),
        ("ShortNameLength", ctypes.c_int8),
        ("ShortName", ctypes.c_uint16 * 12),
        ("FileId", ctypes.c_int64),
        ("FileName", ctypes.c_uint16 * 1),
    )


class FileFsAttributeInformation(ctypes.Structure):
    _fields_ = (
        ("FileSystemAttributes", ctypes.c_uint32),
        ("MaximumComponentNameLength", ctypes.c_int32),
        ("FileSystemNameLength", ctypes.c_uint32),
        ("FileSystemName", ctypes.c_uint16 * 1),
    )


class JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    )


class IoCounters(ctypes.Structure):
    _fields_ = (
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    )


class JobObjectExtendedLimitInformation(ctypes.Structure):
    """`KILL_ON_JOB_CLOSE` is set only through this class, not the basic one."""

    _fields_ = (
        ("BasicLimitInformation", JobObjectBasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


class JobObjectBasicAccountingInformation(ctypes.Structure):
    _fields_ = (
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    )


_NTSTATUS = ctypes.c_uint32
_POINTER = ctypes.c_void_p
_ULONG = ctypes.c_uint32
_BOOLEAN = ctypes.c_uint8

# Each call's result and parameters, as `ntifs.h` declares them; a status is read unsigned.
PROTOTYPES: dict[str, tuple[type[Any], ...]] = {
    "NtClose": (_NTSTATUS, _POINTER),
    "NtCreateFile": (
        _NTSTATUS,
        *(_POINTER, _ULONG, _POINTER, _POINTER, _POINTER),
        *(_ULONG, _ULONG, _ULONG, _ULONG, _POINTER, _ULONG),
    ),
    "NtQueryDirectoryFile": (
        _NTSTATUS,
        *(_POINTER, _POINTER, _POINTER, _POINTER, _POINTER, _POINTER),
        *(_ULONG, _ULONG, _BOOLEAN, _POINTER, _BOOLEAN),
    ),
    "NtQueryInformationFile": (_NTSTATUS, _POINTER, _POINTER, _POINTER, _ULONG, _ULONG),
    "NtQueryVolumeInformationFile": (_NTSTATUS, _POINTER, _POINTER, _POINTER, _ULONG, _ULONG),
    "NtResumeProcess": (_NTSTATUS, _POINTER),
    "NtSetInformationFile": (_NTSTATUS, _POINTER, _POINTER, _POINTER, _ULONG, _ULONG),
}

_BOOL = ctypes.c_int32

# As `jobapi2.h` and `processthreadsapi.h` declare them: a `BOOL` of zero or a null `HANDLE` is a
# failure, whose reason `GetLastError` holds.
KERNEL32_PROTOTYPES: dict[str, tuple[type[Any], ...]] = {
    "AssignProcessToJobObject": (_BOOL, _POINTER, _POINTER),
    "CreateJobObjectW": (_POINTER, _POINTER, _POINTER),
    "OpenProcess": (_POINTER, _ULONG, _BOOL, _ULONG),
    "QueryInformationJobObject": (_BOOL, _POINTER, _ULONG, _POINTER, _ULONG, _POINTER),
    "SetInformationJobObject": (_BOOL, _POINTER, _ULONG, _POINTER, _ULONG),
    "TerminateJobObject": (_BOOL, _POINTER, _ULONG),
}

# The statuses these calls meet, as the errno POSIX gives for the same failure; others are EIO.
_ERRNO = {
    0xC0000034: errno.ENOENT,  # OBJECT_NAME_NOT_FOUND
    0xC000003A: errno.ENOENT,  # OBJECT_PATH_NOT_FOUND
    0xC000000F: errno.ENOENT,  # NO_SUCH_FILE
    # A classic delete leaves the name until the last handle closes; POSIX's is gone at once.
    0xC0000056: errno.ENOENT,  # DELETE_PENDING
    0xC0000123: errno.ENOENT,  # FILE_DELETED
    0xC0000035: errno.EEXIST,  # OBJECT_NAME_COLLISION
    0xC0000022: errno.EACCES,  # ACCESS_DENIED
    0xC0000043: errno.EACCES,  # SHARING_VIOLATION
    0xC0000121: errno.EACCES,  # CANNOT_DELETE, a read-only file
    0xC0000054: errno.EACCES,  # FILE_LOCK_CONFLICT
    0xC0000061: errno.EPERM,  # PRIVILEGE_NOT_HELD
    0xC0000103: errno.ENOTDIR,  # NOT_A_DIRECTORY
    0xC00000BA: errno.EISDIR,  # FILE_IS_A_DIRECTORY
    0xC0000101: errno.ENOTEMPTY,  # DIRECTORY_NOT_EMPTY
    0xC0000033: errno.EINVAL,  # OBJECT_NAME_INVALID
    0xC000000D: errno.EINVAL,  # INVALID_PARAMETER
    0xC0000004: errno.EINVAL,  # INFO_LENGTH_MISMATCH
    0xC0000106: errno.ENAMETOOLONG,  # NAME_TOO_LONG
    0xC000007F: errno.ENOSPC,  # DISK_FULL
    0xC00000A2: errno.EROFS,  # MEDIA_WRITE_PROTECTED
    0xC00000D4: errno.EXDEV,  # NOT_SAME_DEVICE
    0xC000011F: errno.EMFILE,  # TOO_MANY_OPENED_FILES
    0xC000009A: errno.ENOMEM,  # INSUFFICIENT_RESOURCES
    0xC0000008: errno.EBADF,  # INVALID_HANDLE
    0xC0000003: errno.EOPNOTSUPP,  # INVALID_INFO_CLASS
    0xC00000BB: errno.EOPNOTSUPP,  # NOT_SUPPORTED
    0xC0000010: errno.EOPNOTSUPP,  # INVALID_DEVICE_REQUEST
    0x8000002D: errno.ELOOP,  # STOPPED_ON_SYMLINK
    0xC000050B: errno.ELOOP,  # REPARSE_POINT_ENCOUNTERED
}

# `/` and a backslash leave the directory, and a colon names a stream.
_OUTSIDE_A_NAME = frozenset("/\\:")
# A `UNICODE_STRING` counts its bytes in 16 bits, and UTF-16 comes in pairs of them.
_UNICODE_STRING_MAX_BYTES = 0xFFFE

_ENTRY_ATTRIBUTES = FileIdBothDirectoryInformation.FileAttributes.offset
_ENTRY_NAME = FileIdBothDirectoryInformation.FileName.offset
_LISTING_BYTES = 0x10000
_VOLUME_BYTES = 0x200

# `WinDLL` calls with stdcall, which 32-bit Windows needs, and exists only on Windows, the one
# system that loads ntdll and kernel32; so does `get_last_error`.
_LIBRARY: type[ctypes.CDLL] = getattr(ctypes, "WinDLL", ctypes.CDLL)
_last_error: Callable[[], int] = getattr(ctypes, "get_last_error", ctypes.get_errno)


def encode(name: str) -> bytes:
    """`name` as NT takes it relative to a directory: UTF-16, a lone surrogate kept as Windows'
    own listings give it.

    An empty name would open the directory itself, and `.`, `..`, a separator or a stream's colon
    would reach past the name.
    """
    if name in ("", ".", "..") or not _OUTSIDE_A_NAME.isdisjoint(name):
        raise OSError(errno.EINVAL, "Not a name within one directory", name)
    encoded = name.encode("utf-16-le", "surrogatepass")
    if len(encoded) > _UNICODE_STRING_MAX_BYTES:
        raise OSError(errno.ENAMETOOLONG, os.strerror(errno.ENAMETOOLONG), name)
    return encoded


def error(status: int, name: str | None) -> OSError:
    """The `OSError`, and so the subclass, that POSIX raises for the same failure."""
    number = _ERRNO.get(status, errno.EIO)
    return OSError(number, f"{os.strerror(number)} (NTSTATUS 0x{status:08X})", name)


def check(status: int, name: str | None = None) -> None:
    """Raise any status but a success: a warning, such as a truncated answer, fails here too."""
    if status >= 0x80000000:
        raise error(status, name)


def mode(attributes: int, tag: int) -> int:
    """`st_mode` as CPython's `lstat` gives it on Windows: only a symbolic link is `S_IFLNK`, a
    junction is a directory, and the permission bits say whether the file is read-only."""
    kind = stat.S_IFDIR | 0o111 if attributes & FILE_ATTRIBUTE_DIRECTORY else stat.S_IFREG
    bits = kind | (0o444 if attributes & FILE_ATTRIBUTE_READONLY else 0o666)
    symbolic = attributes & FILE_ATTRIBUTE_REPARSE_POINT and tag == _IO_REPARSE_TAG_SYMLINK
    return stat.S_IFLNK | stat.S_IMODE(bits) if symbolic else bits


def stat_result(attributes: int, tag: int) -> os.stat_result:
    """What the path guard and the writer read of an `lstat`: the kind, the read-only bit and the
    reparse tag. The rest is zero or absent."""
    return os.stat_result(
        (mode(attributes, tag), 0, 0, 0, 0, 0, 0, 0, 0, 0),
        {"st_file_attributes": attributes, "st_reparse_tag": tag},
    )


def attributes(current: int, *, readonly: bool) -> int:
    """`current` with the read-only bit set or cleared. None is written as `NORMAL`, since zero
    would leave the attributes as they are."""
    kept = current & _SETTABLE & ~FILE_ATTRIBUTE_READONLY
    return kept | (FILE_ATTRIBUTE_READONLY if readonly else 0) or FILE_ATTRIBUTE_NORMAL


def renaming(target: str, root: int, *, posix: bool) -> tuple[int, ctypes.Array[ctypes.c_char]]:
    """The class and the buffer that rename an open file to `target` in the directory `root`.

    With POSIX semantics a target another program holds open, or a read-only one, is replaced
    too; the classic class only replaces what nothing holds.
    """
    encoded = encode(target)
    offset = FileRenameInformation.FileName.offset
    size = max(ctypes.sizeof(FileRenameInformation), offset + len(encoded))
    buffer = ctypes.create_string_buffer(size)
    header = FileRenameInformation.from_buffer(buffer)
    header.Flags = _RENAME_FLAGS if posix else 1
    header.RootDirectory = root
    header.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    return (_FILE_RENAME_INFORMATION_EX if posix else _FILE_RENAME_INFORMATION), buffer


def disposal(*, posix: bool) -> tuple[int, ctypes.Structure]:
    """The class and the structure that delete an open file or empty directory.

    With POSIX semantics the name goes at once, even while another program holds the file, and a
    read-only file goes too.
    """
    if posix:
        return _FILE_DISPOSITION_INFORMATION_EX, FileDispositionInformationEx(_DISPOSITION_FLAGS)
    return _FILE_DISPOSITION_INFORMATION, FileDispositionInformation(1)


def entries(answer: bytes) -> Iterator[tuple[str, int]]:
    """Each name in one `FileIdBothDirectoryInformation` answer with its attributes, `.` and
    `..` left out."""
    offset = 0
    while True:
        (following,) = struct.unpack_from("<I", answer, offset)
        attributes, length = struct.unpack_from("<II", answer, offset + _ENTRY_ATTRIBUTES)
        start = offset + _ENTRY_NAME
        name = answer[start : start + length].decode("utf-16-le", "surrogatepass")
        if name not in (".", ".."):
            yield name, attributes
        if not following:
            return
        offset += following


def limits() -> JobObjectExtendedLimitInformation:
    """Kill what the job holds when its last handle closes. No breakaway flag is set, so a
    process in the job cannot start one outside it."""
    information = JobObjectExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return information


def nonzero(result: int | None, call: str) -> int:
    """`result`, unless it is how a kernel32 call says it failed: a zero `BOOL` or a null
    `HANDLE`, which ctypes gives as `None`."""
    if not result:
        raise OSError(f"{call} failed with Windows error {_last_error()}")
    return result


@functools.cache
def _ntdll() -> ctypes.CDLL:
    return _bound(_LIBRARY("ntdll"), PROTOTYPES)


@functools.cache
def _kernel32() -> ctypes.CDLL:
    return _bound(_LIBRARY("kernel32", use_last_error=True), KERNEL32_PROTOTYPES)


def _bound(library: ctypes.CDLL, prototypes: dict[str, tuple[type[Any], ...]]) -> ctypes.CDLL:
    for name, (result, *parameters) in prototypes.items():
        function = getattr(library, name)
        function.restype = result
        function.argtypes = parameters
    return library


def open_at(
    parent: int,
    name: str,
    access: int,
    disposition: int,
    options: int,
    *,
    attributes: int = 0,
    follow: bool = False,
) -> int:
    """`name` in the open directory `parent`, resolved against nothing else.

    A reparse point at the name is opened as itself, unless `follow` lets its filter redirect the
    open. Everything is shared, as on POSIX.
    """
    encoded = encode(name)
    text = ctypes.create_string_buffer(encoded, len(encoded))
    string = UnicodeString(len(encoded), len(encoded), ctypes.addressof(text))
    objects = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        parent,
        ctypes.addressof(string),
        _OBJ_CASE_INSENSITIVE,
        None,
        None,
    )
    handle = ctypes.c_size_t()
    status = _ntdll().NtCreateFile(
        ctypes.byref(handle),
        access | SYNCHRONIZE,
        ctypes.byref(objects),
        ctypes.byref(IoStatusBlock()),
        None,
        attributes,
        FILE_SHARE_ALL,
        disposition,
        options | _FILE_SYNCHRONOUS_IO_NONALERT | (0 if follow else _FILE_OPEN_REPARSE_POINT),
        None,
        0,
    )
    check(status, name)
    return handle.value


def close(handle: int) -> None:
    check(_ntdll().NtClose(handle))


@contextlib.contextmanager
def closed_on_error(handle: int) -> Iterator[None]:
    """Close `handle` if the block raises; otherwise the block has handed it on."""
    try:
        yield
    except BaseException:
        close(handle)
        raise


@contextlib.contextmanager
def killed_on_error(process: subprocess.Popen[bytes]) -> Iterator[None]:
    """Kill and reap `process` if the block raises, an interrupt too: one started suspended
    waits for a resume that would never come."""
    try:
        yield
    except BaseException:
        with process:
            process.kill()
        raise


def query(handle: int, information_class: int, into: Any, name: str | None) -> None:
    status = _ntdll().NtQueryInformationFile(
        handle,
        ctypes.byref(IoStatusBlock()),
        ctypes.byref(into),
        ctypes.sizeof(into),
        information_class,
    )
    check(status, name)


def set_information(
    handle: int, information_class: int, information: Any, name: str | None
) -> None:
    status = _ntdll().NtSetInformationFile(
        handle,
        ctypes.byref(IoStatusBlock()),
        ctypes.byref(information),
        ctypes.sizeof(information),
        information_class,
    )
    check(status, name)


def attribute_tag(handle: int, name: str) -> tuple[int, int]:
    """The attributes, and the reparse tag, which means something only with the reparse bit."""
    information = FileAttributeTagInformation()
    query(handle, _FILE_ATTRIBUTE_TAG_INFORMATION, information, name)
    return int(information.FileAttributes), int(information.ReparseTag)


def identity(handle: int, name: str) -> bytes:
    """The volume and the file id, equal for two handles only when they hold the same file."""
    information = FileIdInformation()
    query(handle, _FILE_ID_INFORMATION, information, name)
    return bytes(information)


def posix_semantics(handle: int, name: str) -> bool:
    """Whether the volume that holds `handle` renames and deletes with POSIX semantics."""
    information = ctypes.create_string_buffer(_VOLUME_BYTES)
    status = _ntdll().NtQueryVolumeInformationFile(
        handle,
        ctypes.byref(IoStatusBlock()),
        information,
        len(information),
        _FILE_FS_ATTRIBUTE_INFORMATION,
    )
    check(status, name)
    flags = FileFsAttributeInformation.from_buffer(information).FileSystemAttributes
    return bool(flags & _FILE_SUPPORTS_POSIX_UNLINK_RENAME)


def set_attributes(handle: int, *, readonly: bool, name: str | None) -> None:
    current = FileBasicInformation()
    query(handle, _FILE_BASIC_INFORMATION, current, name)
    wanted = FileBasicInformation(
        FileAttributes=attributes(current.FileAttributes, readonly=readonly)
    )
    set_information(handle, _FILE_BASIC_INFORMATION, wanted, name)


def rename(handle: int, root: int, target: str, *, posix: bool) -> None:
    """Rename the open file to `target` in the directory `root`, replacing what is there."""
    information_class, information = renaming(target, root, posix=posix)
    set_information(handle, information_class, information, target)


def delete(handle: int, *, posix: bool, name: str) -> None:
    """Delete the open file or empty directory as itself. The classic class cannot delete a
    read-only file, so there the attribute is cleared first."""
    if not posix:
        set_attributes(handle, readonly=False, name=name)
    information_class, information = disposal(posix=posix)
    set_information(handle, information_class, information, name)


def listing(handle: int, name: str) -> list[tuple[str, int]]:
    """Every name in the open directory `handle`, with its attributes, read from the handle."""
    buffer = ctypes.create_string_buffer(_LISTING_BYTES)
    found: list[tuple[str, int]] = []
    restart = True
    while True:
        status = _ntdll().NtQueryDirectoryFile(
            handle,
            None,
            None,
            None,
            ctypes.byref(IoStatusBlock()),
            buffer,
            len(buffer),
            _FILE_ID_BOTH_DIRECTORY_INFORMATION,
            False,
            None,
            restart,
        )
        if status == STATUS_NO_MORE_FILES:
            return found
        check(status, name)
        found.extend(entries(buffer.raw))
        restart = False


def new_job() -> int:
    """A job object with `limits()`, which nothing else holds a handle to."""
    job = nonzero(_kernel32().CreateJobObjectW(None, None), "CreateJobObjectW")
    with closed_on_error(job):
        information = limits()
        nonzero(
            _kernel32().SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ),
            "SetInformationJobObject",
        )
    return job


def open_process(pid: int, access: int) -> int:
    return nonzero(_kernel32().OpenProcess(access, False, pid), "OpenProcess")


def assign(job: int, process: int) -> None:
    nonzero(_kernel32().AssignProcessToJobObject(job, process), "AssignProcessToJobObject")


def resume(process: int) -> None:
    """Resume every thread of a process started suspended, whose thread handle `Popen` closed."""
    check(_ntdll().NtResumeProcess(process))


def terminate(job: int, code: int) -> None:
    """End every process in the job with `code`; they may still be exiting when this returns."""
    nonzero(_kernel32().TerminateJobObject(job, code), "TerminateJobObject")


def active_processes(job: int) -> int:
    information = JobObjectBasicAccountingInformation()
    nonzero(
        _kernel32().QueryInformationJobObject(
            job,
            JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
            None,
        ),
        "QueryInformationJobObject",
    )
    return int(information.ActiveProcesses)
