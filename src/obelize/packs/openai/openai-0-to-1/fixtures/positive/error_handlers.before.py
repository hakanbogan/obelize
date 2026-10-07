import openai


def reply(prompt):
    try:
        return openai.ChatCompletion.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
        )
    except openai.error.RateLimitError:
        return None
    except openai.InvalidRequestError as error:
        raise ValueError(error.http_status) from error
