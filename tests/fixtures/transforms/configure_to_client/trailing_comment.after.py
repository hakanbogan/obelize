"""What the statement line keeps when the statement inside it is replaced.

`basic/app.py:7` is this shape and `basic/app.after.py:8` is the answer: the
comment written above the call and the one written after it are both about the
line and not about the expression, so both stay where the author put them.
"""

import os

from google import genai

# The key is read once, at import time, and never again.
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep this comment
