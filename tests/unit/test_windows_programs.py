"""`native.windows_programs`: the program Windows runs for a command, judged on any system.

The file test is a set of paths, so each rule is checked here without Windows; the Windows-only
tests in `test_verify_runner.py`, `test_gitutil.py` and `test_config.py` run the real thing.
"""

from __future__ import annotations

import shlex
import subprocess

import pytest

from obelize.native.windows_programs import command_problem, name, quote, search

ROOT = "C:\\repo"


def found(program: str, *files: str, path: str = "") -> str:
    return search(program, path, ROOT, set(files).__contains__)


def refused(program: str, *files: str, path: str = "") -> str:
    try:
        found(program, *files, path=path)
    except OSError as error:
        return str(error)
    pytest.fail(f"{program!r} was found")


def test_a_bare_name_is_found_on_the_path_and_never_in_the_command_s_directory() -> None:
    assert found("tool", "C:\\repo\\tool.exe", "C:\\tools\\tool.exe", path="C:\\tools") == (
        "C:\\tools\\tool.exe"
    )
    message = refused("tool", "C:\\repo\\tool.exe", "tool.exe", path="C:\\tools")
    assert message == "no tool.com or tool.exe in the command's PATH"


def test_a_directory_on_the_path_that_is_not_absolute_is_passed_by() -> None:
    """Each of these is found from wherever obelize runs, or from its drive's current directory."""
    planted = ("tool.exe", ".\\tool.exe", "bin\\tool.exe", "\\bin\\tool.exe", "C:bin\\tool.exe")
    unanchored = ";.;bin;\\bin;C:bin"
    refused("tool", *planted, path=unanchored)
    assert found("tool", *planted, "D:\\bin\\tool.exe", path=f"{unanchored};D:\\bin") == (
        "D:\\bin\\tool.exe"
    )
    assert found("tool", "\\\\host\\share\\tool.exe", path="\\\\host\\share\\") == (
        "\\\\host\\share\\tool.exe"
    )


def test_the_first_directory_holding_the_name_wins_and_com_comes_before_exe_within_one() -> None:
    """`PATHEXT`'s order, which a shell follows when a person types the command."""
    both = "C:\\a;C:\\b"
    assert found("tool", "C:\\b\\tool.com", "C:\\a\\tool.exe", path=both) == "C:\\a\\tool.exe"
    assert found("tool", "C:\\a\\tool.exe", "C:\\a\\tool.com", path=both) == "C:\\a\\tool.com"


def test_a_name_given_with_its_extension_is_looked_up_as_it_is() -> None:
    assert found("tool.EXE", "C:\\a\\tool.EXE", path="C:\\a") == "C:\\a\\tool.EXE"
    assert found("tool.com", "C:\\a\\tool.com", path="C:\\a") == "C:\\a\\tool.com"
    message = refused("tool.exe", "C:\\a\\tool.exe.com", "C:\\a\\tool.exe.exe", path="C:\\a")
    assert message == "no tool.exe in the command's PATH"


def test_any_other_extension_is_part_of_the_name() -> None:
    assert found("python3.12", "C:\\a\\python3.12.exe", path="C:\\a") == "C:\\a\\python3.12.exe"
    refused("tool.py", "C:\\a\\tool.py", path="C:\\a")


def test_the_trailing_dots_and_spaces_windows_drops_are_dropped_before_anything_is_judged() -> None:
    assert found("tool.exe. .", "C:\\a\\tool.exe", path="C:\\a") == "C:\\a\\tool.exe"


@pytest.mark.parametrize(
    "program",
    [
        "tool.bat",
        "tool.cmd",
        "TOOL.BAT",
        "tool.bat.",
        "tool.bat ",
        "tool.Cmd. .",
        "C:\\a\\tool.bat",
        "scripts/tool.cmd",
    ],
)
def test_a_batch_file_is_refused_however_its_name_is_spelled(program: str) -> None:
    """`cmd.exe` would read its arguments again, so the approved text is not what runs."""
    message = refused(program, "C:\\a\\tool.bat", "C:\\a\\tool.cmd", path="C:\\a")
    assert "is a batch file" in message
    assert "cmd.exe" in message


def test_a_directory_holding_the_name_only_as_a_batch_file_refuses_it_there() -> None:
    """A shell would run that file, so the `.exe` further along is not the command typed."""
    both = "C:\\a;C:\\b"
    message = refused("tool", "C:\\a\\tool.cmd", "C:\\b\\tool.exe", path=both)
    assert message.startswith("C:\\a\\tool.cmd is a batch file")
    assert found("tool", "C:\\a\\tool.bat", "C:\\a\\tool.exe", path=both) == "C:\\a\\tool.exe"


def test_a_program_named_by_its_path_is_taken_from_the_command_s_directory() -> None:
    """As POSIX takes it; `CreateProcess` alone would complete it from obelize's directory."""
    venv = "C:\\repo\\.venv\\Scripts\\pytest.exe"
    listed = "C:\\tools\\pytest.exe"
    assert found(".venv/Scripts/pytest", venv, listed, path="C:\\tools") == venv
    assert found("./pytest.exe", "C:\\repo\\pytest.exe") == "C:\\repo\\pytest.exe"
    assert found("D:\\x\\pytest", "D:\\x\\pytest.exe", listed, path="C:\\tools") == (
        "D:\\x\\pytest.exe"
    )
    message = refused("bin/pytest", listed, path="C:\\tools")
    assert message == "no pytest.com or pytest.exe in C:\\repo\\bin"


