import openai
from openai import api_base as default_base


def read():
    return openai.api_base


def grow():
    openai.api_base += "/v1"


def forget():
    del openai.api_base


def both(url):
    openai.api_base, openai.api_key = url, "key"


def chained(url):
    openai.api_base = openai.api_key = url
