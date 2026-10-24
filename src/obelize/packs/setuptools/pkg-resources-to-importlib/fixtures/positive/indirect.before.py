import importlib
from unittest import mock


def load():
    return importlib.import_module("pkg_resources")


def test_plugins():
    with mock.patch("pkg_resources.iter_entry_points", return_value=[]):
        pass
