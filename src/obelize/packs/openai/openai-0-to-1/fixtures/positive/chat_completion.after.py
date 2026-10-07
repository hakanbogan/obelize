import os

import openai

openai.api_key = os.environ["OPENAI_API_KEY"]


def reply(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=256,
    )
    print(response.usage.total_tokens)
    return response.choices[0].message.content


def one_shot(prompt):
    return openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content


def fire_and_forget(prompt):
    openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
