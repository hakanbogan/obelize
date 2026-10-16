"""A file that holds both SDKs: a legacy model beside a client the new one built.

The model migrates as in any other file, onto a client of its own. The call on
the client the new SDK built is left as it is, and does not withhold the rest.
"""

import google.generativeai as legacy
import google.genai as modern

legacy.configure(api_key="AIzaNotARealKey")

MODEL = legacy.GenerativeModel("gemini-1.5-flash")
client = modern.Client(api_key="AIzaNotARealKey")


def old(prompt):
    return MODEL.generate_content(prompt).text


def new(prompt):
    return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
