"""The streaming flag, in both of the two spellings a literal can have.

`True` sends the call to a differently named method; `False` is the legacy
default written out, so the keyword goes and the call does not move. Anything
that is not one of the two is refused next door.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def chunks(prompt):
    for chunk in client.models.generate_content_stream(model="gemini-1.5-flash", contents=prompt):
        yield chunk.text


def whole(prompt):
    return client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text
