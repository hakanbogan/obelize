"""Optional-dependency loader for the plugin system.

The SDK is reached by name at run time so the package can stay an extra.
None of the four forms below is visible to qualified-name resolution.
"""
import importlib
import sys

import google.generativeai as genai


def load_sdk():
    try:
        return importlib.import_module("google.generativeai")
    except ImportError:  # pragma: no cover - extra not installed
        return None


def load_sdk_legacy():
    return __import__("google.generativeai")


def model_class():
    return getattr(genai, "GenerativeModel")


def install_stub(stub):
    sys.modules["google.generativeai"] = stub
    return stub
