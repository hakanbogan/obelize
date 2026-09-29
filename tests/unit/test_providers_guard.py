"""Guard cases the corpus has no file for: limits, encodings, line endings, import syntax."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from obelize.models import GUARD_REFUSALS, EditProposal
from obelize.native import files
from obelize.providers import base, guard
from platforms import windows_only

SYMBOL = "google.generativeai.GenerativeModel"

# Finding on line 5 in `def ask` (4..6): a 4..6 proposal passes all but the check under test.
SOURCE = b"""import google.generativeai as genai


def ask(prompt):
    model = genai.GenerativeModel("m", generation_config={"seed": 7})
    return model.generate_content(prompt).text
"""


def question(
    *,
    path: str = "app.py",
    line: int = 5,
    span: tuple[int, int] = (4, 6),
    symbol: str | None = SYMBOL,
    to_modules: tuple[str, ...] = ("google.genai",),
) -> base.Consultation:
    return base.Consultation(
        context=base.Context(path, span[0], span[1], "the payload is not read by the guard"),
        line=line,
        column=12,
        symbol=symbol,
        bail="generation_config_not_static",
        pack_id="gemini/google-generativeai-to-google-genai",
        to_package="google-genai",
        to_modules=to_modules,
        limitations=("the pack says what it does not handle",),
    )


def proposal(replacement: str, **overrides: Any) -> EditProposal:
    fields: dict[str, Any] = {
        "path": "app.py",
        "start_line": 4,
        "end_line": 6,
        "symbol": SYMBOL,
        "replacement": replacement,
        "rationale": "because the test says so",
    }
    fields.update(overrides)
    return EditProposal(**fields)


def check(
    root: Path,
    replacement: str,
    *,
    source: bytes = SOURCE,
    consultation: base.Consultation | None = None,
    **overrides: Any,
) -> guard.Checked:
    one = consultation or question()
    (root / one.context.path).write_bytes(source)
    return guard.check(
        proposal(replacement, **overrides), consultation=one, root=root, before=source
    )


def test_the_vocabulary_is_the_fifteen_words_the_adrs_name() -> None:
    """Twelve from ADR-037 D1, three more from D7, for what an import check cannot see."""
    assert {
        "file_changed_since_read",
        "import_outside_the_target",
        "name_outside_the_question",
        "output_does_not_compile",
        "output_does_not_parse",
        "outside_the_context",
        "path_not_python",
        "path_not_the_consulted_file",
        "path_outside_root",
        "replacement_not_displayable",
        "replacement_not_encodable",
        "replacement_runs_past_its_range",
        "replacement_too_large",
        "site_not_replaced",
        "symbol_mismatch",
    } == GUARD_REFUSALS


@pytest.mark.parametrize(
    ("path", "said"),
    [
        pytest.param("/etc/passwd", "absolute", id="absolute"),
        pytest.param("..\\..\\app.py", "forward slashes", id="backslash"),
        pytest.param("pkg//app.py", "empty component", id="empty-component"),
        pytest.param("pkg/../../app.py", "climbs", id="climbs"),
    ],
)
def test_a_path_that_is_not_a_repository_path_is_an_escape(
    path: str, said: str, tmp_path: Path
) -> None:
    """`models._relative_posix_path`'s rules, judged on text so they cannot be raced.

    The detail reaches the report and is pinned since rules overlap (`/x` has an empty component);
    a naive `startswith` would call `pkg/../../app.py` contained.
    """
    checked = check(tmp_path, "pass", path=path)

    assert checked.refusal == "path_outside_root"
    assert not checked.accepted
    assert said in checked.detail


def test_a_name_the_system_reserves_is_an_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed: there `app.py.` is read as `app.py`. The stub answers for the
    whole path only, since a directory's name can be one too."""
    monkeypatch.setattr(files, "reserved", lambda path: path == "pkg/app.py")
    checked = check(tmp_path, "pass", path="pkg/app.py")
    assert checked.refusal == "path_outside_root"
    assert "something else" in checked.detail


@windows_only("POSIX holds the name as written; the stubbed test above refuses it there")
def test_a_name_windows_reads_as_another_file_is_an_escape(tmp_path: Path) -> None:
    """Control: read by path, `app.py.` is `app.py`, so the staleness check alone would pass."""
    checked = check(tmp_path, "pass", path="app.py.")
    assert checked.refusal == "path_outside_root"
    assert (tmp_path / "app.py.").read_bytes() == SOURCE


