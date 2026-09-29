#!/usr/bin/env python3
"""Generator for the byte-level scan fixtures in this directory.

These files exist for their exact bytes -- CRLF, a latin-1 coding cookie, a
UTF-8 BOM, bare-CR line endings, Python 2 syntax, a missing final newline, an
unclosed bracket -- so they are written from byte literals here rather than
typed into an editor, where an editor or a git filter would quietly normalise
them.

Run from the repository root:

    uv run python tests/fixtures/scan/encoding/_build.py            # write, then verify
    uv run python tests/fixtures/scan/encoding/_build.py --check    # verify only, exit 1 on drift

The verification block prints, per file: ``repr(data[:80])``,
``cst.parse_module(data).bytes == data`` and whether ``compile(data, name,
"exec")`` raises.  The answers recorded in ``ground_truth.yaml`` are the ones
this script observed, not predictions.

``parser_syntax_error.py`` is the one file libcst itself refuses, and it is the
reason this script has two expectation tables instead of one: there is no
round-trip to compare when no tree was built.  It was added for COVERAGE.md gap
15 -- the ``cst.ParserSyntaxError`` branch, which ``python2.py`` cannot reach
because libcst parses Python 2 happily.  The two gates disagree about where it
went wrong, by two lines, and both numbers are recorded below.

It also generates the four ``*.after.py`` answer keys -- the output
``obelize fix --apply`` must produce for the four files that migrate -- from the
same byte literals, with each input's own terminator and encoding.  Before
ADR-013 this directory pinned its inputs and said nothing about its outputs, so
four files graded ``auto`` had no answer key and nothing checked that a migrated
CRLF file still comes out CRLF.  ``PAIRS`` and ``byte_shape`` assert that half
on its own, so it survives any later change to the layout rule.

``--check`` **compares the bytes on disk with the bytes this script generates**
and returns 1 on any difference, and it asserts the expectations
``ground_truth.yaml`` records.  Until ADR-010 it did neither: it printed a
report and returned 0 unconditionally, so an editor, a git filter or an
autoformatter could normalise the very bytes under test with CI staying green.
``tests/unit/test_fixture_encoding.py`` runs the same comparison in the ordinary
test matrix, which is what actually guards these files.

This script is the generator, NOT a fixture: it is not part of the scan corpus
and a harness must not feed it to the scanner.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

LF = b"\n"
CRLF = b"\r\n"
CR = b"\r"
BOM = b"\xef\xbb\xbf"


def _join(lines: list[str], terminator: bytes, encoding: str = "utf-8") -> bytes:
    """Encode `lines` and terminate every one of them, including the last."""
    return b"".join(line.encode(encoding) + terminator for line in lines)


# --- crlf.py -------------------------------------------------------------
# Every line terminated by CRLF.  Must round-trip and must be migrated.
CRLF_LINES = [
    '"""Nightly digest job."""',
    "import os",
    "",
    "import google.generativeai as genai",
    "",
    'genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    "",
    "def digest(text):",
    '    model = genai.GenerativeModel("gemini-1.5-flash")',
    "    return model.generate_content(text).text",
]

# --- latin1_cookie.py ----------------------------------------------------
# PEP 263 cookie on line 1 plus non-ASCII text encoded in latin-1.  Read as
# str with errors="replace" the accented characters are destroyed; parsed from
# str, libcst reports encoding='utf-8' and .bytes no longer matches (C-10).
LATIN1_LINES = [
    "# -*- coding: latin-1 -*-",
    '"""Génère un résumé court d\'un texte."""',
    "import os",
    "",
    "import google.generativeai as genai",
    "",
    'genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    'ENTETE = "Résumé du dossier « café » à Genève : "',
    "",
    "",
    "def resumer(texte):",
    '    modele = genai.GenerativeModel("gemini-1.5-flash")',
    "    return modele.generate_content(ENTETE + texte).text",
]

