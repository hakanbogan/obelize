"""Support desk assistant backed by Gemini."""

import google.generativeai as genai

SYSTEM_PROMPT = "You are a terse support assistant. Answer in at most three sentences."


class SupportAssistant:
    """Wraps one Gemini model for the whole support desk."""

    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            "gemini-1.5-flash",
            {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            },
            system_instruction=SYSTEM_PROMPT,
        )

    def answer(self, prompt):
        response = self.model.generate_content(prompt)
        return response.text

    def answer_stream(self, prompt):
        for chunk in self.model.generate_content(prompt, stream=True):
            yield chunk.text

    def conversation(self, text):
        chat = self.model.start_chat(
            history=[
                {"role": "user", "parts": ["hi"]},
                {"role": "model", "parts": ["Hello! What can I do for you?"]},
            ],
        )
        reply = chat.send_message(content=text)
        return reply.text

    async def answer_async(self, prompt):
        response = await self.model.generate_content_async(prompt)
        return response.text

    async def answer_async_stream(self, prompt):
        async for chunk in await self.model.generate_content_async(prompt, stream=True):
            yield chunk.text


class TemplateRenderer:
    """Unrelated to the SDK; it just happens to keep something on ``self.model``."""

    def __init__(self, model):
        self.model = model

    def render(self, **values):
        return self.model.format(**values)
