"""Tests for the summariser. Nothing here touches the network."""
from unittest import mock

from myapp import summariser


@mock.patch("google.generativeai.GenerativeModel")
def test_summarise_uses_model(model_cls):
    model_cls.return_value.generate_content.return_value.text = "ok"
    assert summariser.summarise("hello") == "ok"


@mock.patch("myapp.summariser.genai")
def test_summarise_through_our_module(genai_mod):
    genai_mod.GenerativeModel.return_value.generate_content.return_value.text = "ok"
    assert summariser.summarise("hello") == "ok"


def test_configure_is_called(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "google.generativeai.configure", lambda **kw: seen.append(kw)
    )
    summariser.summarise("hi")
    assert seen == [{"api_key": "test-key"}]
