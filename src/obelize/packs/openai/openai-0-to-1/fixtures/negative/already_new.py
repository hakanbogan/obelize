from openai import AsyncOpenAI, OpenAI, OpenAIError, RateLimitError
from openai.types.chat import ChatCompletion

client = OpenAI()
async_client = AsyncOpenAI()


def reply(prompt: str) -> ChatCompletion:
    try:
        return client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
        )
    except RateLimitError:
        raise
    except OpenAIError as error:
        raise RuntimeError("failed") from error
