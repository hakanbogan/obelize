"""A name from a submodule is read through the new submodule."""

from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError


def readable(path):
    try:
        return len(PdfReader(path).pages) > 0
    except PdfReadError:
        return False