def test_a_file_that_is_no_longer_there_is_a_file_that_changed(tmp_path: Path) -> None:
    """One word for four outcomes, and the detail line says which (ADR-037 D3)."""
    (tmp_path / "app.py").write_bytes(SOURCE)
    checked = guard.check(proposal("pass"), consultation=question(), root=tmp_path, before=SOURCE)
    assert checked.accepted

    (tmp_path / "app.py").unlink()
    gone = guard.check(proposal("pass"), consultation=question(), root=tmp_path, before=SOURCE)

    assert gone.refusal == "file_changed_since_read"
    assert "cannot be read" in gone.detail


def test_a_context_that_claims_more_lines_than_the_file_has(tmp_path: Path) -> None:
    """`Context.holds` checks the sent range; lines past the file's end must be refused too."""
    checked = check(
        tmp_path,
        "pass",
        consultation=question(span=(4, 99)),
        start_line=7,
        end_line=9,
    )

    assert checked.refusal == "outside_the_context"
    assert "of 6 were sent" in checked.detail


def test_a_question_that_named_no_symbol_is_answered_by_nothing(tmp_path: Path) -> None:
    """Fail closed: a `str` symbol never equals `None`, so the guard deliberately has no branch."""
    checked = check(tmp_path, "pass", consultation=question(symbol=None))

    assert checked.refusal == "symbol_mismatch"


@pytest.mark.parametrize(
    ("count", "refused"),
    [
        pytest.param(guard.REPLACEMENT_LINE_LIMIT, False, id="at-the-limit"),
        pytest.param(guard.REPLACEMENT_LINE_LIMIT + 1, True, id="one-over"),
    ],
)
def test_the_line_limit_counts_lines_and_not_line_breaks(
    count: int, refused: bool, tmp_path: Path
) -> None:
    """The corpus has 81 and nothing at 80, so the boundary is pinned here."""
    checked = check(tmp_path, "\n".join(["pass"] * count))

    assert (checked.refusal == "replacement_too_large") is refused
    if refused:
        assert f"is {count} lines" in checked.detail


@pytest.mark.parametrize(
    ("size", "refused"),
    [
        pytest.param(guard.REPLACEMENT_BYTE_LIMIT, False, id="at-the-limit"),
        pytest.param(guard.REPLACEMENT_BYTE_LIMIT + 1, True, id="one-over"),
    ],
)
def test_the_byte_limit_bounds_the_line_the_line_limit_cannot(
    size: int, refused: bool, tmp_path: Path
) -> None:
    checked = check(tmp_path, "# " + "x" * (size - 2))

    assert (checked.refusal == "replacement_too_large") is refused
    if refused:
        assert f"is {size} bytes" in checked.detail


def test_a_replacement_the_files_encoding_cannot_hold(tmp_path: Path) -> None:
    """Writing it anyway would re-encode the file, rewriting every line."""
    source = b"# -*- coding: latin-1 -*-\nimport google.generativeai as genai\n\n\nx = 1\n"
    checked = check(
        tmp_path,
        "x = 2  # caf→",
        source=source,
        consultation=question(line=5, span=(5, 5)),
        start_line=5,
        end_line=5,
    )

    assert checked.refusal == "replacement_not_encodable"
    assert "iso-8859-1" in checked.detail
    assert "→" in checked.detail


@pytest.mark.parametrize(
    ("source", "replacement", "expected"),
    [
        pytest.param(
            b"import google.generativeai as genai\r\n\r\n\r\nx = 1\r\n",
            "x = 2",
            b"import google.generativeai as genai\r\n\r\n\r\nx = 2\r\n",
            id="crlf",
        ),
        pytest.param(
            b"import google.generativeai as genai\n\n\nx = 1",
            "x = 2",
            b"import google.generativeai as genai\n\n\nx = 2",
            id="no-trailing-newline",
        ),
        pytest.param(
            b"\xef\xbb\xbfimport google.generativeai as genai\n\n\nx = 1\n",
            "x = 2",
            b"\xef\xbb\xbfimport google.generativeai as genai\n\n\nx = 2\n",
            id="bom",
        ),
        pytest.param(
            b"import google.generativeai as genai\n\n\nx = 1\n",
            "x = 2\r\ny = 3",
            b"import google.generativeai as genai\n\n\nx = 2\ny = 3\n",
            id="the-model-sent-crlf-into-an-lf-file",
        ),
        pytest.param(
            b"import google.generativeai as genai\r\n\r\n\r\nx = 1\r\n",
            "x = 2\ny = 3",
            b"import google.generativeai as genai\r\n\r\n\r\nx = 2\r\ny = 3\r\n",
            id="two-lines-into-a-crlf-file",
        ),
        pytest.param(
            b"import google.generativeai as genai\n\n\nx = 1",
            "x = 2\ny = 3",
            b"import google.generativeai as genai\n\n\nx = 2\ny = 3",
            id="two-lines-over-an-unterminated-last-line",
        ),
    ],
)
def test_the_files_own_line_endings_survive_the_splice(
    source: bytes, replacement: str, expected: bytes, tmp_path: Path
) -> None:
    """Bytes in, bytes out (ADR-005): the file's line breaks win over the model's.

    Between replacement lines goes the file's break; after the last goes whatever the replaced
    line ended with, which is nothing for an unterminated last line.
    """
    checked = check(
        tmp_path,
        replacement,
        source=source,
        consultation=question(line=4, span=(4, 4)),
        start_line=4,
        end_line=4,
    )

    assert checked.refusal is None, checked.detail
    assert checked.after == expected


