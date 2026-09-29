# ADR-037: Proposal validation

## Status

Accepted; amended by ADR-039 (D9).

## Decision

### D1. Twelve words for seven checks, in one fixed order, first refusal wins

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
| 8 | `replacement_too_large` | over the line or byte limit (D5) |
| 9 | `replacement_not_displayable` | it holds a character a terminal acts on |
| 10 | `replacement_not_encodable` | the file's own encoding cannot hold it (D6) |
| 11 | `output_does_not_parse` | libcst refuses the resulting module |
| 12 | `output_does_not_compile` | `compile()` refuses it (D6) |
| 13 | `replacement_runs_past_its_range` | it changes how the lines after it are read |
| 14 | `import_outside_the_target` | the result imports a module the pack does not target (D7) |
| 15 | `name_outside_the_question` | it names something the question did not license (D7) |

Three groups: may this file be touched (1-4), is this an answer to the question
(5-7), and is the result Python that brings nothing in (8-15), last because
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

### D4. Three questions about where the edit lands, not one

`outside_the_context` is `Context.holds`, called rather than re-derived.
`site_not_replaced`: the replaced range must contain `Consultation.line`.
`symbol_mismatch`: the proposal's `symbol` must equal the consultation's, which
also refuses a consultation with no symbol. Because whether the symbol exists
is the scan's fact; the guard checks the answer is about it.

### D5. The diff size limit is on the replacement, and it is absolute

`REPLACEMENT_LINE_LIMIT = CONTEXT_LINE_LIMIT` (80) and
`REPLACEMENT_BYTE_LIMIT = 1024 * REPLACEMENT_LINE_LIMIT` (81 920 UTF-8 bytes),
not relative to the replaced range. Because the removed side is already bounded
by the context, and the byte limit bounds one huge line.

### D6. Three output gates, because encoding is not parsing

The result is encoded in the file's own encoding as libcst reports it, then
parsed, then compiled. Because a latin-1 file cannot take a character latin-1
lacks, and libcst parses what `compile()` refuses (`await` outside `async`).
Before them a replacement may carry no character a terminal acts on except tab
and line breaks; after them its last token must end a statement.

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

## Consequences

- A proposal failing several checks reports one, so counts by word count first refusals.
- A latin-1 repository refuses some correct-looking proposals; the row stays `needs_review` and the file keeps its bytes.
- `REPLACEMENT_LINE_LIMIT` follows `CONTEXT_LINE_LIMIT`; `tests/unit/test_providers_guard.py` pins the boundary.
- Open: a pack targeting several modules, or a target import absent from the files rewritten, makes D7's allowed set a real constraint.
