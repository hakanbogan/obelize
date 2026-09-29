# What the scan fixtures do NOT cover

These fixtures are the measurement oracle, hand-written before the scanner so
the implementation is judged against a decision rather than its own output.
Nine cases, 169 graded findings (77 `auto`, 80 `needs_review`, 3 `unsupported`,
9 `not_a_usage`), 25 bindings, 107 `must_not_report` rows and one
`must_not_autofix` row. `tests/unit/test_fixture_vocabulary.py` asserts this
census per case and every value against
[docs/SCAN_VOCABULARY.md](../../../docs/SCAN_VOCABULARY.md).

`tests/oracle/` runs the walker, the reader, `scan/analysis.py`,
`scan/manifests.py` and the two `impact/` passes over every case and asserts,
exactly and in both directions: the finding set on file, line, kind, confidence
reason and symbol; the verdict, the bail and `caused_by` on every graded row;
that no `must_not_report` row is reported; every declared binding's constructor
line, use lines, verdict and bail; and that the files blocking the manifest edit
are the ones the key leaves importing the legacy distribution. Nothing is
excluded, so a new code arrives with the fixture that grades it.

The gaps are numbered: thirty-six are written down and **eighteen are
closed**. None of the open ones is a shipped surface without a fixture; they are
measurements and decisions. A closed gap is struck through and keeps its number,
because task rows, ADRs, fixtures and `bench/errors.yaml` cite gaps by number.

## What is covered

| Case | What it pins |
|---|---|
| `basic/` | The complete easy migration: aliased import, module-level `configure`, a `module_const` model with `GenerationConfig`, `generate_content`, `count_tokens`, a manifest line. All `auto`; `app.after.py` is byte for byte what `fix --apply` must produce. |
| `chat_async_self/` | A `self_attr` binding whose client comes from a `configure` inside a method, a positional `safety_settings`, a literal chat history, the `send_message` rename, sync streaming, async, and async streaming. All `auto`. |
| `encoding/` | Bytes in, bytes out: CRLF, a latin-1 cookie, a UTF-8 BOM, bare CR (`roundtrip_mismatch`), no trailing newline, and both `input_does_not_parse` gates: Python 2 (libcst parses, `compile()` rejects) and a half-finished hand migration (libcst refuses). Generated from byte literals by `encoding/_build.py` and guarded by `tests/unit/test_fixture_encoding.py`. The four files that migrate carry a `.after.py`, which `tests/oracle/test_apply_against_the_oracle.py` compares with a real write; the three refused have none, which under `after_file_is: fix_apply_output` claims they come out byte-identical. |
| `escapes/` | Fourteen ways a file refuses to migrate: rebound alias, shadowed name, conditional import, star import, an escaping model object, a `class_attr` binding, dynamic access, mock targets, two `configure` calls, no `configure` at all, a name assigned twice, an import inside a function body, an attribute other methods reassign, and a model another module imports. |
| `manifests/` | The five dependency-manifest layouts in one half-migrated repository, so both halves of [ADR-010](../../../docs/adr/ADR-010-fixture-oracle-and-atomicity.md) F-2 fire: `requirements.txt`, the `requirements/` directory form, PEP 621 `[project] dependencies`, a Poetry group, a `Pipfile` `[dev-packages]` table, a `setup.cfg` extras table and a `setup.py` `install_requires`. `app.py` migrates and `legacy.py` cannot, so the new pin is `auto` and the legacy pin withheld everywhere. Each layout carries a decoy spelling the distribution name (a comment, a description or a URL). |
| `import_forms/` | Every import spelling but the aliased one: plain dotted, `from … import … as …`, `from google import generativeai`, the `types` submodule with two enum members read as attributes, both annotation forms resolving through an `if TYPE_CHECKING:` import, and a model and a function named outside ASCII. All `auto`, deliberately without answer keys. |
| `transitive/` | A repository that migrates whole beside a module importing google-api-core without naming the legacy SDK. The legacy pin stays, under `transitive_dependency_in_use`: the new SDK does not install what that module imports, and the manifest never declared it. |
| `negative/` | Zero findings expected: already on `google.genai`, Vertex (both origins), a local package called `genai`, prose mentions, a Markdown code block. |
| `examples/gemini-legacy-app/` | The end-to-end subject. A run writes nothing: the scan grades three rows `auto`, and the driver withholds the module holding the `configure` two others still run on. |

## Gaps

1. ~~Pack rules 7–10~~ — closed.
2. ~~`history_parts_shape_incompatible`~~ — closed.
3. ~~An unknown `generation_config` key~~ — closed.
4. ~~A bare `genai.GenerativeModel()`~~ — closed.
5. ~~`credentials_shape_differs` and the unsupported `configure` kwargs~~ — closed.
6. ~~The safety table beyond the canonical long forms~~ — closed.
7. ~~Import spellings other than `import google.generativeai as genai`~~ — closed.
8. ~~Naming collisions~~ — closed.
9. ~~String annotations are real findings~~ — closed.
10. ~~One named bail with no fixture~~ — closed.
11. ~~Half of the async surface~~ — closed.
12. ~~`try: response.text / except ValueError:`~~ — closed.
13. ~~File selection~~ — closed.
14. ~~Determinism~~ — closed.
15. ~~`cst.ParserSyntaxError`~~ — closed.
16. ~~Benchmark version pinning~~ — closed.

### Precision and recall costs of the resolution pass

17. **A legacy module path reached through a variable rather than a literal.** `import_module(name)`
    with `name="google.generativeai"` is `not_a_usage`, so a stale patch target reached that way
    carries no review item. *Closes: reporting any legacy-prefixed string literal as a shape, false
    positives measured first.*
