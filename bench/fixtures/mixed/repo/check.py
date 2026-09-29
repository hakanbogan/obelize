"""Exercise both halves, so a regression in either one is visible.

The second half is the one obelize withholds. It has to keep working after the
patch as well -- a partial migration that broke the file it declined to touch
would be a `wrong` case and not a `partial` one.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "_vendor"))

import clean  # noqa: E402
import factory  # noqa: E402

assert clean.summarize("hello") == "gemini-1.5-flash:hello"
assert factory.ask("gemini-1.5-pro", "hi") == "gemini-1.5-pro:hi"
print("ok")
