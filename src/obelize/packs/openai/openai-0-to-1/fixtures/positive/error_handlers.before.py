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


def explain(prompt):
    try:
        return reply(prompt)
    except (ValueError, openai.APIError) as error:
        return error.http_status, error.json_body
    except openai.OpenAIError as error:
        return error.user_message
