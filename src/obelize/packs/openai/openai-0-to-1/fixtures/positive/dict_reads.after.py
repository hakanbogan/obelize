import os

import openai

openai.api_key = os.environ["OPENAI_API_KEY"]


def chat(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return (
        response.id,
        response.created,
        response.model,
        response.choices[0].index,
        response.choices[0].finish_reason,
        response.choices[0].message.role,
        response.choices[0].message.content,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        response.usage.total_tokens,
    )


def completion(prompt):
    response = openai.completions.create(model="gpt-3.5-turbo-instruct", prompt=prompt)
    return (
        response.id,
        response.created,
        response.model,
        response.choices[0].index,
        response.choices[0].finish_reason,
        response.choices[0].text,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        response.usage.total_tokens,
    )


def embedding(prompt):
    result = openai.embeddings.create(model="text-embedding-3-small", input=prompt)
    return (
        result.model,
        result.data[0].index,
        result.data[0].embedding,
        result.usage.prompt_tokens,
        result.usage.total_tokens,
    )


def one_shot(prompt):
    return openai.completions.create(model="gpt-3.5-turbo-instruct", prompt=prompt).choices[0].text


def mixed(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def guarded(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        return response.choices[1].message.content
    except IndexError:
        return None


def picture(prompt):
    response = openai.images.generate(prompt=prompt, n=1, size="256x256")
    return response.created, response.data[0].url


def moderation(prompt):
    response = openai.moderations.create(input=prompt)
    return response.id, response.model, response.results[0].flagged


def transcription(path):
    with open(path, "rb") as audio:
        result = openai.audio.transcriptions.create(model="whisper-1", file=audio)
    return result.text
