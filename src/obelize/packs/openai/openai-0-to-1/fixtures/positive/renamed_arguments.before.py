import openai


def chat(prompt):
    response = openai.ChatCompletion.create(
        engine="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        request_timeout=30,
    )
    return response.model, response.choices[0].message.content


def completion(prompt):
    response = openai.Completion.create(
        prompt=prompt, engine="gpt-3.5-turbo-instruct", request_timeout=2.5
    )
    return response.model, response.choices[0].text


def embedding(text):
    response = openai.Embedding.create(input=text, engine="text-embedding-3-small")
    return response.model, response.data[0].embedding
