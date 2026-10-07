"""A patch target on the new name is already right."""

from unittest import mock

import pypdf


def test_page_count():
    with mock.patch("pypdf.PdfReader") as reader:
        reader.return_value.pages = [object()]
        assert len(pypdf.PdfReader("x.pdf").pages) == 1
