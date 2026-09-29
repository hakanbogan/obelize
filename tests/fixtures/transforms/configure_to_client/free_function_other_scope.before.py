"""A client made in `setup()`, and a file uploaded from another function.

`upload_file` is a free function in the legacy SDK and a method of the client
in the new one, so `upload()` needs the client as much as a model call does.
The placement table counted only the rows the scan's projection says need a
client, and a free function's rewrite is not one of them (COVERAGE.md gap 21),
so the client became a local of `setup()` and `upload()` was written to call a
name nothing in it binds (critic:NEW-01). Every call a running rule routes
through the client is a reader now, and this is row 4.
"""

import google.generativeai as genai


def setup(api_key):
    genai.configure(api_key=api_key)


def upload(path):
    return genai.upload_file(path)
