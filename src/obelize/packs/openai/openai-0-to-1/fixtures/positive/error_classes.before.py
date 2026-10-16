import openai
import openai.error as faults
from openai.error import PermissionError


def ask(prompt):
    try:
        return openai.ChatCompletion.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
        )["choices"][0]["message"]["content"]
    except openai.error.RateLimitError:
        return "rate limited"
    except PermissionError:
        return "forbidden"
    except (faults.Timeout, ValueError):
        return "slow"


def rate_limited(prompt):
    return ask("status:429")


def forbidden(prompt):
    return ask("status:403")


def answered(prompt):
    return ask(prompt)
