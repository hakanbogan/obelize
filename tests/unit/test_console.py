"""`native.console`: what obelize prints is UTF-8, whatever code page Windows gives a stream."""

from __future__ import annotations

import io
import sys

import pytest

from obelize.native import console
from platforms import stdout_as_on_windows, windows_only


@windows_only("a POSIX stream encodes as the locale says, UTF-8 by default, so nothing changes")
def test_a_code_page_stream_writes_utf8_after_setup_and_another_stream_is_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: before the setup, the cp1252 stream cannot write `ğ` at all."""
    reached = stdout_as_on_windows(monkeypatch)
    with pytest.raises(UnicodeEncodeError):
        sys.stdout.write("ğ")
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    console.utf8_stdio()
    sys.stdout.write("ğ\n")
    sys.stdout.flush()
    assert reached.getvalue() == "ğ\r\n".encode()
    assert isinstance(sys.stderr, io.StringIO)


@windows_only("a POSIX stream encodes as the locale says, UTF-8 by default, so nothing changes")
def test_stderr_keeps_the_handler_that_lets_every_message_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows name can hold a lone surrogate, which only `backslashreplace` prints.

    Control: given a new encoding and no handler, the same stream refuses it.
    """
    control = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="backslashreplace")
    control.reconfigure(encoding="utf-8")
    with pytest.raises(UnicodeEncodeError):
        control.write("\udcff")
    reached = io.BytesIO()
    stderr = io.TextIOWrapper(reached, encoding="cp1252", errors="backslashreplace")
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    console.utf8_stdio()
    sys.stderr.write("ğ\udcff")
    sys.stderr.flush()
    assert reached.getvalue() == "ğ".encode() + b"\\udcff"