# --- utf8_bom.py ---------------------------------------------------------
# A UTF-8 BOM in front of ordinary UTF-8 source.  compile() accepts the bytes
# and rejects the same content as a str (invalid non-printable U+FEFF) (C-10).
BOM_LINES = [
    '"""Support reply drafter."""',
    "import os",
    "",
    "import google.generativeai as genai",
    "",
    'genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    "",
    "def draft(question):",
    '    model = genai.GenerativeModel("gemini-1.5-flash")',
    "    return model.generate_content(question).text",
]

# --- bare_cr.py ----------------------------------------------------------
# Classic-Mac line endings: the ONLY terminator is a bare CR.  libcst drops the
# final byte on round-trip and compile() accepts the damaged result, so the
# round-trip gate is the only thing between this file and silent data loss.
BARE_CR_LINES = [
    "import os",
    "import google.generativeai as genai",
    "",
    'genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    'model = genai.GenerativeModel("gemini-1.5-flash")',
    'print(model.generate_content("ping").text)',
]

# --- python2.py ----------------------------------------------------------
# A half-finished port of Python 2 source.  libcst parses it and compile() on
# the INPUT is what refuses it (C-08), at the `__future__` import the port put
# after the other imports -- which every supported interpreter refuses at the
# same line and column.  It used to be refused at `except ValueError, e:`, and
# Python 3.14 compiles that (PEP 758: it catches `ValueError` or `e`), so the
# key held on three interpreters of four (T38).
PYTHON2_LINES = [
    "# -*- coding: utf-8 -*-",
    "# Ported from an internal Python 2 tool. Never finished, still in the tree.",
    "import os",
    "import sys",
    "",
    "import google.generativeai as genai",
    "from __future__ import print_function",
    'genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    "",
    "def main(path):",
    "    try:",
    "        text = open(path).read()",
    "    except ValueError as e:",
    '        print >>sys.stderr, "cannot read %s: %s" % (path, e)',
    "        return 1",
    '    model = genai.GenerativeModel("gemini-1.5-flash")',
    "    print >>sys.stderr, model.generate_content(text).text",
    "    return 0",
]

# --- no_trailing_newline.py ---------------------------------------------
NO_NEWLINE_LINES = [
    '"""One-shot prompt runner."""',
    "import os",
    "",
    "import google.generativeai as genai",
    "",
    'genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    'MODEL = genai.GenerativeModel("gemini-1.5-flash")',
    'print(MODEL.generate_content("ping").text)',
]


# --- parser_syntax_error.py ----------------------------------------------
# The branch python2.py cannot reach: libcst itself refuses the file, so no tree
# is built and there is nothing to round-trip.  A hand migration that was never
# finished -- `genai.Client(` written against the legacy alias, one bracket left
# open, no blank line before the `def` that followed.  Both gates refuse it and
# they name different lines: libcst stops at 8, `compile()` blames 6 (C-08).
PARSER_SYNTAX_ERROR_LINES = [
    '"""Nightly report mailer. A hand migration that was never finished."""',
    "import os",
    "",
    "import google.generativeai as genai",
    "",
    'client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "")',
    "def report(text):",
    '    model = genai.GenerativeModel("gemini-1.5-flash")',
    "    return model.generate_content(text).text",
]

# --- the four answer keys ------------------------------------------------
# `obelize fix --apply` output for the four files that migrate.  The Python in
# them follows `basic/ground_truth.yaml` notes 2 and 4 (the constructor
# statement is deleted with its leading blank line and the model name is folded
# into each call; a call that was one line in the source stays one line).  What
# these keys exist for is the OTHER half: the terminator, the coding cookie, the
# BOM and the final newline must come out exactly as they went in.  `PAIRS`
# below asserts that half separately, so it survives a change to the layout
# rule.

CRLF_AFTER_LINES = [
    '"""Nightly digest job."""',
    "import os",
    "",
    "from google import genai",
    "",
    'client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    "",
    "def digest(text):",
    '    return client.models.generate_content(model="gemini-1.5-flash", contents=text).text',
]

