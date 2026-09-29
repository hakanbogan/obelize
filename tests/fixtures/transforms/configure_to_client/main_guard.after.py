"""A `configure` under `if __name__ == "__main__":`.

Row 1 is "at module level", and this `configure` has no function around it,
so it was row 1: `client` is bound only when the file runs as a script, and
`answer()` reads it when the module is imported (transforms:CODEMOD-10). Row 1
is a statement directly in the module body now, and this is row 4.
"""

from google import genai


def answer(prompt):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(prompt).text


if __name__ == "__main__":
    genai.configure(api_key="AIzaNotARealKey")
    print(answer("hello"))
