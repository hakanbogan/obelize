"""`rename_symbol` for a name that stays in its module: `acme.kit.old_greet` is `acme.kit.greet`.

The pack is `tests/packs/generic/acme/kit-1-to-2`, an invented library whose 2.x renamed a function.
"""

from __future__ import annotations

from pathlib import Path

import acme
import pytest

from obelize.models import Edit
from obelize.packs import loader
from obelize.packs.schema import RenameSymbolChange
from obelize.transforms.kinds.rename_symbol import RenameSymbol

PACK = Path(__file__).resolve().parents[1] / "packs" / "generic" / "acme" / "kit-1-to-2"
LOADED = loader.load(str(PACK / "pack.yaml"))
SPEC = loader.to_scan_spec(LOADED)
(RENAME,) = [change for change in LOADED.pack.changes if isinstance(change, RenameSymbolChange)]
REFUSING = RENAME.model_copy(
    update={"params": RENAME.params.model_copy(update={"calls": "refused"})}
)


def tidy(source: str, change: RenameSymbolChange = RENAME) -> tuple[str, list[Edit]]:
    return acme.transform(source, change, spec=SPEC)


@pytest.mark.parametrize(
    ("source", "written"),
    [
        (
            "import acme.kit\n\nacme.kit.old_greet('x')\n",
            "import acme.kit\n\nacme.kit.greet('x')\n",
        ),
        (
            "import acme.kit\n\nhandler = acme.kit.old_greet\n",
            "import acme.kit\n\nhandler = acme.kit.greet\n",
        ),
        ("import acme.kit as k\n\nk.old_greet(1)\n", "import acme.kit as k\n\nk.greet(1)\n"),
        (
            "import acme.kit\n\nx = [acme.kit.old_greet(n) for n in range(3)]\n",
            "import acme.kit\n\nx = [acme.kit.greet(n) for n in range(3)]\n",
        ),
        (
            "import acme.kit\n\nacme.kit.old_greet(\n    'x',  # why\n)\n",
            "import acme.kit\n\nacme.kit.greet(\n    'x',  # why\n)\n",
        ),
    ],
)
def test_a_reference_takes_the_new_name_and_nothing_else_changes(source: str, written: str) -> None:
    code, edits = tidy(source)
    assert code == written
    assert {row.status for row in edits} == {"auto"}


@pytest.mark.parametrize(
    ("source", "written"),
    [
        (
            "from acme.kit import old_greet\n\nold_greet(1)\n",
            "from acme.kit import greet\n\ngreet(1)\n",
        ),
        (
            "from acme.kit import old_greet as hello\n\nhello(1)\n",
            "from acme.kit import greet as hello\n\nhello(1)\n",
        ),
        (
            "from acme.kit import Client, old_greet\n\nold_greet(Client)\n",
            "from acme.kit import Client, greet\n\ngreet(Client)\n",
        ),
        (
            "from acme.kit import (\n    Client,\n    old_greet,\n)\n\nold_greet(Client)\n",
            "from acme.kit import (\n    Client,\n    greet,\n)\n\ngreet(Client)\n",
        ),
        (
            "import acme.kit\nfrom acme.kit import old_greet\n\nold_greet(acme.kit.Client)\n",
            "import acme.kit\nfrom acme.kit import greet\n\ngreet(acme.kit.Client)\n",
        ),
    ],
)
def test_the_name_on_a_from_import_line_follows_the_rename_and_so_do_its_uses(
    source: str, written: str
) -> None:
    code, edits = tidy(source)
    assert code == written
    assert {row.status for row in edits} == {"auto"}


def test_a_name_the_module_kept_is_left_alone() -> None:
    source = "import acme.kit\nfrom acme.kit import Client\n\nacme.kit.other(Client)\n"
    code, edits = tidy(source)
    assert code == source
    assert edits == []


def test_a_new_name_the_file_already_binds_is_a_collision_and_the_import_is_left() -> None:
    source = "from acme.kit import greet, old_greet\n\nold_greet(greet)\n"
    code, edits = tidy(source)
    assert "alias_collision" in {row.reason for row in edits}
    assert "from acme.kit import greet, old_greet" in code


def test_a_new_name_a_from_import_aliases_away_is_no_collision() -> None:
    source = (
        "from acme.kit import greet\nfrom acme.kit import old_greet as greet2\n\ngreet2(greet)\n"
    )
    code, edits = tidy(source)
    assert code == (
        "from acme.kit import greet\nfrom acme.kit import greet as greet2\n\ngreet2(greet)\n"
    )
    assert {row.status for row in edits} == {"auto"}


def test_a_call_is_refused_unless_the_pack_allows_calls() -> None:
    source = "import acme.kit\n\nacme.kit.old_greet(1)\nhandler = acme.kit.old_greet\n"
    code, edits = tidy(source, REFUSING)
    assert [(row.status, row.reason) for row in edits] == [
        ("needs_review", "error_class_changed"),
        ("auto", None),
    ]
    assert code == "import acme.kit\n\nacme.kit.old_greet(1)\nhandler = acme.kit.greet\n"


def test_the_rule_says_what_it_renames_so_the_planner_can_keep_it_out_of_the_way() -> None:
    assert RenameSymbol(RENAME).renames == frozenset({"acme.kit.old_greet"})


def test_a_pack_that_both_moves_and_renames_claims_each_name_once() -> None:
    change = RENAME.model_copy(
        update={
            "params": RENAME.params.model_copy(update={"symbols": {"acme.kit.faults.Busy": "Busy"}})
        }
    )
    assert RenameSymbol(change).renames == frozenset({"acme.kit.old_greet", "acme.kit.faults.Busy"})
