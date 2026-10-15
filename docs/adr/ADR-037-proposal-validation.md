# ADR-037: Proposal validation

## Status

Accepted; amended by ADR-039 (D9) and ADR-052.

## Decision

### D1. Seventeen words in one fixed order, first refusal wins

`GuardRefusal` is a closed set in `models.py`. The checks run in this order and
only the **first** refusal is recorded:

| # | Word | Refused because |
|---|---|---|
| 1 | `path_outside_root` | the path is absolute, holds a `..` component, or is not a relative POSIX path |
| 2 | `path_not_python` | it does not end in `.py` |
| 3 | `path_not_the_consulted_file` | it is not the file the question was about (D2) |
| 4 | `file_changed_since_read` | the bytes on disk are not the bytes the plan read (D3) |
| 5 | `outside_the_context` | the replaced range is not inside the range that was sent |
| 6 | `site_not_replaced` | the replaced range does not contain the line asked about |
| 7 | `symbol_mismatch` | the proposal names a symbol other than the question's |
| 8 | `replaced_text_differs` | the lines it says it replaces are not the lines it names, as sent (D12) |
| 9 | `replacement_too_large` | over the line or byte limit (D5) |
| 10 | `replacement_not_displayable` | it holds a character a terminal acts on |
| 11 | `replacement_carries_redaction` | it holds `[REDACTED`, which the lines it replaces do not (D10) |
| 12 | `replacement_not_encodable` | the file's own encoding cannot hold it (D6) |
| 13 | `output_does_not_compile` | `compile()` refuses it (D6) |
| 14 | `output_does_not_parse` | libcst refuses a module `compile()` accepted, or it nests deeper than obelize reads (D6, D11) |
| 15 | `replacement_runs_past_its_range` | it changes how the lines after it are read |
| 16 | `import_outside_the_target` | the result imports a module the pack does not target (D7) |
| 17 | `name_outside_the_question` | it names something the question did not license (D7) |

Three groups: may this file be touched (1-4), is this an answer to the question
(5-8), and is the result Python that brings nothing in (9-17), last because
those cost a parse. `../../.bashrc` is reported as an escape, not an unplanned
file, because that is what a reviewer must learn first.

### D2. The allowlist is one path: the file the question was about

The target must be exactly `Consultation.context.path`, narrower than ADR-003's
"the impact plan". An invented filename and a different planned file share
`path_not_the_consulted_file`; the detail line says which. Because one question
is one finding in one file.

### D3. The hash is asked of the disk, and every way the disk can disagree is one word

`fsutil.sha256` of the bytes the plan read is compared with that of
`fsutil.read` now (`O_NOFOLLOW`). Changed, gone, a symlink or unreadable are all
`file_changed_since_read`, with the reason in the detail. Because a proposal's
line numbers mean nothing against other bytes; `fsutil.apply` repeats the check
for the write.

### D4. Four questions about where the edit lands, not one

`outside_the_context` is `Context.holds`, called rather than re-derived.
`site_not_replaced`: the replaced range must contain `Consultation.line`.
`symbol_mismatch`: the proposal's `symbol` must equal the consultation's, which
also refuses a consultation with no symbol. `replaced_text_differs` is D12's.
Because whether the symbol exists is the scan's fact; the guard checks the answer
is about it.

### D5. The diff size limit is on the replacement, and it is absolute

`REPLACEMENT_LINE_LIMIT = CONTEXT_LINE_LIMIT` (80) and
`REPLACEMENT_BYTE_LIMIT = 1024 * REPLACEMENT_LINE_LIMIT` (81 920 UTF-8 bytes),
not relative to the replaced range. Because the removed side is already bounded
by the context, and the byte limit bounds one huge line.

### D6. Three output gates, because encoding is not parsing

