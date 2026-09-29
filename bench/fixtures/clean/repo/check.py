"""The fixture's test command: exercise the module the migration changes.

Run before the patch and again after it. It imports the module, calls the
function the rewrite touches and asserts on what comes back, so a patch that
renames the import and leaves the call site broken fails here rather than
passing a check that only compiled the file.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "_vendor"))

import app  # noqa: E402

answer = app.summarize("hello")
assert answer.endswith(":hello"), answer
assert "gemini-1.5-flash" in answer, answer
print("ok")
