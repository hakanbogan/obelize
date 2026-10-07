"""A different PDF library, which the rename must not touch."""

import fitz


def page_count(path):
    with fitz.open(path) as document:
        return document.page_count
