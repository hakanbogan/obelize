# ADR-017: Input gates

## Status

Accepted.

## Decision

**D1. The order is `compile()`, a depth check, then libcst, then the byte round-trip.** A file
failing only the round-trip is valid Python, so it is analysed and every finding
carries `roundtrip_mismatch`; one also failing `compile()` (bare-CR terminators
and a late `__future__` import, in `tests/unit/test_parse.py`) is one
`input_does_not_parse` finding, not analysis of source that is not Python.
`compile()` goes first because a pathologically deep expression (3,000 nested
parentheses, a chain of 100,000 operands, 10,000 `not`s) overruns libcst's
parser and kills the process with SIGSEGV, where `compile()` raises. A chain of
about thirteen thousand operands, or of attributes, calls or subscripts, is
accepted by `compile()` on some versions (3.14) and kills libcst the same way,
so a second check, `parse.MAX_DEPTH`, refuses a file whose syntax tree is nested
more than 300 levels deep before libcst sees it. The walk is iterative, and an
`and` or `or` counts one level an operand, as libcst nests them where `ast`
holds them flat. 300 is under where libcst gives out, near 490 levels to render
and 320 for the scan's visitors on the default stack: a chain the check passes
does not overrun the stack later, which would depend on the stack (`--jobs`, a
test runner) and not on the file. The refusal is one
`input_does_not_parse` finding and its detail names the limit. The
analysis and the codemod catch `RecursionError` and `MemoryError` per file for
the trees that do parse (libcst nests a call argument two levels where `ast` has
one, so a file within the limit can still overrun): the file is one
`input_does_not_parse` finding, or, when only the rewrite overruns, kept as it
was with `output_does_not_parse`.

**D2. The handler is `except (cst.ParserSyntaxError, SyntaxError, ValueError)`.**
That is libcst's handler: `cst.ParserSyntaxError` is not a `SyntaxError`, and
bytes that contradict their coding cookie raise `UnicodeDecodeError`, a
`ValueError`. The `compile()` handler catches `SyntaxError`, which every
supported interpreter raises even for a null byte, and `RecursionError` and
`MemoryError`, which a deep expression raises instead
(`verify.cheap.COMPILE_REFUSALS`, also the always-on check of changed files):

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

**D5. The reader writes four limitation codes and invents none.**
`file_too_large`, `input_does_not_parse` and `internal_error` (D9) are
[SCAN_VOCABULARY.md](../SCAN_VOCABULARY.md) §4 bails and `unreadable` is §11's.
The set is closed and asserted against both, and `models.LimitationCode` is the
union of the walker's seven and these four, which share `unreadable`: ten
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
nothing else Python 3 lacks is accepted. Both `compile()` calls (the gate and
`verify.cheap`) pass `dont_inherit=True`: obelize's own `from __future__ import
annotations` would otherwise apply to the file and refuse, on 3.12 and 3.13, a
walrus in an annotation that is valid there. A file's own `__future__` imports
still count.

**D9. An exception from one file does not end the run.** `runner.examine` and
`codemod.run` catch `Exception` per file, after the handlers for a stack overrun
(`RecursionError`, `MemoryError`), which keep their own codes. In a scan the file
is one `parse_error` row with `internal_error` as its bail, `unsupported`, at line
1 column 0, so it holds the repository as an unparsable file does, and
`limitations[]` carries `internal_error` with the exception's class and never its
message, which can quote the file or a path. In a `fix` run the file is kept as it
was and each row the scan graded `eligible` is withheld as `internal_error`
([ADR-031](ADR-031-codemod-driver.md) D13). Catching it is not hiding it: the row
is withheld where a reader looks, and the limitation names the class. A native
crash is a signal, not an exception, so `BrokenProcessPool` still propagates
([ADR-022](ADR-022-runner-result-order.md) D7).

## Consequences

- `files_parsed` is `status == "parsed"`, including a file that does not
  round-trip.
- `Read` rejects field combinations that would surface later as a silent zero.
- D2's byte shapes are unit tests in `tests/unit/test_parse.py`, not graded
  fixtures: the oracle grades migrations, and none of them is one.
- A parse error is one finding, and the `text_mention` sweep adds none.
- Open: refusing the whole run once, rather than each file, when a repository
  is newer than the interpreter.
