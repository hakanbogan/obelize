"""The files surface after migration: upload, get, list, delete."""

from google import genai
from google.genai import types

client = genai.Client()


def attach(path):
    uploaded = client.files.upload(
        file=path, config=types.UploadFileConfig(mime_type="text/plain", display_name="notes")
    )
    return uploaded.name


def fetch(name):
    return client.files.get(name=name)


def recent():
    return [handle.display_name for handle in client.files.list(
        config=types.ListFilesConfig(page_size=10)
    )]


def discard(name):
    client.files.delete(name=name)
