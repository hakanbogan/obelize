"""A model read through the chat surface, and a chat read through its own.

A binding group is the transitive closure of what its calls produce: the chat
is held by a method of the model, so the chat's own calls stand or fall with
it. Rewriting one and not the other leaves a new-SDK object being sent a
legacy-SDK message, which is why this file was the corpus's example of a group
refused whole until the methods had rewrites.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text


def converse(opening):
    chat = MODEL.start_chat(history=[])
    return chat.send_message(opening).text
