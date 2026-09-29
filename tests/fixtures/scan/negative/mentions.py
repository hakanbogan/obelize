"""Shared constants for the pending SDK migration.

Two services still depend on google.generativeai; the tracking notes are at
https://ai.google.dev/gemini-api/docs/migrate#google.generativeai and the
distribution itself is https://pypi.org/project/google-generativeai/.

Nothing in this module imports either SDK.
"""

# TODO(hbogan): delete once svc-b stops importing google.generativeai.
LEGACY_IMPORT_PATH = "google.generativeai"

NEW_IMPORT_PATH = "google.genai"

DEPRECATION_NOTE = (
    "This service still uses the retired SDK; see LEGACY_IMPORT_PATH."
)


def is_legacy(module_name):
    return module_name.split(".")[0:2] == LEGACY_IMPORT_PATH.split(".")


def replacement_for(module_name):
    if is_legacy(module_name):
        return NEW_IMPORT_PATH
    return module_name
