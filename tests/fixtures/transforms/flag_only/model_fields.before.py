"""The two `types.Model` fields the new dataclass does not have.

Read off the class rather than off an instance, which is the only spelling a
per-file scan resolves: a `Model` is handed back by `get_model` and by
`list_models`, and neither result is a receiver this projection knows, so an
instance read is reported by nothing (COVERAGE.md gap 20).
"""

import google.generativeai as genai

FIELDS = (
    genai.types.Model.base_model_id,
    genai.types.Model.supported_generation_methods,
)
