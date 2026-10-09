import os

import openai

openai.api_key = os.environ["OPENAI_API_KEY"]
openai.proxy = "http://proxy.example.com:3128"
openai.api_type = "azure"
openai.api_version = "2023-05-15"


def reply(prompt):
    return openai.ChatCompletion.create(
        engine="my-deployment", messages=[{"role": "user", "content": prompt}]
    )
