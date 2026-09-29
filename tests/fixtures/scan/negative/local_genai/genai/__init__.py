"""A package in this repository that happens to be called `genai`.

It predates both Google SDKs and is a two-class stub used by the offline
test suite. `import genai` here resolves to an IMPORT, so only the module
prefix separates it from the real thing.
"""


class GenerativeModel:
    def __init__(self, name, **options):
        self.name = name
        self.options = options

    def generate_content(self, prompt):
        return _Response("stub:%s:%s" % (self.name, prompt))

    def start_chat(self, history=None):
        return _Chat(self, history or [])


class _Chat:
    def __init__(self, model, history):
        self.model = model
        self.history = history

    def send_message(self, content):
        self.history.append(content)
        return self.model.generate_content(content)


class _Response:
    def __init__(self, text):
        self.text = text


def configure(**kwargs):
    return dict(kwargs)
