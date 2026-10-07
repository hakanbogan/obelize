"""Names that exist unchanged on both sides stay in a `from` import of the new module."""

from pypdf import PdfReader, PdfWriter as Writer


def copy_pages(source, target):
    writer = Writer()
    for page in PdfReader(source).pages:
        writer.add_page(page)
    with open(target, "wb") as handle:
        writer.write(handle)
