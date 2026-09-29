"""The legacy surface the fixture uses, and nothing else."""

_configured = {}


def configure(api_key):
    _configured["api_key"] = api_key


class _Response:
    def __init__(self, text):
        self.text = text


class GenerativeModel:
    def __init__(self, model_name):
        self.model_name = model_name

    def generate_content(self, contents):
        if not _configured.get("api_key"):
            raise RuntimeError("configure() was not called")
        return _Response(f"{self.model_name}:{contents}")
