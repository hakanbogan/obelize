"""C-22's own example: three positional arguments, the middle one skipped.

Every legacy constructor parameter is positional-or-keyword and the second is
the safety table, so the third positional is the configuration and a reader
who assumed otherwise would swap two arguments. The edit says the mapping was
made by index so the reader can check it.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    ).text
