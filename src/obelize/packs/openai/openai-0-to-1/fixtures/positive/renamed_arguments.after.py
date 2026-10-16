import openai


def chat(prompt):
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        timeout=30,
    )
    return response.model, response.choices[0].message.content


def completion(prompt):
    response = openai.completions.create(
        prompt=prompt,
        model="gpt-3.5-turbo-instruct",
        timeout=2.5,
    )
    return response.model, response.choices[0].text


def embedding(text):
    response = openai.embeddings.create(input=text, model="text-embedding-3-small")
    return response.model, response.data[0].embedding
