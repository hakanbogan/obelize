# ADR-009: Project named Obelize

## Status

Accepted.

## Decision

The project is called **Obelize**, and every surface carries that one name, so there is one
console script and `uvx obelize` needs no `--from`:

| Thing | Value |
|---|---|
| Brand, in prose | Obelize |
| CLI command | `obelize` |
| PyPI distribution | `obelize` |
| Import package | `obelize` |
| Repository | `github.com/hakanbogan/obelize` |
| Repository config file | `.obelize.yml` |
| Run folder | `.obelize/runs/<id>/` |
| User config | `~/.config/obelize/config.yml` |
| Environment variables | `OBELIZE_MODEL_API_KEY`, `OBELIZE_RUN` |

To *obelize* is to mark a doubtful passage with an obelus (†) instead of silently correcting
it, which is the product's thesis: rewrite what can be proven and mark the rest
`needs_review`. The word is arbitrary for software, the strongest trademark position short of
an invention, and a verb, so `obelize scan` reads as an action.

**Clearance.** A name is adopted only after a register-level search finds no live class 9 or
42 registration for the word and no business trading under it. For `obelize` the US, EU, UK
and Turkish registers show none; the only identical word, CNIPA 36697897, covers class 9
hardware. The project renames on a live registered trademark covering this field, or a formal
objection.

## Consequences

- Commits before the rename carry the former name APIX, dropped over live class 9 and 42 marks.
- Open: USPTO Serial 50061157 (OBELUS, classes 9 and 42) is pending, and TURKPATENT was
  searched only through TMview.
- This reads the registers and is not legal advice: an attorney's opinion before the public
  announcement remains worth buying.