18. ~~A method-name collision in a file that also builds a legacy model~~ — closed.

### What the manifest pass refuses, or cannot see

19. **Three manifest shapes v0 does not read, each for its own reason.** A lockfile (a line edit
    would break its hashes); an unreadable source file, which does not block the pin's removal; and
    a `setup.cfg` requirement with a trailing comment, which reads as no legacy pin. *Closes:
    reading lockfiles, or a measurement that the `setup.cfg` shape occurs.*
20. **An attribute read on a receiver that does not resolve.** The scan reports a method call on an
    unresolved receiver (ADR-019 D5) but not an attribute read, so the legacy `ChatSession`
    attributes (`history`, `last`, `rewind`) are missed whenever a chat is passed rather than built
    in place. *Closes: applying ADR-019 D5 to attribute reads, with the fixture that grades it.*
21. **The scan does not know that a free function's rewrite needs a client.** `needs_client` in
    `impact/planner.py` ignores free functions, so `genai.embed_content(...)` with no `configure` is
    graded `eligible` by the scan and refused at fix time. *Closes: one projection field and one
    `needs_client` clause, with the gate-1 measurement re-run because `spec_digest` moves.*

### What the rewrite rules refuse, or cannot reach

22. **Two of the pack's four removed attributes are reportable only as a class read.**
    `base_model_id` and `supported_generation_methods` read off a `get_model` or `list_models`
    result, also via `getattr`, produce no scan row; fix time refuses such a read but not a result
    passed on. *Closes: the gate-1 re-run with gap 21, and a fixture grading an instance read.*
23. **An inline dependency array is read and not written.** A pin line that also carries the array's
    key or a second declaration is refused `manifest_pin_shape_unsupported`; how often the shape
    occurs is unmeasured. *Closes: a measurement that it occurs, and the second edit shape.*
24. ~~A file the scan already refused produces no `Edit` at all~~ — closed.
25. **A constructor and a method chained on one line.** `GenerativeModel(...).start_chat(...)` is
    one scan row where the benchmark key records two, and
    [SCAN_VOCABULARY.md](../../../docs/SCAN_VOCABULARY.md) does not say which is right. *Closes: a
    fixture with the chained form, its row convention decided first.*
26. **The compile gate does not run when no verification command is configured.** `compile()` over
    changed files is reached only from `_checked` in `src/obelize/commands/fix.py`, so an
    uncompilable write with no command reports `not_run`, exit `6`, not `fail`. *Closes: the gate
    moved out of `_checked`, with a test writing an uncompilable file.*
27. **`tests_cover_change` is read from the key and never checked against the run.** A case can
    claim it, pass on both sides and have skipped the covering test, and `verified_success` reads
    it. *Closes: each such key names its covering test node ids, and the harness asserts each ran
    unskipped in both phases.*

### What running twenty repositories found

Each lever is how many round-one rows would migrate if that cause alone were fixed
([ADR-044](../../../docs/adr/ADR-044-error-analysis.md)).

28. **An import inside a function body, and the largest lever in the round.** Lever +26:
    `local_import` refuses any import that is not module-level (ADR-020 D8), though the rename is
    mechanical and the open question is where the client goes. *Closes: rename in place, hoist, or
    refuse with the lever in the reason, with a fixture grading the choice.*
29. **A configuration argument that is a name, and the prediction it reverses.** Lever +26:
    `generation_config_not_static` refuses a name assigned once and readable, which ADR-012 D6
    predicted would buy zero edits. *Closes: a decision about a name with exactly one binding in
    reach, with fixtures for one binding and for two.*
30. **A name assigned twice, both times a legacy model.** Lever +9: `multiple_assignments` is
    `len(scope[name]) > 1`, so reusing `model` for two legacy models is refused, and nothing grades
    it. *Closes: a decision about a second legacy constructor in one scope, with its fixture.*
31. **A file that imports the legacy module twice.** Lever +6: a `from google.generativeai import …`
    beside `import google.generativeai as genai` bails `alias_collision`, though `rename_import`
    reuses an existing binding elsewhere. *Closes: a decision, with a fixture holding both.*
32. **A legacy module name as a bare string in a list.** Such a string is `not_a_usage`, while the
    same string where a `flag_only` pattern looks is flagged, so a `sys.modules` assertion stays
    true for the wrong reason. *Closes: with gap 17, or not at all.*
33. **A manifest whose filename differs only in case.** `Requirements.txt` is never opened, so no
    legacy pin is reported; on macOS it is the file `pip install -r requirements.txt` installs, on
    Linux another. *Closes: a decision on filename matching, a fixture per filesystem.*
34. **A `sys.modules` stub is graded two ways and the vocabulary settles neither.** The benchmark
    key grades such stubs `dynamic`, the scanner `text_mention` (`not_a_usage`), so they are left
    behind in silence. *Closes: a section 1 row in SCAN_VOCABULARY.md, a fixture, the key regraded.*
35. **A conversation built where no statement in its scope shows it.** A list of turns built in
    another function, returned by a helper or filled through a second name is passed unchanged into
    a call that rejects a bare-string part. *Closes: following a name across functions, as gap 22
    needs.*

### A file half migrated by hand

36. **A legacy call through the new import.** Where `from google import genai` is the only binding
    of `genai`, a later `genai.configure(...)` or `genai.GenerativeModel(...)` produces no finding;
    `escapes/conditional_import.py` grades the case with a legacy binding as well. Without the
    token `generativeai` the file is never parsed, and with it `genai` resolves only to
    `google.genai`, which the pack does not describe. The new module has neither name, so such
    code already fails when it runs. *Closes: a prefilter that reads the new import and a
    decision on reporting a legacy name read off it, with the fixture that grades both.*
