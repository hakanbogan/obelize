"""Tests for the chat path.

`start_chat` and `send_message` are reached through the same patched
`google.generativeai.GenerativeModel`, so this needs no API key either.
"""

from unittest.mock import MagicMock, patch

import pytest

from summarizer.conversation import FollowUp

SUMMARY = "The scheduler no longer holds the job table lock."


@pytest.fixture
def chat_session():
    with patch("google.generativeai.GenerativeModel") as ctor:
        chat = ctor.return_value.start_chat.return_value
        chat.send_message.return_value = MagicMock(text="Because of the audit row.\n")
        chat.history = [object(), object()]
        yield ctor


def test_followup_primes_the_session_with_a_two_turn_history(chat_session):
    FollowUp(SUMMARY)

    history = chat_session.return_value.start_chat.call_args[1]["history"]
    assert [turn["role"] for turn in history] == ["user", "model"]
    assert history[0]["parts"] == ["You are reviewing a summary I wrote."]


def test_ask_sends_the_summary_with_the_question_and_strips_the_reply(chat_session):
    follow_up = FollowUp(SUMMARY)

    answer = follow_up.ask("Why did the stalls happen?")

    assert answer == "Because of the audit row."
    sent = chat_session.return_value.start_chat.return_value.send_message.call_args[0][0]
    assert SUMMARY in sent
    assert "Why did the stalls happen?" in sent


def test_the_chat_session_is_reused_across_questions(chat_session):
    follow_up = FollowUp(SUMMARY)

    follow_up.ask("First?")
    follow_up.ask("Second?")

    chat_session.return_value.start_chat.assert_called_once()
    assert chat_session.return_value.start_chat.return_value.send_message.call_count == 2


def test_turns_reports_the_session_history_length(chat_session):
    assert FollowUp(SUMMARY).turns() == 2
