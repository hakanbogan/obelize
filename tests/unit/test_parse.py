"""The three input gates: which one refuses, what it says, and what it never says."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import libcst as cst
import pytest

from obelize.models import BAIL_CODES, SKIP_REASONS, Config, ReceiverMethods, ScanSpec
from obelize.native import files
from obelize.scan import parse
from obelize.scan.parse import (
    MESSAGE_LIMIT,
    PARSE_BAIL,
    READ_REFUSALS,
    ROUNDTRIP_BAIL,
    Limitation,
    Read,
    candidate,
    contents,
    gates,
    read,
)
from platforms import AS_ROOT, deny

ENCODING = Path(__file__).resolve().parents[1] / "fixtures" / "scan" / "encoding"

# Hand-built, so the reader is tested without loading a pack.
SPEC = ScanSpec(
    pack_id="gemini/google-generativeai-to-google-genai",
    pack_version="0.1.0",
    pack_sha256="a" * 64,
    legacy_modules=("google.generativeai",),
    legacy_distribution="google-generativeai",
    new_distribution="google-genai",
    prefilter_tokens=("generativeai",),
    client_symbol="google.generativeai.configure",
    requires_python=">=3.10",
    constructor_symbols=("google.generativeai.GenerativeModel",),
    supported_methods=(
        ReceiverMethods(
            receiver="google.generativeai.GenerativeModel",
            methods=("generate_content",),
        ),
    ),
)

# The four encoding fixtures that pass all three gates.
CLEAN = ("crlf.py", "latin1_cookie.py", "utf8_bom.py", "no_trailing_newline.py")


def _fixture(name: str) -> bytes:
    return (ENCODING / name).read_bytes()


def test_every_limitation_code_is_one_the_documents_already_publish() -> None:
    """No new vocabulary: `limitations[].code` draws only on bail codes and skip reasons."""
    assert READ_REFUSALS <= (BAIL_CODES | SKIP_REASONS)
    assert sorted(READ_REFUSALS & BAIL_CODES) == ["file_too_large", "input_does_not_parse"]
    assert sorted(READ_REFUSALS & SKIP_REASONS) == ["unreadable"]


def test_every_refusal_carries_a_sentence() -> None:
    """Keyed by the whole set, so a new code cannot ship without a sentence."""
    assert set(parse._DETAIL) == READ_REFUSALS
    for code, sentence in parse._DETAIL.items():
        assert sentence.endswith("."), code
        assert len(sentence) > 40, code


def test_the_two_bail_codes_are_the_ones_the_vocabulary_names() -> None:
    assert PARSE_BAIL in BAIL_CODES
    assert ROUNDTRIP_BAIL in BAIL_CODES
    assert {PARSE_BAIL, ROUNDTRIP_BAIL} < BAIL_CODES


@pytest.mark.parametrize("name", CLEAN)
def test_a_file_that_passes_every_gate_comes_back_with_its_tree(name: str) -> None:
    data = _fixture(name)
    result = gates(name, data)
    assert result.status == "parsed"
    assert result.bail is None
    assert result.module is not None
    assert result.data == data
    assert result.findings == ()
    assert result.limitations == ()


@pytest.mark.parametrize("name", CLEAN)
def test_the_tree_of_a_clean_file_reproduces_its_bytes(name: str) -> None:
    """Through the gate, not libcst: a reader that decoded to `str` would fail only here."""
    result = gates(name, _fixture(name))
    assert result.module is not None
    assert result.module.bytes == _fixture(name)


def test_a_file_that_does_not_round_trip_is_still_analysed() -> None:
    """A tree comes out, so analysis runs under the bail; no `parse_error`, since it parsed."""
    data = _fixture("bare_cr.py")
    result = gates("bare_cr.py", data)
    assert result.status == "parsed"
    assert result.bail == ROUNDTRIP_BAIL
    assert result.module is not None
    assert result.module.bytes != data
    assert result.findings == ()
    assert result.limitations == ()


def test_a_chain_too_long_to_render_is_one_unparsable_file_and_not_a_crash() -> None:
    """libcst renders a tree one frame per level, so a chain of hundreds of terms overruns it."""
    source = ("x = " + " + ".join(["1"] * 900) + "\n").encode()
    result = gates("long.py", source)
    assert result.status == "does_not_parse"
    assert [finding.bail for finding in result.findings] == [PARSE_BAIL]


def test_a_python_2_file_is_refused_by_the_compile_gate() -> None:
    """libcst parses and round-trips Python 2, so only `compile()` can refuse it."""
    data = _fixture("python2.py")
    assert cst.parse_module(data).bytes == data

    result = gates("python2.py", data)
    assert result.status == "does_not_parse"
    assert result.module is None
    assert result.bail is None
    finding = result.findings[0]
    assert (finding.line, finding.column) == (7, 0)
    assert result.limitations[0].detail.startswith(parse._DETAIL[PARSE_BAIL])
    assert "Refused by compile:" in result.limitations[0].detail


def test_a_file_libcst_refuses_never_reaches_the_compile_gate() -> None:
    """libcst blames line 8 and `compile()` line 6, so the line shows which gate ran first."""
    data = _fixture("parser_syntax_error.py")
    result = gates("parser_syntax_error.py", data)
    assert result.status == "does_not_parse"
    finding = result.findings[0]
    assert (finding.line, finding.column) == (8, 4)
    assert finding.line != 6
    assert "Refused by libcst:" in result.limitations[0].detail


@pytest.mark.parametrize("name", ["python2.py", "parser_syntax_error.py"])
def test_the_one_finding_of_an_unparsable_file_names_no_symbol(name: str) -> None:
    """Ground truth shows the offending line; the runtime must keep source out of the evidence."""
    result = gates(name, _fixture(name))
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind == "parse_error"
    assert finding.confidence_reason == "parse_error"
    assert finding.scan_status == "unsupported"
    assert finding.bail == PARSE_BAIL
    assert finding.symbol is None
    assert finding.evidence is None
    assert finding.path == name


def test_the_compile_gate_wins_when_a_file_fails_that_one_and_the_round_trip() -> None:
    """`compile()` refuses it everywhere: one finding, not analysis under the round-trip bail."""
    data = b"import google.generativeai as genai\rfrom __future__ import print_function\rx = 1\r"
    module = cst.parse_module(data)
    assert module.bytes != data

    result = gates("legacy/tool.py", data)
    assert result.status == "does_not_parse"
    assert result.findings[0].bail == PARSE_BAIL
    assert result.bail is None


def test_survived_both_parse_gates_is_exactly_the_parsed_status() -> None:
    """`files_parsed` counts `status == "parsed"`, which includes a file failing the round-trip."""
    for name in (*CLEAN, "bare_cr.py", "python2.py", "parser_syntax_error.py"):
        data = _fixture(name)
        accepted = True
        try:
            cst.parse_module(data)
            compile(data, name, "exec")
        except (cst.ParserSyntaxError, SyntaxError, ValueError):
            accepted = False
        assert (gates(name, data).status == "parsed") is accepted, name


# Shapes where a gate raises outside the documented type; measured on 3.12, 3.13 and 3.14.
AWKWARD: dict[str, bytes] = {
    # libcst: ParserSyntaxError. compile(): SyntaxError with `lineno=None`.
    "a null byte": b"import google.generativeai as genai\nx = 1\x00\n",
    # libcst: plain `SyntaxError`, `lineno=None`. compile(): SyntaxError, `lineno=0`.
    "an unknown coding cookie": b"# -*- coding: nonsense-42 -*-\nimport x\n",
    # libcst: plain `SyntaxError`. compile(): accepts it, the mirror of `python2.py`.
    "a non-UTF-8 byte and no cookie": b"# a lone latin-1 byte: \xe9\nimport x\n",
    # libcst: `UnicodeDecodeError`, a `ValueError` the documented handler would let out.
    "bytes that contradict the cookie": b'# -*- coding: utf-8 -*-\nX = "caf\xe9"\n',
    # libcst: plain `SyntaxError`. compile(): null bytes again.
    "UTF-16 source": "x = 1\n".encode("utf-16"),
}


@pytest.mark.parametrize("shape", sorted(AWKWARD), ids=sorted(AWKWARD))
def test_an_awkward_byte_shape_is_refused_and_not_raised(shape: str) -> None:
    """Catching `SyntaxError` alone lets libcst's `UnicodeDecodeError` out and ends the run."""
    result = gates("odd.py", AWKWARD[shape])
    assert result.status in {"parsed", "does_not_parse"}
    if result.status == "does_not_parse":
        assert result.findings[0].bail == PARSE_BAIL


