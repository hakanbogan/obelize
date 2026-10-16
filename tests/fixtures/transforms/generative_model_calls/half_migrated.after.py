"""A file that holds both SDKs: a legacy model beside a client the new one built.

The model migrates as in any other file, onto a client of its own. The call on
the client the new SDK built is left as it is, and does not withhold the rest.
"""

from google import genai as legacy
import google.genai as modern

genai_client = legacy.Client(api_key="AIzaNotARealKey")
client = modern.Client(api_key="AIzaNotARealKey")


def old(prompt):
    return genai_client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text


def new(prompt):
    return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
