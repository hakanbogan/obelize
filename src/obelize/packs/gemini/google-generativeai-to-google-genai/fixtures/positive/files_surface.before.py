"""Upload, get, list and delete, which are four calls and one client."""

import google.generativeai as genai

genai.configure(api_key="")


def attach(path):
    uploaded = genai.upload_file(path, mime_type="text/plain", display_name="notes")
    return uploaded.name


def fetch(name):
    return genai.get_file(name)


def recent():
    return [handle.display_name for handle in genai.list_files(page_size=10)]


def discard(name):
    genai.delete_file(name)
