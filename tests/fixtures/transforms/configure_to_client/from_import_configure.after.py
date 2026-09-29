"""ADR-025 D10's prediction, discharged: the name is consumed, not rewritten.

The import below binds a symbol off the legacy module itself, and until a rule
consumed `configure` the honest answer was `from_import_unmigrated_symbol`.
The client rule replaces the only call the name exists for, so the entry goes
and the statement becomes the module import the new client is reached through.
"""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