The result is encoded in the file's own encoding as libcst reports it, then
compiled, then parsed. Because a latin-1 file cannot take a character latin-1
lacks, and libcst parses what `compile()` refuses (`await` outside `async`).
`compile()` goes first because it answers a deeply nested expression with an
exception, where libcst's parser overruns the C stack and kills the process; a
syntax error is therefore `output_does_not_compile`, and `output_does_not_parse`
is what `compile()` accepted and libcst cannot read. Before them a replacement
may carry no character a terminal acts on except tab and line breaks; after
them its last token must end a statement.

### D7. The import check reads `__import__` and `importlib.import_module` too

Every module the result imports and the input did not must be a `to_module` of
the pack's `rename_import` changes or under one; a relative or non-literal
import is under nothing. `import`, `from ... import`, `__import__`,
`importlib.import_module` and a bare `import_module` all count. Then every name
the replacement reads must be in the replaced lines, bound by a target import
or the replacement, or one of a few pure builtins, and never a dunder. Because
`--accept-model` with verification commands runs a proposal before anyone reads it.

### D8. The guard returns the bytes it checked

`check` writes nothing and returns a `Checked`: the proposal, the refusal or
`None`, a detail line, and on acceptance the resulting file bytes, the only
splice in the package. `providers.base.split_lines` divides lines for both, and
`Consultation.to_modules` carries the allowed imports to prompt and guard.
Because bytes rebuilt by a caller need not be the bytes that were checked.

### D9. Nothing calls the guard yet

Superseded by ADR-039: `providers/proposals.py` checks every proposal before
`obelize fix` may write it.

### D10. A placeholder the model echoes is refused

The context a model is shown is redacted, so a secret stands in it as `[REDACTED...]`. A
replacement that repeats the marker would write the word into the file where the value stood, and
what ran with the value would run with the word. `replacement_carries_redaction` compares the
`[REDACTED` prefix in the replacement with the lines it replaces: a marker those lines already hold
is the file's own text and passes. Because a proposal that compiles and imports nothing can still
destroy a credential, and the later checks cannot see it.

### D11. A reply nested deeper than the stack is refused, not raised

A replacement of about nine hundred operands passes `compile()` and libcst's
parser, and the visitors that walk its tree recurse once per level and raise
`RecursionError`. `check` catches that and `MemoryError` and records
`output_does_not_parse`, with the detail "nested more deeply than obelize
reads". Because a refusal is a row for a reviewer, and an exception ends the run
with a traceback and no run folder. An operand chain of about 13,000 `and` or
`or` terms on Python 3.14 and later still reaches libcst's parser; that is the
scanner's open item too.

### D12. A proposal quotes the lines it replaces, and the quote must be what was sent

`EditProposal.replaces` is required: the text of the lines the range names, as
the model was shown them. After `symbol_mismatch` the guard compares it with
`Consultation.context.text` for `start_line` to `end_line`, line by line without
trailing whitespace or line break (a final line break in the quote is allowed;
indentation is not ignored), and refuses a difference as `replaced_text_differs`.
The context is the redacted text the model read, so a secret is quoted as its
marker and the quote of the raw value is refused. A redaction can join lines (a
private key over three lines becomes one marker), which leaves the context with
fewer lines than its range and every later line number untrustworthy: the guard
then refuses every proposal for that context, with that sentence in the detail.
Because a range that slipped by one line still covers the asked line, is inside
the context and names the right symbol, and the result can compile: only the
text it claims to replace can tell it from the range that was meant. A model
that cannot quote exactly is refused more often, which fails closed.

## Consequences

- A proposal failing several checks reports one, so counts by word count first refusals.
- A latin-1 repository refuses some correct-looking proposals; the row stays `needs_review` and the file keeps its bytes.
- `REPLACEMENT_LINE_LIMIT` follows `CONTEXT_LINE_LIMIT`; `tests/unit/test_providers_guard.py` pins the boundary.
- Open: a pack targeting several modules, or a target import absent from the files rewritten, makes D7's allowed set a real constraint. A model is asked about one pack, so the set never holds two packs' targets (ADR-052 D6).
