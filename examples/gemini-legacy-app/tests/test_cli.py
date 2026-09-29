"""End-to-end test of the command line, with the SDK boundary patched."""

from unittest.mock import MagicMock, patch

import pytest

from summarizer import cli


@pytest.fixture
def generative_model():
    with patch("google.generativeai.GenerativeModel") as ctor:
        ctor.return_value.generate_content.return_value = MagicMock(text="A summary.")
        chat = ctor.return_value.start_chat.return_value
        chat.send_message.return_value = MagicMock(text="An answer.")
        yield ctor


@pytest.fixture
def document(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Some text worth summarising.\n", encoding="utf-8")
    return str(doc)


def test_main_prints_the_summary(capsys, document, generative_model):
    assert cli.main([document]) == 0
    assert capsys.readouterr().out.strip() == "A summary."


def test_main_prints_the_follow_up_answer_when_asked(capsys, document, generative_model):
    assert cli.main([document, "--ask", "Why?"]) == 0

    out = capsys.readouterr().out
    assert "A summary." in out
    assert "An answer." in out


def test_main_reports_a_missing_file_without_calling_the_sdk(capsys, generative_model):
    assert cli.main(["/no/such/file.txt"]) == 2

    assert "cannot read" in capsys.readouterr().err
    generative_model.assert_not_called()
