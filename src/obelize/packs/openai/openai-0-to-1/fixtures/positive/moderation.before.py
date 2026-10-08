import openai


def flagged(text):
    return openai.Moderation.create(input=text)["results"][0]["flagged"]


def screen(text):
    response = openai.Moderation.create(text)
    return response.results[0].flagged
