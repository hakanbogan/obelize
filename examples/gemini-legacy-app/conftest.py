"""Test-suite setup for the example app.

Living at the project root rather than in `tests/` on purpose: pytest puts the
directory holding the root `conftest.py` on `sys.path`, which is what makes
`import summarizer` work without installing the package or adding a
`pyproject.toml`.

The environment variable is set here, before any test module imports
`summarizer.config`, because that module calls `genai.configure(...)` at import
time. No network call is made and the value is not a real key: every test
patches the SDK boundary.
"""

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-a-real-credential")
os.environ.setdefault("SUMMARIZER_MODEL", "gemini-1.5-flash")