@pytest.mark.parametrize("shape", sorted(AWKWARD), ids=sorted(AWKWARD))
def test_a_refusal_always_has_coordinates_a_finding_can_hold(shape: str) -> None:
    """These give `lineno` None or 0 and `Finding.line` must be `>= 1`: the floor stops a crash."""
    result = gates("odd.py", AWKWARD[shape])
    if result.status == "does_not_parse":
        assert result.findings[0].line >= 1
        assert result.findings[0].column >= 0


def test_a_refusal_records_the_parsers_words_and_never_a_line_of_the_file() -> None:
    """`str(exc)` embeds a source excerpt; the control proves it, so this cannot pass vacuously."""
    data = _fixture("parser_syntax_error.py")
    detail = gates("pkg/mailer.py", data).limitations[0].detail

    with pytest.raises(cst.ParserSyntaxError) as excinfo:
        cst.parse_module(data)
    context = excinfo.value.context
    assert context is not None
    assert context.startswith('    model = genai.GenerativeModel("gemini-1.5-flash")')
    assert context.rstrip().endswith("^")
    assert context in str(excinfo.value)

    assert context.splitlines()[0] not in detail
    assert "GenerativeModel" not in detail
    assert "gemini-1.5-flash" not in detail
    # The excerpt is two lines; a lone `^` proves nothing, as libcst lists it as an expected token.
    assert "\n" not in detail
    assert "parser error" in detail


