"""The installed `obelize.exe` over a copy of `examples/gemini-legacy-app`, as a user runs it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from platforms import windows_only

pytestmark = [
    pytest.mark.e2e,
    windows_only("the .exe launcher and a Windows file stream; test_scan_command.py fakes one"),
]

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "gemini-legacy-app"

# A user's streams take the code page unless one of these is set.
UTF8 = {"PYTHONIOENCODING", "PYTHONUTF8"}

PRINT = "import sys; print(open(sys.argv[1], encoding='utf-8').read(), end='')"


def test_the_launcher_redirects_json_as_the_bytes_in_the_run_folder(tmp_path: Path) -> None:
    """Two workers make the pool start processes from the launcher.

    Control: `print` of the same text to a redirected stream ends each line with CRLF.
    """
    launcher = Path(sys.executable).with_name("obelize.exe")
    assert launcher.is_file(), f"no console launcher next to {sys.executable}"
    work = tmp_path / "app"
    shutil.copytree(EXAMPLE, work)
    # A name outside ASCII, so a document in the code page cannot pass as UTF-8.
    shutil.copyfile(work / "summarizer" / "summarize.py", work / "summarizer" / "résumé.py")
    user = {name: value for name, value in os.environ.items() if name not in UTF8}
    redirected = tmp_path / "findings.json"
    with redirected.open("wb") as stdout:
        scanned = subprocess.run(
            [str(launcher), "scan", "--repo", str(work), "--jobs", "2", "--json"],
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=False,
            env=user,
        )
    assert scanned.returncode == 0, scanned.stderr.decode("utf-8", "replace")
    written = redirected.read_bytes()
    assert "summarizer/résumé.py" in written.decode("utf-8")
    assert b"\r" not in written
    run_id = (work / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    assert written == (work / ".obelize" / "runs" / run_id / "findings.json").read_bytes()

    printed = tmp_path / "printed.json"
    with printed.open("wb") as stdout:
        subprocess.run(
            [sys.executable, "-c", PRINT, str(redirected)],
            stdout=stdout,
            check=True,
            env={**user, "PYTHONIOENCODING": "utf-8"},
        )
    assert printed.read_bytes() == written.replace(b"\n", b"\r\n")
