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


def classes(error):
    return isinstance(
        error,
        (
            openai.error.APIConnectionError,
            openai.error.APIError,
            openai.error.AuthenticationError,
            openai.error.InvalidAPIType,
            openai.error.InvalidRequestError,
            openai.error.OpenAIError,
            openai.error.ServiceUnavailableError,
            openai.error.SignatureVerificationError,
            openai.error.TryAgain,
        ),
    )
