import openai


def picture(prompt):
    response = openai.images.generate(prompt=prompt, n=1, size="256x256")
    return response.data[0].url


def hosted(prompt):
    response = openai.images.generate(model="dall-e-3", prompt=prompt, quality="hd", style="vivid")
    return response.data[0].url
