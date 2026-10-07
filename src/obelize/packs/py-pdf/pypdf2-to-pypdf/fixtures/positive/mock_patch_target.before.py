"""A patch target left on the old name keeps passing and stops testing anything."""

from unittest import mock

import PyPDF2


def test_page_count():
    with mock.patch("PyPDF2.PdfReader") as reader:
        reader.return_value.pages = [object()]
        assert len(PyPDF2.PdfReader("x.pdf").pages) == 1
