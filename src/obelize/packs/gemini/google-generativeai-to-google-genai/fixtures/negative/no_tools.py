"""A tool declaration on the new SDK, with the calling behaviour made explicit."""

from google import genai
from google.genai import types

client = genai.Client()


def get_weather(city: str) -> str:
    return "23C"


def ask(question):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=question,
        config=types.GenerateContentConfig(
            tools=[get_weather],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    ).text
