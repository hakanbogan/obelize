"""An alias the author wrote survives, so the reads through it stay as they are."""

import pypdf as pdf


def first_page_text(path):
    return pdf.PdfReader(path).pages[0].extract_text()
