"""The packs under `tests/packs/generic/`: invented libraries that exercise a rule the three
bundled packs use in one way only, held to the checks `obelize pack test` runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from obelize.packs import loader
from obelize.packtools import check

GENERIC = Path(__file__).resolve().parent / "generic"
PACKS = sorted(GENERIC.glob("*/*/pack.yaml"))


def test_there_are_generic_packs() -> None:
    assert PACKS


@pytest.mark.parametrize("path", PACKS, ids=lambda path: f"{path.parts[-3]}/{path.parts[-2]}")
def test_a_generic_pack_passes_every_check(path: Path) -> None:
    loaded = loader.load(str(path))
    assert [(one.name, one.problems) for one in check.run(loaded) if not one.ok] == []


@pytest.mark.parametrize("path", PACKS, ids=lambda path: f"{path.parts[-3]}/{path.parts[-2]}")
def test_a_generic_pack_is_not_a_bundled_one(path: Path) -> None:
    """It is a test input, never offered to a user by id."""
    loaded = loader.load(str(path))
    assert loaded.bundled is False
    assert loaded.pack.id not in loader.bundled_ids()
