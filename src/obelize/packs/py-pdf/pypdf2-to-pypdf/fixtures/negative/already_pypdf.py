"""Already on the new name: nothing here names the old module."""

from pypdf import PdfReader, PdfWriter


def copy_pages(source, target):
    writer = PdfWriter()
    for page in PdfReader(source).pages:
        writer.add_page(page)
    with open(target, "wb") as handle:
        writer.write(handle)
