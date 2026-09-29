"""A patch target that keeps passing and stops testing anything.

The string is a live reference: `mock.patch` imports the module by name when
the patch is entered, so a target left pointing at the legacy path intercepts a
call the migrated code no longer makes. The mention in `NOTE` is the opposite
shape and must not be claimed -- it is prose, `not_a_usage`, and carries no
bail for this rule to read.
"""

from unittest import mock

NOTE = "the target below names google.generativeai and this sentence does too"


def test_generate(monkeypatch):
    with mock.patch("google.generativeai.GenerativeModel") as built:
        built.return_value.generate_content.return_value.text = "ok"
    monkeypatch.setattr("google.generativeai.configure", lambda **kwargs: None)
