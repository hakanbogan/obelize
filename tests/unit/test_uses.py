"""`obelize.packtools.uses`: the names of a library that a repository's code reaches."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obelize.packtools import uses
from support import write_tree

if TYPE_CHECKING:
    from pathlib import Path

CODE = """\
import numpy
import pandas as pd
import pandas.io.json
from pandas import DataFrame as DF, read_csv
from . import sibling
from .pandas import hidden


def work():
    frame = pd.DataFrame.from_records([])
    other = DF()
    text = pandas.io.json.read_json
    return numpy.array, frame, other, text, read_csv, sibling, hidden, pd.DataFrame
"""


def test_the_names_reached_through_every_form_of_import_are_found(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"app.py": CODE, "notes.txt": "pandas.nothing", "bad.py": "def (:"})
    assert uses.names(root, "pandas") == frozenset(
        {"DataFrame", "DataFrame.from_records", "io", "io.json", "io.json.read_json", "read_csv"}
    )
    assert uses.names(root, "numpy") == frozenset({"array"})
    assert uses.names(root, "scipy") == frozenset()


def test_a_star_import_leaves_no_telling_which_names_are_used(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"a.py": "import pandas\n", "b.py": "from pandas import *\n"})
    assert uses.names(root, "pandas") is None
    assert uses.names(root, "numpy") == frozenset()


def test_a_star_import_of_another_module_is_no_matter(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path, {"a.py": "from os.path import *\nimport pandas as pd\npd.read_csv\n"}
    )
    assert uses.names(root, "pandas") == frozenset({"read_csv"})


def test_a_file_too_large_to_be_hand_written_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uses, "FILE_BYTES", 10)
    root = write_tree(tmp_path, {"a.py": "import pandas as pd\npd.read_csv\n"})
    assert uses.names(root, "pandas") == frozenset()
