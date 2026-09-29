"""Every `complete: true` `.after.py` key binds every name it reads.

A byte-comparing gate agrees with a key that expects a `NameError`. Incomplete keys are files a run
would not write, and some hold the defect on purpose.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from unresolved import names_unresolved

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms"
CORPORA = ("configure_to_client", "generative_model_calls", "rename_import", "rewrite_call")


def complete_keys() -> list[Path]:
    keys: list[Path] = []
    for corpus in CORPORA:
        key = yaml.safe_load((ROOT / corpus / "answers.yaml").read_text(encoding="utf-8"))
        keys += [
            ROOT / corpus / f"{case['file']}.after.py"
            for case in key["cases"]
            if case.get("complete")
        ]
    return keys


def test_every_complete_key_binds_every_name_it_reads() -> None:
    keys = complete_keys()
    assert len(keys) == 57, "the four corpora's complete keys, counted when this was written"
    assert names_unresolved(*keys) == ""


def test_the_check_finds_a_name_nothing_binds(tmp_path: Path) -> None:
    """Control: a check that passes everything would pass the keys too."""
    planted = tmp_path / "planted.py"
    planted.write_text("def go():\n    return client.models\n", encoding="utf-8")
    assert "F821" in names_unresolved(planted)
