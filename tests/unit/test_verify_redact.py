"""What redaction takes out of command output, and the documented limits of it.

Each sample joins two literals at import time, so no line on disk matches a secret scanner.
"""

from __future__ import annotations

import shlex

import pytest

from obelize.verify import redact

GOOGLE = "AIza" + "NotARealGoogleApiKeyForTestsOnly123"
OPENAI = "sk-" + "notarealopenaikey0000000"
AWS = "AKIA" + "NOTAREALAWSKEY12"
GITHUB = "ghp_" + "notarealgithubtoken000000000000000000"
# Split like the four above: written whole, the header trips `detect-private-key`.
PEM = "-----BEGIN RSA " + "PRIVATE KEY-----\nTk9UQVJFQUxLRVk=\n-----END RSA PRIVATE KEY-----"
AWS_SESSION = "ASIA" + "NOTAREALAWSKEY12"
GITHUB_OAUTH = "gho_" + "notarealgithubtoken000000000000000000"
GITHUB_FINE = "github_pat_" + "NotARealFineGrainedToken0_" + "x" * 30
HUGGING_FACE = "hf_" + "notarealhuggingfacetoken00000000000"
SLACK = "xoxb-" + "0000000000-aaaaaaaaaaaa"
STRIPE = "sk_live_" + "notarealstripekey0000"
GITLAB = "glpat-" + "notarealgitlabtoken0000"
PYPI = "pypi-" + "NotARealPyPIToken" * 3
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJub3QifQ" + "." + "bm90LWEtcmVhbC1zaWduYXR1cmU"

SHAPES = [
    (GOOGLE, "google"),
    (OPENAI, "openai"),
    (AWS, "aws"),
    (GITHUB, "github"),
    (PEM, "pem"),
    (AWS_SESSION, "aws session"),
    (GITHUB_OAUTH, "github oauth"),
    (GITHUB_FINE, "github fine grained"),
    (HUGGING_FACE, "hugging face"),
    (SLACK, "slack"),
    (STRIPE, "stripe"),
    (GITLAB, "gitlab"),
    (PYPI, "pypi"),
    (JWT, "jwt"),
]


@pytest.mark.parametrize(("secret", "shape"), SHAPES, ids=[name for _, name in SHAPES])
def test_every_documented_shape_is_removed(secret: str, shape: str) -> None:
    assert secret not in redact.redact(f"before {secret} after", {}), shape


@pytest.mark.parametrize(("secret", "shape"), SHAPES, ids=[name for _, name in SHAPES])
def test_what_surrounds_a_secret_survives_it(secret: str, shape: str) -> None:
    """A redactor that ate the line would take the reason for the failure too."""
    cleaned = redact.redact(f"before {secret} after", {})
    assert cleaned.startswith("before ")
    assert cleaned.endswith(" after")


def test_a_quoted_assignment_keeps_the_name_of_what_leaked() -> None:
    """The one pattern that keeps part of its match: the reader needs the name to rotate it."""
    assert redact.redact('api_key = "hunter2hunter2"', {}) == 'api_key = "[REDACTED]"'
    assert redact.redact("TOKEN: 'abcdefghij'", {}) == "TOKEN: '[REDACTED]'"


def test_a_short_quoted_value_is_not_a_secret() -> None:
    """Eight characters is the documented floor, and `THREAT_MODEL.md` sets it."""
    assert redact.redact('api_key = "short"', {}) == 'api_key = "short"'


def test_a_value_is_removed_when_its_variable_says_it_is_a_secret() -> None:
    environ = {"GEMINI_API_KEY": "abcdefghij", "PATH": "/usr/bin", "EDITOR": "vi"}
    assert redact.redact("key abcdefghij, path /usr/bin", environ) == (
        "key [REDACTED:GEMINI_API_KEY], path /usr/bin"
    )


def test_a_short_value_is_left_alone_however_it_is_named() -> None:
    """Otherwise `TOKEN=1` would turn every `1` in a build log into a marker."""
    assert redact.secrets({"TOKEN": "short"}) == ()
    assert redact.redact("exit 1 short", {"TOKEN": "short"}) == "exit 1 short"


def test_the_longest_value_goes_first() -> None:
    """Replacing a short prefix secret first would leave most of the long one in the log."""
    environ = {"A_TOKEN": "abcdefghij", "B_TOKEN": "abcdefghijklmnop"}
    assert [value for value, _ in redact.secrets(environ)] == [
        "abcdefghijklmnop",
        "abcdefghij",
    ]
    assert redact.redact("abcdefghijklmnop", environ) == "[REDACTED:B_TOKEN]"


