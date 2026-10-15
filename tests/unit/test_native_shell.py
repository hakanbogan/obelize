"""`native.shell`: the examples a message gives, picked by the platform at import."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator

import pytest

from obelize.native import shell


@pytest.fixture
def reloaded_afterwards(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield
    monkeypatch.undo()
    importlib.reload(shell)


@pytest.mark.parametrize(
    ("system", "interpreter", "ask"),
    [
        ("win32", ".venv/Scripts/python.exe", 'cmd /c "<command>"'),
        ("linux", ".venv/bin/python", "sh -c '<command>'"),
    ],
)
@pytest.mark.usefixtures("reloaded_afterwards")
def test_a_system_gets_the_examples_its_shells_read(
    monkeypatch: pytest.MonkeyPatch, system: str, interpreter: str, ask: str
) -> None:
    monkeypatch.setattr(sys, "platform", system)
    reloaded = importlib.reload(shell)
    assert interpreter == reloaded.VENV_PYTHON
    assert ask == reloaded.SHELL
