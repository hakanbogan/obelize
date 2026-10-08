# ADR-054: Pack guidance in the report

## Status

Accepted.

## Decision

What a pack says about the rows it flags reaches the person who runs it. A `flag_only` change carries
a `message` and a `suggestion` (ADR-018), a pack carries `limitations` and `verification.suggestions`,
and the report prints each of them. A flagged row reads as its code and a `rule_id`, and the words
say what to do about it.

### D1. A flagged change speaks for the findings it claimed

`scan` and `fix` print, after the counts, one block per `flag_only` change that claimed at least one
finding of its own pack: `<pack id>:<change id>: N finding(s) flagged.`, then the message and
`Suggestion:` and the suggestion. `REPORT.md` has the same under `## Guidance`, after `## Withheld`.
A change that claimed nothing prints nothing, so a run that flagged nothing adds no line.

The claim is `FlagOnly.claims`, the test the rule applies, over the findings of the one pack. A shape
row (`dynamic_access`, `mock_patch_target`) names no pack and every pack declares the shapes, so the
merged findings of a run would credit a pack with another's row. Blocks follow the order the packs run
in and then the order a pack declares its changes. A pack the repository blocks plans no edit but
still reports its findings, so it still explains the ones it flagged.

### D2. A pack's limitations and suggestions are in the report

`REPORT.md` lists each pack's `limitations` after the run's own, under `What <pack id> says it does
not handle:`, whether or not the run withheld anything, and a fix's Verification section lists the
packs' `verification.suggestions` as suggested and not run (ADR-007). The terminal prints neither: the
lists are the same for every run of a pack and say nothing about this one.

### D3. Pack text is shown, never interpreted

A pack's text is one line of display text: no control, format or surrogate character, and no line or
paragraph separator (ADR-018 D6). `REPORT.md` escapes the characters that make Markdown or HTML of a
line (`\`, backtick, `*`, `<`, `>`, `&`, `[`, `]`, `!`, `|`), so a viewer shows the text as written and
fetches, runs and hides nothing. `_` and `#` are left, since they matter only inside a word or at a
line start, which the text never is.

### D4. The verify note is the last one, whole

`obelize verify` replaces its own note, which is the marker, a blank line, the heading `## Verified
again` and one paragraph to the end of the file. It takes the last such note and ignores any earlier
text of that shape, such as a file name with line breaks, so the report is not cut.

### D5. No format gains a field

The words are read from the packs the run loaded. `findings.json`, `plan.json`, `run.json` and
`--json` are as they were, and the wording of `REPORT.md` stays outside the contract.

## Consequences

- A row withheld for a reason no flagged change owns (`response_shape_changed`, `usage_unmapped`, the
  two atomicity codes) still reads as its code, which `docs/SCAN_VOCABULARY.md` defines and the wheel
  does not install. A flagged row that caused an atomicity row is the one explained.
- A pack that names one surface in two `flag_only` changes reports its rows under both, and the
  blocks count them twice. Validation does not compare the changes (KNOWN_ISSUES).
- Open: a sentence per code for the codes no pack writes.
