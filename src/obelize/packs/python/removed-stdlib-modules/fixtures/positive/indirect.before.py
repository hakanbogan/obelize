import importlib
from unittest import mock


def load():
    return importlib.import_module("telnetlib")


def test_loop():
    with mock.patch("asyncore.loop"):
        pass
