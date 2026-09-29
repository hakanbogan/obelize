"""C-19: a `credentials=` that is a dict literal, which the new client refuses.

The keyword is allowed and the *shape* is not, which is why this bail is its
own code rather than `configure_kwargs_unsupported`. COVERAGE.md gap 5.

No run writes this file: the key beside it shows the import moved, because the
other rule succeeded, and F-1 withholds the whole file because this one did not.
"""

from google import genai

genai.configure(credentials={"token": "not-a-real-token", "refresh_token": None})
