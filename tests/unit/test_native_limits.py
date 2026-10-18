"""`native.limits`: a child process is capped where the system can cap it."""

from __future__ import annotations

import importlib
import sys

import pytest

from obelize.native import limits


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no setrlimit")
def test_a_child_is_capped_in_memory_and_time(monkeypatch: pytest.MonkeyPatch) -> None:
    resource = importlib.import_module("resource")
    seen: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "setrlimit", lambda which, cap: seen.append((which, cap)))
    limits.limit()
    assert seen == [
        (resource.RLIMIT_AS, (4 << 30, 4 << 30)),
        (resource.RLIMIT_CPU, (300, 300)),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no setrlimit")
def test_a_limit_the_system_refuses_does_not_stop_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = importlib.import_module("resource")
    seen: list[int] = []

    def refuse_the_first(which: int, _cap: tuple[int, int]) -> None:
        seen.append(which)
        if which == resource.RLIMIT_AS:
            raise ValueError("current limit exceeds maximum limit")

    monkeypatch.setattr(resource, "setrlimit", refuse_the_first)
    limits.limit()
    assert seen == [resource.RLIMIT_AS, resource.RLIMIT_CPU]


@pytest.mark.skipif(sys.platform != "win32", reason="POSIX caps the child")
def test_windows_leaves_the_cap_to_the_parents_deadline() -> None:
    limits.limit()
