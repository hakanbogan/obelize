"""Modules only PyPDF2 1 ships: obelize reports them and edits nothing."""

from PyPDF2.pdf import PdfFileReader
from PyPDF2.utils import PdfReadError


def page_count(path):
    try:
        return PdfFileReader(path).getNumPages()
    except PdfReadError:
        return 0
