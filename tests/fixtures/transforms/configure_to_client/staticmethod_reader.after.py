"""A reader in a static method, which has no instance to read a client off.

Row 3 puts the client on `self` and spells every reader against it, and a
static method has no `self`: `self.client.files.upload(...)` there is a
`NameError` (critic:NEW-02). A reader in a decorated method, or one whose first
parameter is not the receiver, is row 4.
"""

from google import genai


class Library:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)

    @staticmethod
    def upload(path):
        return genai.upload_file(path)
