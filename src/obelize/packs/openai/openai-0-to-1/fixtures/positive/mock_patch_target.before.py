import sys
from unittest import mock

import myapp.llm


def test_reply():
    with mock.patch("openai.ChatCompletion.create") as create:
        create.return_value = {}
        assert create() == {}
    with mock.patch("openai.OpenAI"):
        pass


def test_own_module():
    with mock.patch("myapp.llm.openai.ChatCompletion.create"):
        pass
    with mock.patch.object(myapp.llm.openai, "ChatCompletion"):
        pass
    with mock.patch.object(myapp.llm.openai, "OpenAI"):
        pass
    with mock.patch.dict(sys.modules, {"openai": mock.Mock()}):
        pass
