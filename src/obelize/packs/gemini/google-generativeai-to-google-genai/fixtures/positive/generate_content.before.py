"""The constructor, its configuration, its safety table and the chat surface."""

import google.generativeai as genai

genai.configure(api_key="")

model = genai.GenerativeModel(
    "gemini-1.5-pro",
    system_instruction="Answer in one sentence.",
    generation_config=genai.GenerationConfig(temperature=0.2, max_output_tokens=256),
    safety_settings={"HATE": "BLOCK_ONLY_HIGH", "harm_category_sexual": "block_none"},
)


def summarise(text):
    return model.generate_content(text).text


def stream(text):
    for chunk in model.generate_content(text, stream=True):
        yield chunk.text


def size(text):
    return model.count_tokens(text).total_tokens


def converse(opening):
    chat = model.start_chat(history=[{"role": "user", "parts": ["hello"]}])
    return chat.send_message(opening).text
