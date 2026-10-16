import openai
import openai as faults
from openai import PermissionDeniedError


def ask(prompt):
    try:
        return openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content
    except openai.RateLimitError:
        return "rate limited"
    except PermissionDeniedError:
        return "forbidden"
    except (faults.APITimeoutError, ValueError):
        return "slow"


def rate_limited(prompt):
    return ask("status:429")


def forbidden(prompt):
    return ask("status:403")


def answered(prompt):
    return ask(prompt)
