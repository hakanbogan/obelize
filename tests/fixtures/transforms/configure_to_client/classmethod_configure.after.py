"""A `configure` in a class method, with a reader in an instance method.

Row 3 reads the receiver off the configuring method's first parameter, and
here that is `cls`: the client would be `cls.client`, and the instance method
would be written to read `cls`, which it does not have
(transforms:CODEMOD-03). A decorated configuring method is row 4.
"""

from google import genai


class Desk:
    @classmethod
    def setup(cls, api_key):
        genai.configure(api_key=api_key)

    def upload(self, path):
        return genai.upload_file(path)
