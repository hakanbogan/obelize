"""Two fields a legacy `Model` had and the new one does not, read four ways.

`supported_generation_methods` and `base_model_id` are gone from
`google.genai.types.Model`, so each read raises `AttributeError` once the call
is rewritten -- and the `getattr` spelling does not raise, it quietly returns
the default. The last function reads only fields both have.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def generating():
    for model in genai.list_models():
        if "generateContent" in model.supported_generation_methods:
            print(model.name)


def generating_names():
    return [m.name for m in genai.list_models() if "embedContent" in m.supported_generation_methods]


def tuned_from():
    model = genai.get_model("models/gemini-1.5-flash")
    return model.base_model_id


def methods():
    model = genai.get_model("models/gemini-1.5-flash")
    return getattr(model, "supported_generation_methods", [])


def described():
    for model in genai.list_models():
        print(model.name, model.display_name)