def test_two_variables_holding_the_same_value_resolve_the_same_way_twice() -> None:
    """The sort is total, so the marker does not depend on dictionary order."""
    assert redact.secrets({"B_KEY": "abcdefghij", "A_KEY": "abcdefghij"}) == (
        ("abcdefghij", "[REDACTED:A_KEY]"),
        ("abcdefghij", "[REDACTED:B_KEY]"),
    )


NAMES = ["API_KEY", "GH_TOKEN", "MY_SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH_HEADER"]


@pytest.mark.parametrize("name", NAMES)
def test_every_documented_name_fragment_matches(name: str) -> None:
    assert redact.secrets({name: "abcdefghij"}) == (("abcdefghij", f"[REDACTED:{name}]"),)


@pytest.mark.parametrize("name", ["HOME", "PATH", "LANG", "obelize_run"])
def test_a_name_that_claims_nothing_is_not_searched_for(name: str) -> None:
    assert redact.secrets({name: "abcdefghij"}) == ()


def test_the_name_rule_ignores_case_and_therefore_over_matches() -> None:
    """`GIT_AUTHOR_NAME` contains `AUTH`: a documented cost; over-redaction is the safe side."""
    assert redact.secrets({"git_author_name": "Someone Long"}) != ()


def test_a_format_that_is_not_on_the_list_is_not_removed() -> None:
    """A limit `docs/PRIVACY.md` promises users, asserted so it cannot drift either way."""
    twilio = "SK" + "0123456789abcdef0123456789abcdef"
    assert redact.redact(twilio, {}) == twilio


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Authorization: Bearer abcdefghijklmnop0123", "Authorization: Bearer "),
        ("curl -H 'authorization: bearer abcdefghijklmnop0123'", "curl -H 'authorization: bearer "),
        ("postgres://app:hunter2hunter2@db.example/x", "postgres://app:"),
    ],
    ids=["bearer", "bearer lower case in quotes", "password in a url"],
)
def test_what_labels_a_secret_stays_and_the_secret_goes(text: str, kept: str) -> None:
    cleaned = redact.redact(text, {})
    assert cleaned.startswith(kept)
    assert cleaned[len(kept) :].startswith(redact.REDACTED)
    assert "hunter2" not in cleaned
    assert "abcdefghij" not in cleaned


def test_a_url_without_a_password_and_a_short_bearer_word_are_left_alone() -> None:
    text = "https://example.invalid:8080/path Bearer short user@host.invalid"
    assert redact.redact(text, {}) == text


def test_a_quoted_password_keeps_its_name() -> None:
    assert redact.redact("PASSWORD = 'hunter2hunter2'", {}) == "PASSWORD = '[REDACTED]'"
    assert redact.redact('db_passwd: "hunter2hunter2"', {}) == 'db_passwd: "[REDACTED]"'


@pytest.mark.parametrize("secret", [SLACK, JWT, PYPI, GITHUB_FINE])
def test_a_redacted_command_still_splits_into_the_arguments_it_had(secret: str) -> None:
    """A command is recorded as text, and the record is refused when `shlex` cannot split it."""
    command = f"python -c 'print(1)' --token {secret} --header \"Authorization: Bearer {secret}\""
    before, after = shlex.split(command), shlex.split(redact.redact(command, {}))
    assert len(before) == len(after)


def test_nothing_is_elided_below_the_cap() -> None:
    assert redact.cap(b"head", b"tail", 0) == ("headtail", False)


def test_the_marker_says_how_much_is_missing_and_what_it_is_called() -> None:
    text, truncated = redact.cap(b"head", b"tail", 42)
    assert truncated is True
    assert "output_truncated" in text
    assert "42 bytes" in text
    assert text.startswith("head")
    assert text.endswith("tail")


def test_output_that_is_not_utf8_travels_through_rather_than_raising() -> None:
    """A foreign-encoding file name or a mid-character cut must not lose the whole build log."""
    text, _ = redact.cap(b"caf\xe9", b"", 0)
    assert text.startswith("caf")


def test_the_cap_is_the_two_halves_the_documents_name() -> None:
    assert redact.HEAD_BYTES + redact.TAIL_BYTES == redact.OUTPUT_LIMIT
    assert redact.OUTPUT_LIMIT == 1024 * 1024
