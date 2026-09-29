"""Both names on one `from` line, and both of them consumed.

`GenerativeModel` moved to no module at all and `configure` became an object,
so neither name survives the rewrite. The line that bound them becomes the
module import the two new calls are reached through, which is the answer the
one-rule corpus next door cannot give.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text
