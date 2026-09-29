"""A model named as a resource rather than as a bare name.

Both SDKs accept it, so it is carried across exactly as written and pointed
at rather than rewritten: a rule that tidied the author's string would be
changing a value it has no evidence about.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(model="models/gemini-1.5-flash", contents=prompt).text
