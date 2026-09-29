"""Both rungs of the ladder are taken, which is `client_name_collision`.

COVERAGE.md gap 8's last third. The import still moves -- that is the other
rule's edit and it succeeds -- but no run writes this file, because ADR-010
F-1 withholds a file whose client cannot be named.
"""

import os

from google import genai

client = os.environ.get("HTTP_CLIENT", "requests")
genai_client = os.environ.get("GENAI_CLIENT", "rest")

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
