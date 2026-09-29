"""Tests for the summarisation path.

Every test patches `google.generativeai.GenerativeModel`, which is the whole SDK
boundary this module touches, so the suite needs no API key and no network.
"""

from unittest.mock import MagicMock, patch

import pytest

from summarizer import config, summarize


@pytest.fixture
def generative_model():
    with patch("google.generativeai.GenerativeModel") as ctor:
        ctor.return_value.generate_content.return_value = MagicMock(
            text="  The scheduler lock bug is fixed.  "
        )
        yield ctor


def test_summarize_text_returns_stripped_response_text(generative_model):
    assert summarize.summarize_text("some release notes") == (
        "The scheduler lock bug is fixed."
    )


def test_model_is_built_with_the_configured_name_and_settings(generative_model):
    summarize.summarize_text("some release notes")

    generative_model.assert_called_once()
    args, kwargs = generative_model.call_args
    assert args[0] == config.MODEL_NAME
    assert kwargs["generation_config"] == summarize.GENERATION_CONFIG
    assert kwargs["safety_settings"] == summarize.SAFETY_SETTINGS
    assert kwargs["system_instruction"] == "You are a terse technical editor."


def test_prompt_carries_the_body_and_the_sentence_budget(generative_model):
    summarize.summarize_text("polar bears", sentences=7)

    prompt = generative_model.return_value.generate_content.call_args[0][0]
    assert "polar bears" in prompt
    assert "at most 7 sentences" in prompt


def test_empty_input_is_rejected_before_the_sdk_is_touched(generative_model):
    with pytest.raises(ValueError):
        summarize.summarize_text("   \n  ")

    generative_model.assert_not_called()


def test_summarize_file_reads_utf8(tmp_path, generative_model):
    doc = tmp_path / "notes.txt"
    doc.write_text("Le résumé du jour.", encoding="utf-8")

    assert summarize.summarize_file(str(doc)) == "The scheduler lock bug is fixed."

    prompt = generative_model.return_value.generate_content.call_args[0][0]
    assert "Le résumé du jour." in prompt
