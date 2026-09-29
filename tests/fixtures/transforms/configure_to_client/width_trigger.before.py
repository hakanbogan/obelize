"""A call that fits on one line before the rewrite and does not after it.

`client = ` and `Client` are nine characters longer than the `configure` they
replace, so a call at 97 columns comes out at 103. Without the pack's
`layout.line_length` the codemod would emit that line and the user's own
formatter would rewrap it, which is the diff ADR-005 promises not to produce.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ.get("MY_ORGANISATION_GEMINI_API_KEY_FOR_PRODUCTION_RUNS", ""))