def test_compile_is_given_the_relative_path_so_no_absolute_path_can_leak() -> None:
    """The control reads `.filename`: `str()` shows only the basename and 3.14's `repr` drops it."""
    data = _fixture("python2.py")
    absolute = os.path.abspath("/var/folders/xy/somewhere/pkg/legacy.py")
    with pytest.raises(SyntaxError) as excinfo:
        compile(data, absolute, "exec")
    assert excinfo.value.filename == absolute
    assert absolute not in str(excinfo.value)

    limitation = gates("pkg/legacy.py", data).limitations[0]
    assert limitation.path == "pkg/legacy.py"
    assert absolute not in limitation.detail
    assert "legacy.py" not in limitation.detail


def test_a_message_that_is_missing_or_enormous_does_not_become_the_report() -> None:
    """`SyntaxError().msg` is `None`, and libcst's expected-token list alone is 160 characters."""
    assert parse._message(SyntaxError()) == ""
    assert parse._message(SyntaxError("")) == ""
    assert parse._message(SyntaxError("first line\nsecond line")) == "first line"

    long_message = parse._message(SyntaxError("x" * 300))
    assert len(long_message) == MESSAGE_LIMIT
    assert long_message.endswith("...")


def test_a_decode_error_has_no_coordinates_and_says_so() -> None:
    """`UnicodeDecodeError` carries neither `.raw_line` nor `.lineno`."""
    error = UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid start byte")
    assert parse._coordinates(error) == (1, 0)
    assert "invalid start byte" in parse._message(error)


# Syntax and the version that introduced it, taken from each PEP rather than measured.
MODERN: dict[str, tuple[tuple[int, int], bytes]] = {
    "a PEP 695 type alias": ((3, 12), b"type Alias = int\n"),
    "a PEP 695 generic function": ((3, 12), b"def f[T](x: T) -> T:\n    return x\n"),
    "a PEP 701 nested quote": ((3, 12), b'x = f"{"inner"}"\n'),
    "an except* group": ((3, 11), b"try:\n    pass\nexcept* ValueError:\n    pass\n"),
    "a PEP 758 except without parentheses": (
        (3, 14),
        b"try:\n    pass\nexcept ValueError, TypeError:\n    pass\n",
    ),
    "a PEP 750 template string": ((3, 14), b'name = "x"\ngreeting = t"hi {name}"\n'),
}


