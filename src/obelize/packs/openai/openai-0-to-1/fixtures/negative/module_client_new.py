import os

import openai

openai.api_key = os.environ["OPENAI_API_KEY"]
openai.organization = "org-example"


def reply(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


def media(prompt, audio):
    openai.images.generate(prompt=prompt, n=1)
    openai.moderations.create(input=prompt)
    openai.audio.transcriptions.create(model="whisper-1", file=audio)
    return openai.audio.translations.create(model="whisper-1", file=audio).text
