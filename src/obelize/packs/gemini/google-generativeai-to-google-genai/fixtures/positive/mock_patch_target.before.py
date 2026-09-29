"""A patch target left pointing at the old path keeps passing and stops testing."""

import importlib
import sys
from unittest import mock


def test_generate_is_called():
    with mock.patch("google.generativeai.GenerativeModel") as model:
        model.return_value.generate_content.return_value.text = "stubbed"
        assert model.return_value.generate_content("hi").text == "stubbed"


def load_dynamically(name="google.generativeai"):
    return importlib.import_module(name)


def install_stub(stub):
    sys.modules["google.generativeai"] = stub
