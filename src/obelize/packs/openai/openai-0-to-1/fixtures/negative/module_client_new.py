import os

import openai

openai.api_key = os.environ["OPENAI_API_KEY"]
openai.organization = "org-example"


def reply(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