@pytest.mark.parametrize("shape", sorted(MODERN), ids=sorted(MODERN))
def test_the_compile_gate_is_the_interpreters_answer_and_not_libcsts(shape: str) -> None:
    """Older interpreters refuse newer syntax: fail-closed, reported and never edited."""
    introduced, source = MODERN[shape]
    assert cst.parse_module(source).bytes == source
    parsed = gates("modern.py", source).status == "parsed"
    assert parsed is (sys.version_info >= introduced)
    assert "newer Python" in parse._DETAIL[PARSE_BAIL]


def test_compile_is_stronger_than_parsing_which_is_why_it_is_the_gate() -> None:
    """Each is a valid tree but not a program; `ast.parse` would add nothing to libcst."""
    import ast

    for source in (
        b"import google.generativeai as genai\nreturn 1\n",
        b"x = await f()\n",
        b"def f(a, a):\n    pass\n",
        b"nonlocal x\n",
    ):
        assert cst.parse_module(source).bytes == source
        assert ast.parse(source) is not None
        assert gates("odd.py", source).status == "does_not_parse"


def test_the_prefilter_matches_raw_bytes_and_decides_nothing_about_encoding() -> None:
    """Public: the excluded-file report and the manifest scan must agree with the scanner."""
    assert candidate(b"import google.generativeai as genai\n", ("generativeai",))
    assert not candidate(b"from google import genai\n", ("generativeai",))
    assert candidate(_fixture("latin1_cookie.py"), ("generativeai",))
    assert candidate(b"x = 1\ngenerativeai\n", ("nothing", "generativeai"))
    assert not candidate(b"x = 1\n", ())


def _root(tmp_path: Path, name: str, data: bytes) -> Path:
    (tmp_path / name).write_bytes(data)
    return tmp_path


def test_reading_a_selected_file_returns_its_bytes_and_its_tree(tmp_path: Path) -> None:
    data = _fixture("crlf.py")
    root = _root(tmp_path, "app.py", data)
    result = read(root, "app.py", SPEC, Config())
    assert result.status == "parsed"
    assert result.data == data
    assert result.module is not None


def test_a_file_the_prefilter_eliminates_is_never_parsed(tmp_path: Path) -> None:
    """Most files end here (97.81% in ADR-005); only a file the reader could not see owes a row."""
    root = _root(tmp_path, "notes.py", b"from google import genai\n")
    result = read(root, "notes.py", SPEC, Config())
    assert result.status == "not_a_candidate"
    assert result.module is None
    assert result.limitations == ()
    assert result.data == b"from google import genai\n"


def test_a_file_over_the_limit_is_not_read_at_all(tmp_path: Path) -> None:
    """The limit applies to the `lstat` size, before reading; the row names both numbers."""
    root = _root(tmp_path, "huge.py", b"generativeai\n" * 100)
    result = read(root, "huge.py", SPEC, Config(max_file_bytes=64))
    assert result.status == "not_read"
    assert result.data is None
    assert result.limitations[0].code == "file_too_large"
    assert "1300 bytes against a limit of 64" in result.limitations[0].detail


def test_a_path_that_is_gone_by_the_time_it_is_read_is_unreadable(tmp_path: Path) -> None:
    result = read(tmp_path, "vanished.py", SPEC, Config())
    assert result.status == "not_read"
    assert result.limitations[0].code == "unreadable"


def test_a_name_that_became_a_symlink_after_the_selection_is_not_followed(
    tmp_path: Path,
) -> None:
    """A check before open can be raced; only `O_NOFOLLOW` on the open itself closes the hole."""
    secret = tmp_path / "outside.py"
    secret.write_bytes(b"import google.generativeai as genai\n")
    (tmp_path / "app.py").symlink_to(secret)

    result = read(tmp_path, "app.py", SPEC, Config())
    assert result.status == "not_read"
    assert result.limitations[0].code == "unreadable"
    assert result.data is None


