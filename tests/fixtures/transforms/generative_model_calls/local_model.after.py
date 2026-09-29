"""A model built and read inside one function, with the client above it.

The binding is a local rather than a module constant, which is a different
row of the resolution table and the same rewrite: the constructor goes and
the name it bound stops existing.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text
