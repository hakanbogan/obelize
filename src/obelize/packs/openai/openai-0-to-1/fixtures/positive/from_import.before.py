from openai import ChatCompletion, OpenAIError


def reply(prompt):
    try:
        return ChatCompletion.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
        )
    except OpenAIError:
        return None
