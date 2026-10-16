"""A `configure()` that names no key, so the environment supplies it.

The two SDKs read different variables first, and the rule does not look at the
environment: it writes `Client()` and warns only that the client checks its key
when it is built, which a module-level one does at import.
"""

import google.generativeai as genai

genai.configure()
