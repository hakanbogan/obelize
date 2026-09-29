"""A tool declaration: moved across unchanged, it starts calling the function."""

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool

genai.configure(api_key="")

LOOKUP = Tool(
    function_declarations=[
        FunctionDeclaration(
            name="get_weather",
            description="Current weather for a city.",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
        )
    ]
)


def ask(question):
    model = genai.GenerativeModel("gemini-1.5-flash", tools=[LOOKUP])
    return model.generate_content(question).text
