"""A list of mappings held by a module-level name, passed to a chat's streaming call.

The role-play game in the benchmark declares its four safety rows once and hands them to each
`send_message`. On a chat the new SDK replaces the configuration the chat was created with, so
the call restates every key it carries; here that is the table alone, since the model had none.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

SAFETY = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


def converse(text):
    model = genai.GenerativeModel("gemini-1.5-flash")
    chat = model.start_chat()
    for chunk in chat.send_message(text, stream=True, safety_settings=SAFETY):
        print(chunk.text)
