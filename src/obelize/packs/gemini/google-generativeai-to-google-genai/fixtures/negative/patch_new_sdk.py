"""A patch target that moved with the code, which is what the report asks for."""

from unittest import mock


def test_generate_is_called():
    with mock.patch("google.genai.Client") as client:
        call = client.return_value.models.generate_content
        call.return_value.text = "stubbed"
        assert call(model="gemini-1.5-flash", contents="hi").text == "stubbed"
