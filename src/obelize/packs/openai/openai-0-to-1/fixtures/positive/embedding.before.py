import openai


def embed(text):
    response = openai.Embedding.create(input=text, model="text-embedding-3-small")
    return response.data[0].embedding
