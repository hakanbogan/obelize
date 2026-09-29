"""Thin wrapper around the current Google GenAI SDK.

This service was migrated in 2026-Q1. It binds the name `genai`, which is
exactly what the old SDK was usually aliased to, so the only thing that tells
the two apart is where the import comes from.
"""
# Migrated away from google.generativeai in 2026-Q1; do not reintroduce it.
import os

from google import genai
from google.genai import types

_client = None


def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def summarise(text, temperature=0.2):
    resp = client().models.generate_content(
        model="gemini-2.0-flash",
        contents=text,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    return resp.text


def stream_summary(text):
    for chunk in client().models.generate_content_stream(
            model="gemini-2.0-flash", contents=text):
        yield chunk.text


async def asummarise(text):
    resp = await client().aio.models.generate_content(
        model="gemini-2.0-flash", contents=text)
    return resp.text


def chat_once(question, history=None):
    chat = client().chats.create(model="gemini-2.0-flash", history=history or [])
    return chat.send_message(message=question).text
