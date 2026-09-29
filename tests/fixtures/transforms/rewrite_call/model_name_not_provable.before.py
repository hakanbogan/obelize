"""Three model names the rewrite cannot carry, and the reason is one fact.

The legacy `get_model` dispatched on the prefix of the name it was given:
`models/...` came back as a Model and `tunedModels/...` as a different
dataclass. `client.models.get` always returns a Model, so the rewrite is right
only for a literal the pack names a prefix for -- and a name held in a
variable, a name under the other prefix and a call with no name at all are all
refused rather than guessed at.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def by_name(name):
    return genai.get_model(name)


def tuned():
    return genai.get_model("tunedModels/my-tuned-model")


def whatever_the_default_was():
    return genai.get_model()
