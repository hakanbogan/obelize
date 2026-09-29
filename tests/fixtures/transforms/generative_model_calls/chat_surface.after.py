"""A model read through the chat surface, and a chat read through its own.

A binding group is the transitive closure of what its calls produce: the chat
is held by a method of the model, so the chat's own calls stand or fall with
it. Rewriting one and not the other leaves a new-SDK object being sent a
legacy-SDK message, which is why this file was the corpus's example of a group
refused whole until the methods had rewrites.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text


def converse(opening):
    chat = client.chats.create(model="gemini-1.5-flash", history=[])
    return chat.send_message(message=opening).text
