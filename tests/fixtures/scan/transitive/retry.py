"""A retry policy built on google-api-core, which only the legacy SDK installs.

google-generativeai depends on google-api-core and google-genai does not, and
this repository never declared it. Dropping the legacy pin drops it too, and
`from google.api_core import retry` then fails when this module is imported.
"""

from google.api_core import retry

POLICY = retry.Retry(initial=1.0, maximum=10.0)