@pytest.mark.parametrize(
    ("replacement", "refused"),
    [
        pytest.param("from google import genai", False, id="the-target-itself"),
        pytest.param("from google.genai import types", False, id="under-the-target"),
        pytest.param("import google.genai", False, id="the-target-as-a-module"),
        pytest.param("import google.genaixyz", True, id="a-near-miss-on-the-target"),
        pytest.param("import os", True, id="a-plain-import"),
        pytest.param("import os.path", True, id="a-dotted-import"),
        pytest.param("from os import system", True, id="a-name-out-of-a-module"),
        pytest.param("from os import *", True, id="a-star-import"),
        pytest.param("from . import sibling", True, id="a-relative-import"),
        pytest.param("from .pkg import sibling", True, id="a-relative-dotted-import"),
        pytest.param('import importlib; importlib.import_module("os")', True, id="by-function"),
        pytest.param('from importlib import import_module\nimport_module("os")', True, id="bare"),
        pytest.param('__import__("os")', True, id="by-builtin"),
        pytest.param('__import__("google.genai")', False, id="the-target-by-builtin"),
        pytest.param("name = 'os'\n__import__(name)", True, id="computed"),
        pytest.param('__import__(b"os")', True, id="not-even-a-string"),
        pytest.param("__import__()", True, id="no-argument-at-all"),
        pytest.param('(lambda one: one)("os")', False, id="a-call-that-is-not-an-import"),
        pytest.param('[0][0].import_module("os")', False, id="a-receiver-that-is-not-a-name"),
    ],
)
def test_which_imports_a_proposal_may_introduce(
    replacement: str, refused: bool, tmp_path: Path
) -> None:
    """ADR-037 D7. The last two are not imports: `_dotted` must answer `None`, not raise."""
    checked = check(tmp_path, replacement)

    assert (checked.refusal == "import_outside_the_target") is refused, checked.detail
    if refused:
        assert "this pack targets ['google.genai']" in checked.detail


# Already imports both import functions, so only call detection can see a replacement calling
# one. Finding on line 8; `def ask` is the context.
IMPORTLIB_SOURCE = b"""import importlib
from importlib import import_module

import google.generativeai as genai


def ask(prompt):
    model = genai.GenerativeModel("m", generation_config={"seed": 7})
    return model.generate_content(prompt).text
"""


@pytest.mark.parametrize(
    ("replacement", "refused"),
    [
        pytest.param('    importlib.import_module("os")', True, id="dotted"),
        pytest.param('    import_module("os")', True, id="bare"),
        pytest.param('    __import__("os")', True, id="builtin"),
        pytest.param("    model = None", False, id="nothing-imported-at-all"),
    ],
)
def test_an_import_function_is_seen_where_no_import_statement_is(
    replacement: str, refused: bool, tmp_path: Path
) -> None:
    """No new import statement here, so any refusal comes from the call check (ADR-037 D7)."""
    checked = check(
        tmp_path,
        replacement,
        source=IMPORTLIB_SOURCE,
        consultation=question(line=8, span=(7, 9)),
        start_line=8,
        end_line=8,
    )

    assert (checked.refusal == "import_outside_the_target") is refused, checked.detail


def test_an_import_the_file_already_had_is_not_a_new_one(tmp_path: Path) -> None:
    """The check is a difference against the file's own imports, not a permission list."""
    source = b"import os\nimport google.generativeai as genai\n\n\nx = os.getpid()\n"
    checked = check(
        tmp_path,
        "x = os.getppid()",
        source=source,
        consultation=question(line=5, span=(5, 5)),
        start_line=5,
        end_line=5,
    )

    assert checked.refusal is None, checked.detail


def test_a_pack_that_renames_no_import_licenses_no_new_import(tmp_path: Path) -> None:
    """Fail closed on an empty target set, which is representable."""
    checked = check(
        tmp_path,
        "from google import genai",
        consultation=question(to_modules=()),
    )

    assert checked.refusal == "import_outside_the_target"
    assert "targets []" in checked.detail


