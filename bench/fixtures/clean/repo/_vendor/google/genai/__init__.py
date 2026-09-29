"""The new surface the fixture migrates to, with the real argument names.

`Client(api_key=...)`, `client.models.generate_content(model=..., contents=...)`
and a response carrying `.text` are what `google-genai` 2.24.0 exposes; the
signatures here are copied from it so that a patch which satisfies this double
would also satisfy the real distribution.
"""


class _Response:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, api_key):
        self._api_key = api_key

    def generate_content(self, *, model, contents):
        if not self._api_key:
            raise RuntimeError("no api_key")
        return _Response(f"{model}:{contents}")


class Client:
    def __init__(self, *, api_key=None):
        self.models = _Models(api_key)
