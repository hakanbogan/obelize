from unittest import mock


def test_reply():
    with mock.patch("openai.ChatCompletion.create") as create:
        create.return_value = {}
        assert create() == {}
    with mock.patch("openai.OpenAI"):
        pass
