"""A real git repository of PyPDF2 code and manifests, and the bundled pack's scan spec.

The newest-release gate reads a git listing (a dot-directory is only listed there), so the tests
that exercise it need a repository, not a directory.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from obelize.models import ScanSpec
from obelize.packs import loader

SPEC: ScanSpec = loader.to_scan_spec(loader.load("py-pdf/pypdf2-to-pypdf"))

# Uses the library, so the gate is asked; nothing in it names a removed class.
MAIN = 'import PyPDF2\n\nreader = PyPDF2.PdfReader("a.pdf")\nprint(len(reader.pages))\n'

# Uses PdfFileReader, which PyPDF2 3.0.0 removed.
REMOVED = 'from PyPDF2 import PdfFileReader\n\nreader = PdfFileReader("a.pdf")\n'


def git_repo(
    root: Path, files: Mapping[str, str | bytes], ignore: str = "", *, init: bool = True
) -> Path:
    """Write `files` under `root` and make it the top of a repository; `ignore` is `.gitignore`.

    Nothing is added: the listing takes untracked files that are not ignored.
    """
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8", newline="\n")
    if ignore:
        (root / ".gitignore").write_text(ignore, encoding="utf-8", newline="\n")
    if init:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root
