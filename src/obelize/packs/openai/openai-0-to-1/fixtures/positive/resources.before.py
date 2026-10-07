import openai


def picture(prompt):
    return openai.Image.create(prompt=prompt, n=1, size="256x256")


def moderate(text):
    return openai.Moderation.create(input=text)
