import openai


def flagged(text):
    return openai.moderations.create(input=text).results[0].flagged


def screen(text):
    response = openai.moderations.create(input=text)
    return response.results[0].flagged
