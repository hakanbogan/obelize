"""Placement row 2: the `configure` is in a function and so are its uses.

A module-level assignment would leak the client out of the scope the author
put the setup in, so the client is a local where the `configure` was.

Every rule this file needs now exists, so the key beside it is the whole of
what `obelize fix --apply` writes. It was the two rules' partial output until
T12, which is why the model constructor is here at all.
"""

import os

from google import genai


def summarise(text):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return client.models.generate_content(model="gemini-1.5-flash", contents=text).text