@pytest.mark.parametrize("program", ["C:tool.exe", "c:tool", "C:bin\\tool.exe"])
def test_a_drive_with_no_root_directory_is_refused(program: str) -> None:
    """It means that drive's current directory, which obelize's own may be."""
    files = ("C:tool.exe", "C:\\repo\\tool.exe", "C:\\repo\\bin\\tool.exe", "C:\\a\\tool.exe")
    assert "current directory" in refused(program, *files, path="C:\\a")


@pytest.mark.parametrize("program", ["tool.exe:hidden.exe", "C:\\a\\tool.exe:x.exe"])
def test_a_stream_of_a_file_is_refused(program: str) -> None:
    assert "stream" in refused(program, "C:\\a\\tool.exe", path="C:\\a")


@pytest.mark.parametrize("program", ["..", "bin/", ". ."])
def test_a_name_with_nothing_left_to_run_is_refused(program: str) -> None:
    files = ("C:\\a\\.com", "C:\\a\\.exe", "C:\\repo\\bin\\.exe", "C:\\.exe")
    assert refused(program, *files, path="C:\\a") == "there is no file name to run"


@pytest.mark.parametrize(
    ("program", "expected"),
    [
        ("pytest", "pytest"),
        ("C:/x/pytest.exe", "pytest"),
        ("C:\\x\\PyTest.EXE", "pytest"),
        ("pytest.com", "pytest"),
        ("pytest.exe. ", "pytest"),
        ("py.test", "py.test"),
        ("python3.12.exe", "python3.12"),
        (".venv/Scripts/python", "python"),
        ("pytest.bat", "pytest.bat"),
    ],
)
def test_a_program_s_name_is_its_file_name_as_windows_reads_it(program: str, expected: str) -> None:
    assert name(program) == expected


@pytest.mark.parametrize(
    "text",
    [
        "pytest -q",
        "pytest -k '#1' #2",
        "pytest 'tests\\unit'",
        "'C:\\x\\pytest.exe' -q",
        '"C:\\x\\pytest.exe" -q',
    ],
)
def test_a_command_windows_reads_as_written_has_no_problem(text: str) -> None:
    assert command_problem(text) is None


@pytest.mark.parametrize(
    "text",
    ["pytest tests\\unit", "C:\\x\\pytest.exe -q", 'pytest "a\\\\b"', 'pytest "a\\"b"'],
    ids=["unquoted", "unquoted-program", "doubled-in-double-quotes", "escaped-quote"],
)
def test_a_backslash_the_split_would_drop_or_read_as_an_escape_is_a_problem(text: str) -> None:
    problem = command_problem(text)
    assert problem is not None
    assert repr(text) in problem
    assert "single quotes" in problem


def arguments(line: str) -> list[str]:
    """The arguments a program built with Microsoft's C runtime reads from `line`.

    Backslashes are literal except before a quote: an even run halves and the quote delimits, an
    odd one halves and the quote is literal.
    """
    read: list[str] = []
    word: list[str] = []
    quoted = started = False
    slashes = 0
    for character in line:
        if character == "\\":
            slashes += 1
            started = True
            continue
        if character == '"':
            word.append("\\" * (slashes // 2) + '"' * (slashes % 2))
            quoted ^= slashes % 2 == 0
            slashes = 0
            started = True
            continue
        word.append("\\" * slashes)
        slashes = 0
        if character in " \t" and not quoted:
            if started:
                read.append("".join(word))
            word, started = [], False
            continue
        word.append(character)
        started = True
    word.append("\\" * slashes)
    if started:
        read.append("".join(word))
    return read


# A space, a trailing backslash, an escaped quote, nothing, and characters a shell acts on.
AWKWARD = ["my repo", "C:\\my repo\\", 'a"b', 'a\\\\"b', "", "C:\\R&D", "it's", "a\tb", "x|y"]


def test_the_reference_reads_back_what_list2cmdline_writes() -> None:
    """`list2cmdline` is Python's writer for these rules; the reader is checked against it."""
    assert arguments(subprocess.list2cmdline(["tool", *AWKWARD])) == ["tool", *AWKWARD]


@pytest.mark.parametrize("argument", AWKWARD)
def test_a_quoted_argument_reaches_a_windows_program_as_it_was(argument: str) -> None:
    """Control: single quotes, which cmd.exe does not read, split a spaced one in two."""
    assert arguments(f"tool {quote(argument)}") == ["tool", argument]
    assert arguments(f"tool {shlex.quote('my repo')}") == ["tool", "'my", "repo'"]


@pytest.mark.parametrize(
    ("argument", "spelled"),
    [
        ("C:\\repo", "C:\\repo"),
        ("RUNNER~1\\x.y-z", "RUNNER~1\\x.y-z"),
        ("my repo", '"my repo"'),
        ("C:\\my repo\\", '"C:\\my repo\\\\"'),
        ("", '""'),
    ],
)
def test_an_argument_is_quoted_where_list2cmdline_quotes_it_and_as_it_does(
    argument: str, spelled: str
) -> None:
    assert quote(argument) == spelled == subprocess.list2cmdline([argument])


@pytest.mark.parametrize(
    "argument",
    [
        "C:\\R&D",
        "a|b",
        "a<b",
        "a>b",
        "a^b",
        "a;b",
        "a,b",
        "a(b",
        "a)b",
        "a{b",
        "a}b",
        "@a",
        "#a",
        "it's",
    ],
)
def test_a_character_cmd_or_powershell_acts_on_is_quoted_too(argument: str) -> None:
    """Control: `list2cmdline` writes such an argument bare, where cmd.exe would run what follows
    the `&` as a command of its own."""
    assert subprocess.list2cmdline([argument]) == argument
    assert quote(argument) == f'"{argument}"'
