"""A plugin installed for a test: a module and a `.dist-info` folder on `sys.path`.

`importlib.metadata` finds a distribution by its folder, and `entry_points.txt` there is what names
a kind, so this is a plugin as `pip` leaves one, with nothing installed in the environment.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# As an installer leaves one: CRLF line ends, and a line for the file itself.
RECORD = "acme_fixer.py,sha256=x,1\r\nacme_fixer-1.0.dist-info/RECORD,,\r\n"
PLUGINS = Path(__file__).resolve().parents[2] / "docs" / "PLUGINS.md"


def documented() -> str:
    """The first Python block of docs/PLUGINS.md: the plugin the guide shows is the one tested."""
    found = re.search(r"```python\n(.*?)```", PLUGINS.read_text(encoding="utf-8"), re.DOTALL)
    assert found is not None
    return found[1]


# A kind that renames `acme.old(...)` to `acme.<word>(...)`, wherever the pack's symbol is called.
SOURCE = documented()


def install(
    where: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    distribution: str = "acme-fixer",
    version: str = "1.0",
    name: str = "fixer",
    module: str = "acme_fixer",
    source: str = SOURCE,
    record: str | bytes | None = RECORD,
) -> Path:
    """Put the distribution under `where`, on `sys.path` for this test, and return its folder."""
    where.mkdir(parents=True, exist_ok=True)
    (where / f"{module}.py").write_text(source, encoding="utf-8")
    info = where / f"{distribution.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n", encoding="utf-8"
    )
    (info / "entry_points.txt").write_text(
        f"[obelize.kinds]\n{name} = {module}:KIND\n", encoding="utf-8"
    )
    if record is not None:
        data = record.encode() if isinstance(record, str) else record
        (info / "RECORD").write_bytes(data)
    monkeypatch.syspath_prepend(str(where))
    importlib.invalidate_caches()
    monkeypatch.delitem(sys.modules, module, raising=False)
    return info