LATIN1_AFTER_LINES = [
    "# -*- coding: latin-1 -*-",
    '"""Génère un résumé court d\'un texte."""',
    "import os",
    "",
    "from google import genai",
    "",
    'client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    'ENTETE = "Résumé du dossier « café » à Genève : "',
    "",
    "",
    "def resumer(texte):",
    "    return client.models.generate_content("
    'model="gemini-1.5-flash", contents=ENTETE + texte'
    ").text",
]

BOM_AFTER_LINES = [
    '"""Support reply drafter."""',
    "import os",
    "",
    "from google import genai",
    "",
    'client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    "",
    "",
    "def draft(question):",
    '    return client.models.generate_content(model="gemini-1.5-flash", contents=question).text',
]

NO_NEWLINE_AFTER_LINES = [
    '"""One-shot prompt runner."""',
    "import os",
    "",
    "from google import genai",
    "",
    'client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))',
    'print(client.models.generate_content(model="gemini-1.5-flash", contents="ping").text)',
]


def build() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    files["crlf.py"] = _join(CRLF_LINES, CRLF)
    files["latin1_cookie.py"] = _join(LATIN1_LINES, LF, encoding="latin-1")
    files["utf8_bom.py"] = BOM + _join(BOM_LINES, LF)
    files["bare_cr.py"] = _join(BARE_CR_LINES, CR)
    files["python2.py"] = _join(PYTHON2_LINES, LF)
    files["parser_syntax_error.py"] = _join(PARSER_SYNTAX_ERROR_LINES, LF)
    # Same as _join but without terminating the last line.
    files["no_trailing_newline.py"] = LF.join(line.encode("utf-8") for line in NO_NEWLINE_LINES)
    # The answer keys, each built with its input's terminator and encoding.
    files["crlf.after.py"] = _join(CRLF_AFTER_LINES, CRLF)
    files["latin1_cookie.after.py"] = _join(LATIN1_AFTER_LINES, LF, encoding="latin-1")
    files["utf8_bom.after.py"] = BOM + _join(BOM_AFTER_LINES, LF)
    files["no_trailing_newline.after.py"] = LF.join(
        line.encode("utf-8") for line in NO_NEWLINE_AFTER_LINES
    )
    return files


def write(files: dict[str, bytes]) -> None:
    for name, data in files.items():
        Path(HERE / name).write_bytes(data)
        print(f"wrote {name}: {len(data)} bytes")


# What ground_truth.yaml records, asserted rather than merely printed.
# name -> (libcst round-trips, compile() accepts, bytes lost on round-trip)
# Every generated file EXCEPT the one libcst refuses is in here; `verify` asserts
# that the two tables together cover exactly what `build` writes, so a new
# fixture cannot be added without being graded.
EXPECTED: dict[str, tuple[bool, bool, int]] = {
    "crlf.py": (True, True, 0),
    "latin1_cookie.py": (True, True, 0),
    "utf8_bom.py": (True, True, 0),
    "bare_cr.py": (False, True, 1),
    "python2.py": (True, False, 0),
    "no_trailing_newline.py": (True, True, 0),
    "crlf.after.py": (True, True, 0),
    "latin1_cookie.after.py": (True, True, 0),
    "utf8_bom.after.py": (True, True, 0),
    "no_trailing_newline.after.py": (True, True, 0),
}
# python2.py is the only file compile() refuses while libcst accepts it, at this
# line.
PYTHON2_SYNTAX_ERROR_LINENO = 7

# The one file libcst itself refuses.  It has no EXPECTED row because neither
# column applies: `cst.parse_module` raises, so there is no `.bytes` to compare.
LIBCST_REFUSES = "parser_syntax_error.py"

# `cst.ParserSyntaxError.raw_line` (1-based) and `.raw_column` (0-based), which
# is the pair ADR-008 names.
PARSER_SYNTAX_ERROR_AT = (8, 4)

