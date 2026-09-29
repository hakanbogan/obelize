"""The always-on compile check, asked of files on disk rather than the bytes obelize computed."""

from __future__ import annotations

import os
from pathlib import Path

from obelize.verify import cheap

# Its `python2.py` parses in libcst and `compile()` refuses it: why every gate asks `compile()`.
ENCODING = Path(__file__).resolve().parents[1] / "fixtures" / "scan" / "encoding"


def test_a_file_that_compiles_is_not_reported(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert cheap.uncompilable(tmp_path, ["app.py"]) == ()


def test_a_file_that_does_not_compile_is(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes((ENCODING / "python2.py").read_bytes())
    assert cheap.uncompilable(tmp_path, ["app.py"]) == ("app.py",)


def test_source_holding_a_null_byte_is_refused_too(tmp_path: Path) -> None:
    """Every supported interpreter raises a position-less `SyntaxError` for a NUL byte."""
    (tmp_path / "app.py").write_bytes(b"VALUE = 1\x00\n")
    assert cheap.uncompilable(tmp_path, ["app.py"]) == ("app.py",)


def test_a_file_that_is_not_python_is_not_compiled(tmp_path: Path) -> None:
    """obelize changes manifests too, and a manifest is not a program."""
    (tmp_path / "requirements.txt").write_text("google-genai>=1,<3\n", encoding="utf-8")
    assert cheap.uncompilable(tmp_path, ["requirements.txt"]) == ()


def test_a_file_that_cannot_be_read_is_reported(tmp_path: Path) -> None:
    """obelize has just written it, so being unable to read it is the accident."""
    assert cheap.uncompilable(tmp_path, ["gone.py"]) == ("gone.py",)


def test_the_answer_is_sorted(tmp_path: Path) -> None:
    for name in ("b.py", "a.py"):
        (tmp_path / name).write_bytes(b"def (\n")
    assert cheap.uncompilable(tmp_path, ["b.py", "a.py"]) == ("a.py", "b.py")


def test_the_reason_names_the_file_as_the_user_spells_it(tmp_path: Path) -> None:
    """As in `scan/parse.py`: not the ambiguous basename, nor an absolute path that leaks."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_bytes(b"def (\n")
    assert cheap.refusal(tmp_path, "pkg/app.py") == "pkg/app.py:1: invalid syntax"


def test_a_refusal_with_no_position_says_so_by_leaving_it_out(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(b"VALUE = 1\x00\n")
    message = cheap.refusal(tmp_path, "app.py")
    assert message is not None
    assert message.startswith("app.py: ")
    assert "null bytes" in message


def test_a_file_that_cannot_be_read_says_so_rather_than_naming_a_syntax(
    tmp_path: Path,
) -> None:
    message = cheap.refusal(tmp_path, "gone.py")
    assert message is not None
    assert message.startswith("gone.py cannot be read: ")
    assert str(tmp_path) not in message


def test_a_file_that_compiles_has_no_reason(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert cheap.refusal(tmp_path, "app.py") is None


def test_the_check_reads_the_disk_and_not_what_the_driver_computed(tmp_path: Path) -> None:
    """The driver compiles bytes in memory; only opening the file catches a disk that differs."""
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert cheap.uncompilable(tmp_path, ["app.py"]) == ()
    (tmp_path / "app.py").write_bytes(b"VALUE = (\n")
    assert cheap.uncompilable(tmp_path, ["app.py"]) == ("app.py",)


def test_the_read_does_not_follow_a_symbolic_link(tmp_path: Path) -> None:
    """Via `fsutil.read`: compiling a link's target would answer about a file outside the plan."""
    (tmp_path / "real.py").write_text("VALUE = 1\n", encoding="utf-8")
    os.symlink(tmp_path / "real.py", tmp_path / "link.py")
    assert cheap.uncompilable(tmp_path, ["link.py"]) == ("link.py",)
