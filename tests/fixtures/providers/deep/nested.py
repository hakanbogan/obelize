"""A nested function, and a credential in a comment.

Two measurements live here. The group that bails -- `model` is constructed and
used inside `run`, not inside `make` -- fixes which scope the context is taken
from: the smallest one that holds the whole group, which is the inner function
and not the outer one that returns it.

The comment on line 30 is the other. It carries a key of the exact shape
`docs/THREAT_MODEL.md` lists under TM-3, in the place TM-3 names: a comment. It
is thirty-nine characters of nothing, but it is the thirty-nine characters the
redactor matches, and the context that reaches a model must not contain it.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

PREFIXES = {
    "terse": "In one sentence: ",
    "long": "In three paragraphs: ",
}


def make(kind):
    """Return a summariser bound to one prompt style."""
    prefix = PREFIXES[kind]

    def run(body):
        # Rotated on 2026-09-01; the key this used to read was
        # AIzaSyD00000000000000000000000000000000, which the audit log still names.
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"seed": 7},
        )
        return model.generate_content(prefix + body).text

    return run