# `.editor_line` and `.editor_column` on the same exception: the display form,
# and a different number.  Recorded so that reading the wrong attribute is
# visibly wrong rather than plausibly right.
PARSER_SYNTAX_ERROR_EDITOR_AT = (8, 5)

# `compile()` refuses the same bytes and blames a different line -- two earlier,
# where the bracket was actually left open.  Which number reaches the report is
# therefore decided by which gate runs first, and that is a decision
# (ADR-017), not an implementation detail.
PARSER_SYNTAX_ERROR_COMPILE_LINENO = 6

# input -> `obelize fix --apply` answer key.  The three files missing from this
# mapping are the three that must never be edited: `bare_cr.py`
# (roundtrip_mismatch), `python2.py` and `parser_syntax_error.py` (both
# input_does_not_parse, from opposite gates).  Absence from this table is
# therefore a statement, not an omission -- see `after_file_is` in
# ground_truth.yaml.
PAIRS: dict[str, str] = {
    "crlf.py": "crlf.after.py",
    "latin1_cookie.py": "latin1_cookie.after.py",
    "utf8_bom.py": "utf8_bom.after.py",
    "no_trailing_newline.py": "no_trailing_newline.after.py",
}


def byte_shape(data: bytes) -> dict[str, object]:
    """The byte-level facts a migration has to carry through unchanged.

    Deliberately computed from the bytes rather than from libcst: this is the
    property the fixtures exist for, and reading it out of the parser would make
    the answer depend on the thing under test.
    """
    body = data[len(BOM) :] if data.startswith(BOM) else data
    return {
        "bom": data.startswith(BOM),
        "terminator": (
            "crlf" if CRLF in body else "cr" if CR in body else "lf" if LF in body else "none"
        ),
        "final_newline": body.endswith((LF, CR)),
        "cookie": next(
            (
                line
                for line in body.split(LF)[:2]
                if b"coding" in line and line.lstrip().startswith(b"#")
            ),
            b"",
        ),
    }


