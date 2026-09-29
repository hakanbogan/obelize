"""The model and the client in one function, and a free function in another.

The typical script: `main()` configures and builds the model, a helper
uploads. Counting the model's rows alone, every reader was in `main()` and the
client was a local there; the helper was written against a name it cannot see
(critic:NEW-01). With the helper counted, no single placement reaches every
reader.
"""

import google.generativeai as genai


def main(api_key, prompt):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(prompt).text


def upload(path):
    return genai.upload_file(path)
