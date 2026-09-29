"""One file, two changes, and an edit has to say which one refused it.

The whole reason this kind produces an edit at all: `ScanSpec` carries the
union of every `flag_only` change's names, so the scan can say that a surface
is refused and not by whom. The message and the suggestion a reader needs are
on one change, and `rule_id` is the only way from the row to them.
"""

import google.generativeai as genai
from google.generativeai.types import Tool

genai.configure(api_key="")

LOOKUP = Tool(function_declarations=[])


def schema():
    return genai.protos.Schema(type=genai.protos.Type.STRING)
