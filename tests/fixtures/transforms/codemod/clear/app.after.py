"""The repository a run migrates whole.

Every eligible row is claimed by a rule, every rule applies, the bytes that
come out pass both output gates, and nothing is left importing the legacy
distribution -- so both halves of
[ADR-010](../../../../../docs/adr/ADR-010-fixture-oracle-and-atomicity.md) F-2
are clear and the manifest's legacy pin is *replaced* rather than joined.

`../blocked/` reaches the other manifest from a repository a scan grades
exactly as it grades this one.
"""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
