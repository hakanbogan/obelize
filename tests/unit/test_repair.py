"""`obelize.repair`: a failing test's traceback, as places in code the move changed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obelize.repair import is_test, rows

if TYPE_CHECKING:
    from pathlib import Path

TRACE = (
    "Traceback (most recent call last):\n"
    '  File "{work}/tests/test_app.py", line 8, in test_gone\n'
    "    assert app.gone(1) == 1\n"
    '  File "{work}/pkg/app.py", line 5, in gone\n'
    "    return helper(x)\n"
    '  File "{work}/pkg/util.py", line 2, in helper\n'
    "    return x.missing\n"
    '  File "/somewhere/site-packages/acme_kit/__init__.py", line 9, in deep\n'
    "    raise AttributeError\n"
    "AttributeError: 'int' object has no attribute 'missing'\n"
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pkg/app.py", False),
        ("tests/test_app.py", True),
        ("pkg/test_app.py", True),
        ("pkg/app_test.py", True),
        ("pkg/conftest.py", True),
        ("pkg/test/helpers.py", True),
        ("pkg/contest.py", False),
    ],
)
def test_a_test_file_is_known_by_its_name_or_its_directory(path: str, expected: bool) -> None:
    assert is_test(path) is expected


def test_the_place_is_the_innermost_frame_in_a_changed_file_that_is_not_a_test(
    tmp_path: Path,
) -> None:
    failures = {"test_app::test_gone": TRACE.format(work=tmp_path)}
    found = rows(tmp_path, failures, {"pkg/app.py", "tests/test_app.py"}, {})
    assert [(one.path, one.line, one.symbol) for one in found] == [("pkg/app.py", 5, "gone")]
    assert found[0].note == (
        "test_app::test_gone passed before the move and fails after it: "
        "AttributeError: 'int' object has no attribute 'missing'"
    )
    both = rows(tmp_path, failures, {"pkg/app.py", "pkg/util.py"}, {})
    assert [(one.path, one.line, one.symbol) for one in both] == [("pkg/util.py", 2, "helper")]


def test_a_test_with_no_frame_in_changed_code_asks_nothing_and_many_tests_one_place(
    tmp_path: Path,
) -> None:
    trace = TRACE.format(work=tmp_path)
    assert rows(tmp_path, {"t::a": trace}, {"pkg/other.py"}, {}) == []
    assert rows(tmp_path, {"t::a": "", "t::b": "no frames here"}, {"pkg/app.py"}, {}) == []
    twice = rows(tmp_path, {"t::a": trace, "t::b": trace}, {"pkg/app.py"}, {})
    assert len(twice) == 1
    assert twice[0].note.startswith("t::a ")


def test_the_error_is_redacted_and_clipped_before_it_is_a_question(tmp_path: Path) -> None:
    secret = "sk-" + "a" * 40
    text = TRACE.format(work=tmp_path) + f"RuntimeError: {secret} " + "x" * 400 + "\n"
    [one] = rows(tmp_path, {"t::a": text}, {"pkg/app.py"}, {})
    assert secret not in one.note
    assert len(one.note) < 460


def test_the_short_frames_pytest_prints_for_a_module_that_would_not_import_are_places(
    tmp_path: Path,
) -> None:
    short = (
        "Traceback:\n"
        "test_other.py:1: in <module>\n"
        "    import other\n"
        "other.py:2: in <module>\n"
        "    from acme_kit import removed_fn\n"
        "E   ImportError: cannot import name 'removed_fn'\n"
    )
    [one] = rows(tmp_path, {"::test_other": short}, {"other.py"}, {})
    assert (one.path, one.line, one.symbol) == ("other.py", 2, "<module>")
