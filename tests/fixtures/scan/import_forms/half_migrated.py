"""A file that holds both SDKs: a legacy model beside a client the new one built.

The model's rows migrate as in any other file. The two calls on the client are
no legacy usage, so they report nothing and do not withhold the model's rows.
"""

import os

import google.generativeai as legacy
import google.genai as modern

legacy.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = legacy.GenerativeModel("gemini-1.5-flash")
client = modern.Client(api_key=os.environ["GEMINI_API_KEY"])


def old(prompt):
    return MODEL.generate_content(prompt).text


def new(prompt):
    return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text


def chat(prompt):
    return client.chats.create(model="gemini-2.0-flash").send_message(prompt).text
