"""The documentation site's navigation names every page, and no page it names is missing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

# `mkdocs_hooks.py` publishes the repository's changelog as a page at build time.
GENERATED = {"CHANGELOG.md"}


def _pages(nav: Any) -> set[str]:
    if isinstance(nav, str):
        return {nav}
    if isinstance(nav, list):
        return {page for entry in nav for page in _pages(entry)}
    if isinstance(nav, dict):
        return {page for entry in nav.values() for page in _pages(entry)}
    return set()


def _navigation() -> set[str]:
    document = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    return _pages(document["nav"])


def test_every_page_the_navigation_names_exists() -> None:
    missing = sorted(page for page in _navigation() - GENERATED if not (DOCS / page).is_file())
    assert missing == []


def test_every_page_in_docs_is_in_the_navigation() -> None:
    pages = {path.name for path in DOCS.glob("*.md")}
    assert sorted(pages - _navigation()) == []
