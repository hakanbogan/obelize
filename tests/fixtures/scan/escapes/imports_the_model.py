"""Reads a model built in another module, and names no SDK at all."""
from imported_model import MODEL


def title():
    return MODEL.model_name
