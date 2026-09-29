"""Prints two secrets it was handed, so the redactor has something to remove.

Neither is written down here. The harness builds both, puts them in the
environment and asserts they are in this program's raw output before it asserts
they are absent from the recorded one -- a "nothing was redacted" pass has to be
impossible, and it is impossible only if the control runs first.

The two variables are named differently on purpose. `OBELIZE_SAMPLE_PLAIN` does
not match the secret-name pattern, so removing its value is the *pattern* rule
doing it; `OBELIZE_TEST_TOKEN` does, so removing its value is the *value* rule,
and the two leave different markers.
"""

import os

print("plain:", os.environ["OBELIZE_SAMPLE_PLAIN"])
print("named:", os.environ["OBELIZE_TEST_TOKEN"])
