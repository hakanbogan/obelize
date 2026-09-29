"""The only secret redactor (evidence, logs, model payloads, the printed diff), and the cap.

`docs/THREAT_MODEL.md` specifies both rules. Rule 1 replaces the values of secret-named variables,
longest first so a substring secret cannot split a longer one; rule 2 replaces known shapes. Both
over-redact on purpose (`GIT_AUTHOR_NAME` matches `AUTH`) rather than list exact names; other
formats pass, as `docs/PRIVACY.md` says. The cap bounds memory too: over it, a secret straddling
the elision is cut rather than removed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Replaces a shape match; a variable's value gets `[REDACTED:<NAME>]`, naming what to rotate.
REDACTED = "[REDACTED]"

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.IGNORECASE)

# Shorter values are too likely to be ordinary words; `THREAT_MODEL.md` names the number.
MIN_SECRET_LENGTH = 8

# The secret shapes, in `THREAT_MODEL.md`'s order. The generic assignment keeps the setting's name,
# which the reader needs in order to rotate it.
_GENERIC_ASSIGNMENT = re.compile(
    r"""(?P<name>api[_-]?key|token|secret)(?P<gap>\s*[:=]\s*)(?P<quote>['"])[^'"]{8,}(?P=quote)""",
    re.IGNORECASE,
)
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)

# One mebibyte kept as its two ends: the first thing that went wrong, and the summary.
HEAD_BYTES = 256 * 1024
TAIL_BYTES = 768 * 1024
OUTPUT_LIMIT = HEAD_BYTES + TAIL_BYTES


def marker(elided: int) -> str:
    """What replaces the elided middle; `output_truncated` is the fixed word, so a grep finds it."""
    return f"\n... [output_truncated: {elided} bytes elided] ...\n"


def secrets(environ: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """The `(value, marker)` pairs rule 1 will remove, longest value first.

    Totally ordered, so when two variables hold one value (`GH_TOKEN`, `GITHUB_TOKEN`) the marker
    names the same one on every run.
    """
    found = [
        (value, name)
        for name, value in environ.items()
        if len(value) >= MIN_SECRET_LENGTH and SECRET_NAME.search(name)
    ]
    found.sort(key=lambda pair: (-len(pair[0]), pair[0], pair[1]))
    return tuple((value, f"[REDACTED:{name}]") for value, name in found)


def redact(text: str, environ: Mapping[str, str]) -> str:
    """Rule 1 then rule 2, over one string."""
    for value, replacement in secrets(environ):
        text = text.replace(value, replacement)
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _GENERIC_ASSIGNMENT.sub(
        lambda match: f"{match['name']}{match['gap']}{match['quote']}{REDACTED}{match['quote']}",
        text,
    )


def cap(head: bytes, tail: bytes, elided: int) -> tuple[str, bool]:
    """Join what was retained, decode it, and say whether anything was dropped.

    `surrogateescape`: non-UTF-8 output, or a character the cap cut, is kept rather than raising
    mid-record.
    """
    if elided:
        joined = head.decode("utf-8", "surrogateescape")
        joined += marker(elided)
        joined += tail.decode("utf-8", "surrogateescape")
        return joined, True
    return (head + tail).decode("utf-8", "surrogateescape"), False


__all__ = [
    "HEAD_BYTES",
    "MIN_SECRET_LENGTH",
    "OUTPUT_LIMIT",
    "REDACTED",
    "SECRET_NAME",
    "TAIL_BYTES",
    "cap",
    "marker",
    "redact",
    "secrets",
]
