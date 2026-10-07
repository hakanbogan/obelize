"""The module imported whole: its name goes, and each read goes through the new module."""

import pypdf


def page_count(path):
    return len(pypdf.PdfReader(path).pages)


def merge(paths, target):
    writer = pypdf.PdfWriter()
    for path in paths:
        for page in pypdf.PdfReader(path).pages:
            writer.add_page(page)
    with open(target, "wb") as handle:
        writer.write(handle)
