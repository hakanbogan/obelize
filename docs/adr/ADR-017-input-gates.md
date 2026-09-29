# ADR-017: Input gates

## Status

Accepted.

## Decision

**D1. The order is libcst, then `compile()`, then the byte round-trip.** A file
failing only the round-trip is valid Python, so it is analysed and every finding
carries `roundtrip_mismatch`; one also failing `compile()` (bare-CR terminators
and a late `__future__` import, in `tests/unit/test_parse.py`) is one
`input_does_not_parse` finding, not analysis of source that is not Python.

**D2. The handler is `except (cst.ParserSyntaxError, SyntaxError, ValueError)`.**
That is libcst's handler: `cst.ParserSyntaxError` is not a `SyntaxError`, and
bytes that contradict their coding cookie raise `UnicodeDecodeError`, a
`ValueError`. The `compile()` handler catches `SyntaxError` alone, which every
supported interpreter raises even for a null byte:

| Bytes | `cst.parse_module` | `compile(...)` |
|---|---|---|
| a null byte | `ParserSyntaxError` | `SyntaxError` |
| an unknown coding cookie | plain `SyntaxError`, `lineno=None` | `SyntaxError`, `lineno=0` |
| a non-UTF-8 byte and no cookie | plain `SyntaxError`, `lineno=None` | **accepts it** |
| bytes that contradict their cookie | **`UnicodeDecodeError`** | `SyntaxError`, `lineno=2` |
| UTF-16 source | plain `SyntaxError`, `lineno=None` | `SyntaxError` |

**D3. Coordinates come from the attribute the exception actually has, with a
floor.** `.raw_line`/`.raw_column` for `cst.ParserSyntaxError` (not `.editor_*`),
`.lineno` and the 1-based `.offset` for `SyntaxError`, otherwise `1, 0`; line 1,
column 0 is the floor because `Finding.line` is `>= 1` and D2's table yields
`lineno=None` and `lineno=0`.

**D4. The parser's sentence goes in the limitation; `Finding.evidence` is
`None`; no excerpt of the file goes anywhere.** A `parse_error` has null
`symbol` and `evidence`, which `Finding` enforces; `limitations[].detail` holds
the refusal's sentence, the gate, and the first line of the parser's `.message`
or `.msg`, capped. `str(cst.ParserSyntaxError)` and `SyntaxError.text` quote the
source and are never used; `compile()`'s message may name an unknown coding
cookie, a declaration kept because it explains the refusal.

**D5. The reader writes three limitation codes and invents none.**
`file_too_large` and `input_does_not_parse` are
[SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) §4 bails and `unreadable` is §11's.
The set is closed and asserted against both, and `models.LimitationCode` is the
union of the walker's seven and these three, which share `unreadable`: nine
values.

**D6. `max_file_bytes` is a limit on the `lstat`, and the prefilter runs before
the parser.** An oversized file is never read, and its row names both numbers.
The prefilter (`parse.candidate`, also asked of F-2's excluded files and of
manifests) runs on raw bytes; a file it eliminates was looked at and owes the
report nothing.

**D7. The read opens with `O_NOFOLLOW`.** Any check before an `open` can be
raced; a name that became a symbolic link after selection fails with `ELOOP`
and is reported `unreadable`. Both declared platforms have the flag, so it is
used unconditionally.

**D8. The `compile()` gate stays, and its version-dependence is documented
rather than worked around.** It refuses what libcst and `ast.parse` accept and
is not a program (a module-level `return`, a late `__future__` import), but it
is the running interpreter's answer: newer syntax is `input_does_not_parse`,
never edited, and the detail sentence says to try a newer interpreter. 3.14
compiles Python 2's `except E, e:` (PEP 758), so there a Python 2 file using
nothing else Python 3 lacks is accepted.

## Consequences

- `files_parsed` is `status == "parsed"`, including a file that does not
  round-trip.
- `Read` rejects field combinations that would surface later as a silent zero.
- D2's byte shapes are unit tests in `tests/unit/test_parse.py`, not graded
  fixtures: the oracle grades migrations, and none of them is one.
- A parse error is one finding, and the `text_mention` sweep adds none.
- Open: refusing the whole run once, rather than each file, when a repository
  is newer than the interpreter.
