"""A stream bound to a name, and walked by a loop and by nothing else.

The one shape besides a loop's header that the new call keeps: every read of
the name is the iterable of a `for`.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def chunks(prompt):
    stream = client.models.generate_content_stream(model="gemini-1.5-flash", contents=prompt)
    for chunk in stream:
        yield chunk.text
