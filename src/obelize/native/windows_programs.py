"""The program Windows runs for a command, whether it reads the command as written, and how
its shells read an argument.

Judged on any system, so it is tested everywhere. `CreateProcess` looks in Python's directory and
the current one before `PATH`, and runs a `.bat` or `.cmd` through `cmd.exe`, which parses the
arguments again (BatBadBut). So a program is looked up on the command's own `PATH` alone, and
only an `.exe` or a `.com` runs, judged after the trailing dots and spaces Windows drops.
"""

from __future__ import annotations

import ntpath
import re
import shlex
from collections.abc import Callable

# In `PATHEXT`'s order, which a shell follows within one directory.
RUNNABLE = (".com", ".exe")
BATCH = (".bat", ".cmd")

# What splits an argument, or what cmd.exe or PowerShell act on outside double quotes.
_QUOTED = re.compile(r"""[\s"&|<>^;,(){}@'#]""")


def search(program: str, path: str, cwd: str, is_file: Callable[[str], bool]) -> str:
    """The file to run for `program`, or `OSError` saying why none may run.

    A name with a separator is taken from `cwd`, the command's own directory, as POSIX takes it;
    a bare one from the first absolute directory on `path` that holds it.
    """
    drive, root, rest = ntpath.splitroot(program)
    if drive and not root:
        raise OSError("a drive with no directory after it means that drive's current directory")
    if ":" in rest:
        raise OSError("a ':' after the drive names a stream of a file, which is not run")
    name = ntpath.basename(program).rstrip(". ")
    if not name:
        raise FileNotFoundError("there is no file name to run")
    suffix = ntpath.splitext(name)[1].casefold()
    if suffix in BATCH:
        raise OSError(_batch(name))
    if suffix in RUNNABLE:
        runnable: tuple[str, ...] = (name,)
        batch: tuple[str, ...] = ()
    else:
        runnable = tuple(name + extension for extension in RUNNABLE)
        batch = tuple(name + extension for extension in BATCH)
    if bare(program):
        directories = [entry for entry in path.split(";") if _absolute(entry)]
        where = "the command's PATH"
    else:
        where = ntpath.normpath(ntpath.join(cwd, ntpath.dirname(program)))
        directories = [where]
    for directory in directories:
        for candidate in runnable:
            if is_file(found := ntpath.join(directory, candidate)):
                return found
        for candidate in batch:
            if is_file(found := ntpath.join(directory, candidate)):
                raise OSError(_batch(found))
    raise FileNotFoundError(f"no {' or '.join(runnable)} in {where}")


def bare(program: str) -> bool:
    """Named without a directory, so looked up on `PATH`."""
    return "/" not in program and "\\" not in program


def name(program: str) -> str:
    """The file name as Windows reads it, less `.exe` or `.com`: `C:/x/PyTest.EXE` is `pytest`."""
    read = ntpath.basename(program).rstrip(". ").casefold()
    stem, suffix = ntpath.splitext(read)
    return stem if suffix in RUNNABLE else read


def command_problem(text: str) -> str | None:
    """Why Windows cannot take `text` as written, or `None`.

    `shlex` reads a backslash as an escape, so an unquoted Windows path loses its separators:
    `tests\\unit` becomes `testsunit`. Single quotes keep every backslash.
    """
    literal = shlex.shlex(text, posix=True)
    literal.whitespace_split = True
    literal.commenters = ""
    literal.escape = ""
    try:
        kept: list[str] | None = list(literal)
    except ValueError:  # the backslash was escaping a quote
        kept = None
    if kept == shlex.split(text):
        return None
    return (
        f"{text!r} holds a backslash that splitting it into arguments would drop; put a Windows "
        f"path in single quotes or write it with forward slashes"
    )


def quote(argument: str) -> str:
    """`argument` as one argument of a command typed into cmd.exe or PowerShell.

    cmd.exe reads no single quote, so this is double quotes, escaped as
    `subprocess.list2cmdline` escapes them: a run of backslashes before a quote, or before the
    closing one, is doubled. `list2cmdline` leaves `R&D` bare, where cmd.exe would run what
    follows the `&`.
    """
    if argument and not _QUOTED.search(argument):
        return argument
    escaped = re.sub(r'(\\*)"', r'\1\1\\"', argument)
    return '"' + re.sub(r"(\\+)$", r"\1\1", escaped) + '"'


def _absolute(directory: str) -> bool:
    """A drive or share and a root: anything else is found from obelize's own directory."""
    drive, root, _ = ntpath.splitroot(directory)
    return bool(drive) and bool(root)


def _batch(file: str) -> str:
    return (
        f"{file} is a batch file, which Windows would run through cmd.exe, and cmd.exe reads "
        f"its arguments again as a shell does; name the .exe it starts instead"
    )


__all__ = ["BATCH", "RUNNABLE", "bare", "command_problem", "name", "quote", "search"]
