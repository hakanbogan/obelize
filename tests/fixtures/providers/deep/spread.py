"""A line in two groups, where the two groups are not the same size.

`MODEL` is bound at module level and used inside `talk`; `chat` is bound from
that use and used on the line below it. Line 24 is therefore in both groups,
and they disagree about how far the context has to reach: `chat`'s group fits
inside `talk`, and `MODEL`'s does not.

The rule takes the union, so line 24 gets the whole module and line 25 gets
`talk` alone. An implementation that looked the line up in one group rather
than in all of them would answer `talk` for both -- and a proposal about
`MODEL.start_chat()` that cannot see where `MODEL` came from is the failure
[ADR-036](../../../../docs/adr/ADR-036-model-requests-answers.md)
D2 is about.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"seed": 7})


def talk(prompt):
    chat = MODEL.start_chat()
    return chat.send_message(prompt).text
