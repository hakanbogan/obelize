import os

import openai


def from_the_environment(prompt):
    openai.base_url = ("%s" % (os.environ["MOCK_URL"],)).rstrip("/") + "/"
    return openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content


def with_a_slash_already(prompt):
    openai.base_url = ("%s" % (os.environ["MOCK_URL"] + "/",)).rstrip("/") + "/"
    return openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content


def a_literal_first(prompt):
    openai.base_url = "https://proxy.example.com/v1/"
    openai.base_url = 'http://localhost:8000/v1/'
    openai.base_url = ("%s" % (os.environ["MOCK_URL"],)).rstrip("/") + "/"
    return openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content


def through_a_name(prompt):
    address = os.environ["MOCK_URL"]
    openai.base_url = ("%s" % (address,)).rstrip("/") + "/"
    return openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    ).choices[0].message.content
