"""The camelCase classes PyPDF2 3.0.0 removed: obelize reports them and edits nothing."""

import PyPDF2


def page_count(path):
    return PyPDF2.PdfFileReader(path).getNumPages()
