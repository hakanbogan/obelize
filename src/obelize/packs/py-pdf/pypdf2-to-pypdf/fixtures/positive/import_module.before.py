"""The module imported whole: its name goes, and each read goes through the new module."""

import PyPDF2


def page_count(path):
    return len(PyPDF2.PdfReader(path).pages)


def merge(paths, target):
    writer = PyPDF2.PdfWriter()
    for path in paths:
        for page in PyPDF2.PdfReader(path).pages:
            writer.add_page(page)
    with open(target, "wb") as handle:
        writer.write(handle)
