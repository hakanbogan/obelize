import openai
from openai.embeddings_utils import cosine_similarity


def closeness(first, second):
    return cosine_similarity(first, second)
