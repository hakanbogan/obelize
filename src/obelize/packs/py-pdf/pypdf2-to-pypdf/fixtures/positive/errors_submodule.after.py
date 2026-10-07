"""A name from a submodule is read through the new submodule."""

from pypdf import PdfReader
from pypdf import errors


def readable(path):
    try:
        return len(PdfReader(path).pages) > 0
    except errors.PdfReadError:
        return False
