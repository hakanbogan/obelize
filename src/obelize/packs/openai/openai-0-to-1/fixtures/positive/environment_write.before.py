import os
from unittest import mock


def configure(base):
    os.environ["OPENAI_API_BASE"] = base
    os.environ["OPENAI_ORGANIZATION"] += "-test"
    os.environ.setdefault("OPENAI_API_BASE", base)
    os.putenv("OPENAI_ORGANIZATION", "org-example")
    os.environ.update({"OPENAI_API_BASE": base})


def test_gateway():
    with mock.patch.dict(os.environ, {"OPENAI_API_BASE": "http://localhost:8080/v1"}):
        pass
