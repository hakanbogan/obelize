"""Turn the SARIF `obelize scan` printed into GitHub annotations and a step summary.

An annotation names a file and a line, so a pull request shows the places a migration leaves where
they are. GitHub shows the first ten of each level; the SARIF upload to code scanning shows all.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

COMMANDS = {"error": "error", "warning": "warning", "note": "notice"}


def escape(text: str, *, value: bool = False) -> str:
    """The workflow-command escapes: a file name is repository text and must not end the command."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if value else text


def annotation(result: dict[str, Any]) -> str:
    place = result["locations"][0]["physicalLocation"]
    command = COMMANDS.get(result.get("level", "warning"), "warning")
    where = (
        f"file={escape(place['artifactLocation']['uri'], value=True)},"
        f"line={place['region']['startLine']},col={place['region']['startColumn']},"
        f"title={escape('obelize ' + result['ruleId'], value=True)}"
    )
    return f"::{command} {where}::{escape(result['message']['text'])}"


def summary(results: list[dict[str, Any]]) -> str:
    counts = Counter(result["ruleId"] for result in results)
    lines = ["## obelize", "", f"{len(results)} place(s) left."]
    if counts:
        lines += ["", "| Reason | Places |", "|---|---|"]
        lines += [f"| `{rule}` | {count} |" for rule, count in sorted(counts.items())]
    return "\n".join(lines) + "\n"


def main(path: str) -> int:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        results = document["runs"][0]["results"]
    except (OSError, ValueError, LookupError):
        print("::error::obelize printed no findings, so there is nothing to annotate; see the log")
        return 0
    for result in results:
        print(annotation(result))
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(summary(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