@pytest.mark.skipif(AS_ROOT, reason="chmod means nothing to root")
def test_a_file_whose_permissions_hide_it_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "sealed.py"
    path.write_bytes(b"import google.generativeai as genai\n")
    with deny(path):
        result = read(tmp_path, "sealed.py", SPEC, Config())
    assert result.status == "not_read"
    assert result.limitations[0].code == "unreadable"


def test_the_reader_opens_each_file_exactly_once(tmp_path: Path, monkeypatch: Any) -> None:
    """A second open could see bytes other than the ones graded (ADR-016 D5)."""
    opened: list[str] = []
    real_open = files.open_path

    def counting_open(path: Path) -> int:
        opened.append(str(path))
        return real_open(path)

    monkeypatch.setattr(files, "open_path", counting_open)
    root = _root(tmp_path, "app.py", _fixture("crlf.py"))
    assert read(root, "app.py", SPEC, Config()).status == "parsed"
    assert opened == [str(root / "app.py")]


def test_the_bytes_are_handed_over_without_a_gate_for_a_file_that_is_not_python(
    tmp_path: Path,
) -> None:
    """Manifests and excluded files, never parsed, share this size limit and `O_NOFOLLOW` open."""
    (tmp_path / "requirements.txt").write_text(
        "google-generativeai==0.8.6\n", encoding="utf-8", newline="\n"
    )
    data, limitations = contents(tmp_path, "requirements.txt", Config())
    assert data == b"google-generativeai==0.8.6\n"
    assert limitations == ()

    data, limitations = contents(tmp_path, "requirements.txt", Config(max_file_bytes=4))
    assert data is None
    assert [row.code for row in limitations] == ["file_too_large"]

    data, limitations = contents(tmp_path, "gone.txt", Config())
    assert data is None
    assert [row.code for row in limitations] == ["unreadable"]


MODULE = cst.parse_module("x = 1\n")

# Each row is a complete call: the checks run in order, so a shared base would pick which fires.
INCOHERENT: list[tuple[dict[str, Any], str]] = [
    ({"status": "parsed", "data": b"x = 1\n"}, "a tree exists exactly when"),
    (
        {"status": "parsed", "data": b"x = 1\n", "module": MODULE, "bail": "file_too_large"},
        "the only file-wide bail",
    ),
    ({"status": "does_not_parse", "data": b"x = 1\n"}, "exactly one finding"),
    ({"status": "not_read", "data": b"x = 1\n"}, "the bytes are absent exactly when"),
    ({"status": "not_read"}, "owes the report one row"),
    ({"status": "parsed", "module": MODULE}, "the bytes are absent exactly when"),
]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    INCOHERENT,
    ids=["no tree", "a foreign bail", "no finding", "bytes it never read", "no row", "no bytes"],
)
def test_a_read_cannot_hold_a_combination_that_means_nothing(
    kwargs: dict[str, Any], message: str
) -> None:
    """Unchecked, each would fail much later, as a file that quietly produced nothing."""
    with pytest.raises(ValueError, match=message):
        Read(path="a.py", **kwargs)


def test_the_ordinary_combinations_are_accepted() -> None:
    """The counterpart of the five checks above, so none of them is vacuous."""
    module = cst.parse_module("x = 1\n")
    assert Read(path="a.py", status="parsed", data=b"x = 1\n", module=module).bail is None
    assert (
        Read(path="a.py", status="parsed", data=b"x = 1\n", module=module, bail=ROUNDTRIP_BAIL).bail
        == ROUNDTRIP_BAIL
    )
    assert Read(path="a.py", status="not_a_candidate", data=b"x").findings == ()
    assert (
        Read(
            path="a.py",
            status="not_read",
            limitations=(Limitation(path="a.py", code="unreadable", detail="Gone."),),
        ).data
        is None
    )


@pytest.mark.parametrize("data", [None, b"x = 1\n"], ids=["dropped", "kept"])
def test_a_file_no_pack_looks_at_may_or_may_not_keep_its_bytes(data: bytes | None) -> None:
    assert parse.Read(path="a.py", status="not_a_candidate", data=data).data == data