def test_the_guard_changes_no_file_whatever_it_decides(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_bytes(SOURCE)
    accepted = guard.check(
        proposal("def ask(prompt):\n    return None"),
        consultation=question(),
        root=tmp_path,
        before=SOURCE,
    )

    assert accepted.refusal is None, accepted.detail
    assert accepted.after is not None
    assert accepted.after != SOURCE
    assert (tmp_path / "app.py").read_bytes() == SOURCE


def test_a_module_the_file_already_imports_is_not_a_name_the_question_licensed(
    tmp_path: Path,
) -> None:
    """The import check sees nothing new, but the replaced lines never named `os`."""
    source = b"import os\nimport google.generativeai as genai\n\n\nx = genai.GenerativeModel()\n"
    checked = check(
        tmp_path,
        'x = os.system("id")',
        source=source,
        consultation=question(line=5, span=(5, 5)),
        start_line=5,
        end_line=5,
    )
    assert checked.refusal == "name_outside_the_question"
    assert "'os'" in checked.detail


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("    model = ().__class__", id="a-dunder-attribute"),
        pytest.param("    model = __name__", id="a-dunder-name"),
        pytest.param("    model = globals()", id="a-builtin-that-is-not-admitted"),
    ],
)
def test_a_dunder_or_an_unadmitted_builtin_is_refused(replacement: str, tmp_path: Path) -> None:
    checked = check(tmp_path, replacement, start_line=5, end_line=5)
    assert checked.refusal == "name_outside_the_question", checked.detail


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("    model = genai.GenerativeModel()", id="the-replaced-lines-own-names"),
        pytest.param(
            "    client = len(str(None))\n    model = client", id="a-name-it-binds-itself"
        ),
        pytest.param(
            "    from google import genai as fresh\n    model = fresh.Client()",
            id="a-name-the-target-import-binds",
        ),
        pytest.param("    model = [n for n in range(3)]", id="a-comprehension-variable"),
        pytest.param("    model = generation_config = None", id="a-keyword-the-lines-named"),
        pytest.param("    model = (lambda seed: seed)(None)", id="a-parameter-it-declares"),
        pytest.param("    model = dict(seed=7)", id="a-keyword-argument-is-not-a-name-it-reaches"),
    ],
)
def test_names_the_question_licenses_are_accepted(replacement: str, tmp_path: Path) -> None:
    """A guard that refused every name would pass the tests above."""
    checked = check(tmp_path, replacement, start_line=5, end_line=5)
    assert checked.refusal is None, checked.detail


# Line 5 follows the finding (line 4) so a trailing backslash can join it and still compile.
SWALLOW_SOURCE = b"""import google.generativeai as genai


model = genai.GenerativeModel("m")
require_auth()
"""


def test_a_replacement_that_runs_past_its_range_is_refused(tmp_path: Path) -> None:
    """A trailing `\\` swallows unsent line 5 into the lambda; it parses and compiles."""
    checked = check(
        tmp_path,
        "model = lambda: \\",
        source=SWALLOW_SOURCE,
        consultation=question(line=4, span=(4, 4)),
        start_line=4,
        end_line=4,
    )
    assert checked.refusal == "replacement_runs_past_its_range", checked.detail


def test_a_replacement_that_ends_inside_a_block_of_its_own_is_not_running_past_it(
    tmp_path: Path,
) -> None:
    """Its block closing on the next line follows its own indentation, not an edit to that line."""
    checked = check(tmp_path, "    if True:\n        model = None", start_line=5, end_line=5)
    assert checked.refusal is None, checked.detail


def test_a_replacement_that_ends_where_its_range_ends_is_not_running_past_it(
    tmp_path: Path,
) -> None:
    checked = check(
        tmp_path,
        "model = None",
        source=SWALLOW_SOURCE,
        consultation=question(line=4, span=(4, 4)),
        start_line=4,
        end_line=4,
    )
    assert checked.refusal is None, checked.detail


def test_a_star_import_of_the_target_licenses_no_name(tmp_path: Path) -> None:
    """It passes the import check but binds unseen names; a replacement must name what it uses."""
    source = b"import google.generativeai as genai\n\n\nmodel = genai.GenerativeModel()\n"
    checked = check(
        tmp_path,
        "from google.genai import *\nmodel = Client()",
        source=source,
        consultation=question(line=4, span=(4, 4)),
        start_line=4,
        end_line=4,
    )
    assert checked.refusal == "name_outside_the_question"
    assert "'Client'" in checked.detail