def verify(files: dict[str, bytes]) -> bool:
    """Print the byte-level report. Return True when everything matches."""
    from importlib.metadata import version as _dist_version

    import libcst as cst

    ok = True

    def fail(name: str, message: str) -> None:
        nonlocal ok
        ok = False
        print(f"    MISMATCH      : {name}: {message}")

    def refused(name: str, data: bytes) -> None:
        """The file libcst will not parse: no round-trip, two sets of coordinates."""
        try:
            cst.parse_module(data)
        except cst.ParserSyntaxError as exc:
            at = (exc.raw_line, exc.raw_column)
            editor = (exc.editor_line, exc.editor_column)
            print(f"    libcst parse  : ParserSyntaxError raw={at} editor={editor}")
            print(f"    libcst message: {exc.message.splitlines()[0]}")
            if at != PARSER_SYNTAX_ERROR_AT:
                fail(name, f"raw coordinates are {at}, ground truth says {PARSER_SYNTAX_ERROR_AT}")
            if editor != PARSER_SYNTAX_ERROR_EDITOR_AT:
                fail(
                    name,
                    f"editor coordinates are {editor}, ground truth says "
                    f"{PARSER_SYNTAX_ERROR_EDITOR_AT}",
                )
        except Exception as exc:
            fail(
                name,
                f"libcst raised {type(exc).__name__}, not cst.ParserSyntaxError; "
                f"this file exists for that one branch",
            )
        else:
            fail(name, "libcst parsed it; this file exists because libcst refuses it")
        try:
            compile(data, name, "exec")
        except SyntaxError as exc:
            print(
                f"    compile(bytes): RAISED SyntaxError: {exc.msg} "
                f"(lineno={exc.lineno}, offset={exc.offset})"
            )
            if exc.lineno != PARSER_SYNTAX_ERROR_COMPILE_LINENO:
                fail(
                    name,
                    f"compile() blames lineno={exc.lineno}, ground truth says "
                    f"{PARSER_SYNTAX_ERROR_COMPILE_LINENO}",
                )
        else:
            fail(name, "compile() accepted it; both gates must refuse this file")

    print()
    print(f"libcst {_dist_version('libcst')}, python {sys.version.split()[0]}")
    graded = set(EXPECTED) | {LIBCST_REFUSES}
    if graded != set(files):
        fail(
            "EXPECTED",
            f"the expectation tables and the generated files disagree: "
            f"{sorted(set(files) ^ graded)}. Every fixture here is graded.",
        )
    for name, generated in files.items():
        path = Path(HERE / name)
        if not path.exists():
            print()
            print(f"--- {name}")
            fail(name, "missing from disk; run this script without --check")
            continue
        data = path.read_bytes()
        print()
        print(f"--- {name} ({len(data)} bytes)")
        if data != generated:
            fail(
                name,
                f"on disk differs from the generated bytes "
                f"({len(data)} vs {len(generated)} bytes). "
                f"These files exist for their exact bytes; something normalised them.",
            )
        if name == LIBCST_REFUSES:
            print(f"    head          : {data[:80]!r}")
            refused(name, data)
            continue
        want_roundtrip, want_compiles, want_lost = EXPECTED[name]
        print(f"    head          : {data[:80]!r}")
        print(f"    tail          : {data[-40:]!r}")
        try:
            module = cst.parse_module(data)
        except Exception as exc:
            print(f"    libcst parse  : RAISED {type(exc).__name__}: {str(exc).splitlines()[0]}")
            print("    roundtrip     : n/a")
            print("    module.encoding: n/a")
            fail(name, "libcst refused the file; every fixture here must parse")
        else:
            roundtrips = module.bytes == data
            lost = len(data) - len(module.bytes)
            print("    libcst parse  : ok")
            print(f"    module.encoding: {module.encoding!r}")
            print(f"    roundtrip     : {roundtrips}")
            if not roundtrips:
                print(f"    roundtrip out : {module.bytes[-40:]!r}")
                print(f"    bytes lost    : {lost}")
            if roundtrips is not want_roundtrip:
                fail(name, f"roundtrip is {roundtrips}, ground truth says {want_roundtrip}")
            elif not roundtrips and lost != want_lost:
                fail(name, f"lost {lost} bytes on roundtrip, ground truth says {want_lost}")
        try:
            compile(data, name, "exec")
        except SyntaxError as exc:
            print(
                f"    compile(bytes): RAISED SyntaxError: {exc.msg} "
                f"(lineno={exc.lineno}, offset={exc.offset})"
            )
            if want_compiles:
                fail(name, f"compile() refused it: {exc.msg}")
            elif exc.lineno != PYTHON2_SYNTAX_ERROR_LINENO:
                fail(
                    name,
                    f"SyntaxError at lineno={exc.lineno}, ground truth says "
                    f"{PYTHON2_SYNTAX_ERROR_LINENO}",
                )
        else:
            print("    compile(bytes): ok")
            if not want_compiles:
                fail(name, "compile() accepted it; ground truth says it must not")

    print()
    print("--- answer keys keep the input's byte shape")
    for source, answer in PAIRS.items():
        before = byte_shape(files[source])
        after = byte_shape(files[answer])
        print(f"    {source} -> {answer}")
        print(f"      in : {before}")
        print(f"      out: {after}")
        if before != after:
            differing = sorted(k for k in before if before[k] != after[k])
            fail(
                answer,
                f"the answer key changes the byte shape of {source} ({differing}). "
                f"A migration is bytes in, bytes out: the terminator, the coding "
                f"cookie, the BOM and the final newline all survive it.",
            )

    print()
    print("CHECK: ok" if ok else "CHECK: FAILED -- see the MISMATCH lines above")
    return ok


def main(argv: list[str]) -> int:
    files = build()
    if "--check" not in argv:
        write(files)
    return 0 if verify(files) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
