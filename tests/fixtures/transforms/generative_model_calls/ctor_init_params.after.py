"""A model on the instance, built from what `__init__` was handed.

The rewrite folds the model's name into every call, and every call is in
another method, where `model_name` is not a name at all: each would raise
`NameError` (transforms:CODEMOD-01).
"""

from google import genai


class Desk:
    def __init__(self, api_key, model_name):
        self.client = genai.Client(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def answer(self, prompt):
        return self.model.generate_content(prompt).text
