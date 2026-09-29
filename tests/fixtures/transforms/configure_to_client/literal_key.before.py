"""The one shape ADR-013 D5 exempts from the mandatory warning.

`api_key=` is a non-empty string literal, so the migrated client cannot raise
`ValueError: No API key was provided.` where the legacy call returned quietly,
and the edit carries no `client_constructed_eagerly`.
"""

import google.generativeai as genai

genai.configure(api_key="test-key-not-a-real-credential")
