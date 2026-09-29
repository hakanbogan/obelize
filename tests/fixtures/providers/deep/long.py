"""One function that grew, which is the shape the context cap is for.

`review` holds a prompt that a team kept adding lines to, and the two rows that
bail sit at its two ends: the constructor on line 23 and the use on line 109.
Neither arm of the context rule can cover that.

The enclosing scope is the whole function, which is longer than the cap. The
window around the group is the group's span plus a margin either side, and the
span alone is more than eighty lines. So there is no range that both holds the
whole group and stays inside the budget, and the row is not sent at all --
which is the answer a fail-closed rule has to give. A rule that truncated
instead would send a context the proposal could not be checked against, and
[ADR-003](../../../../docs/adr/ADR-003-model-adapter.md)'s guard is written
around "the edit stays inside the range that was sent".
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def review(diff):
    model = genai.GenerativeModel(
        "gemini-1.5-flash",
        generation_config={"seed": 7},
    )
    guidance = (
        "You are reviewing a pull request for a small Python library.\n"
        "Read the diff before you read the description.\n"
        "Say what the change does in one sentence.\n"
        "Then list what you would ask the author to change.\n"
        "\n"
        "What to look for, in this order:\n"
        "- A behaviour change that the description does not mention.\n"
        "- A public name that changed without a deprecation.\n"
        "- An exception that is caught and not re-raised.\n"
        "- A bare except.\n"
        "- A mutable default argument.\n"
        "- A comparison with None that uses == rather than is.\n"
        "- A dictionary lookup that assumes a key is present.\n"
        "- An index into a sequence that may be empty.\n"
        "- A loop that mutates the thing it iterates over.\n"
        "- A file opened without an encoding.\n"
        "- A path built by string concatenation.\n"
        "- A subprocess call with shell=True.\n"
        "- A temporary file with a predictable name.\n"
        "- A credential, a token or a key in the diff itself.\n"
        "- A log line that prints a credential.\n"
        "- A sleep in a test.\n"
        "- A test that asserts nothing.\n"
        "- A test whose name does not say what it asserts.\n"
        "- A fixture that reaches outside its own directory.\n"
        "- A mock that patches a name the code no longer calls.\n"
        "- An assertion on a message string rather than on a type.\n"
        "- A comment that says what the code says.\n"
        "- A comment that says something the code stopped doing.\n"
        "- A docstring that describes a parameter that is gone.\n"
        "- A type annotation that disagrees with the default.\n"
        "- An Optional that is never None.\n"
        "- An Any that could be narrowed.\n"
        "- A cast that hides a real mismatch.\n"
        "- A public function with no annotation at all.\n"
        "- A module-level constant that is mutated.\n"
        "- A global that is written from more than one place.\n"
        "- An import inside a function with no reason given.\n"
        "- A circular import worked around rather than removed.\n"
        "- A dependency added for one call.\n"
        "- A vendored file with no upstream reference.\n"
        "- A generated file edited by hand.\n"
        "- A lock file that does not match the manifest.\n"
        "- A version pinned in two places.\n"
        "- A migration with no rollback.\n"
        "- A schema change with no default for existing rows.\n"
        "- An index added without a query that uses it.\n"
        "- A query inside a loop.\n"
        "- A transaction held open across a network call.\n"
        "- A retry with no backoff.\n"
        "- A retry on an error that will not clear.\n"
        "- A timeout that is absent rather than long.\n"
        "- A cache with no expiry.\n"
        "- A cache key that omits something the value depends on.\n"
        "- A background task whose failure is not reported.\n"
        "- A thread that is started and never joined.\n"
        "- A lock taken in two different orders.\n"
        "- A counter incremented without a lock.\n"
        "- A float used for money.\n"
        "- A naive datetime compared with an aware one.\n"
        "- A date formatted for a machine with a human format.\n"
        "- A sort whose key is not total.\n"
        "- An equality that compares floats exactly.\n"
        "- A regular expression that can backtrack badly.\n"
        "- A user string interpolated into a query.\n"
        "- A user string interpolated into a shell command.\n"
        "- A redirect to a URL the user supplied.\n"
        "- An error message that leaks an internal path.\n"
        "- A retry that logs at error level on every attempt.\n"
        "- A metric emitted with an unbounded label.\n"
        "- A feature flag with no owner and no removal date.\n"
        "- A TODO with no issue behind it.\n"
        "- A configuration default that differs between environments.\n"
        "- A secret read at import time.\n"
        "- A health check that does not check anything.\n"
        "\n"
        "Finish with the single change you would make first.\n"
        "\n"
        "The diff follows.\n"
        "\n"
    )
    return model.generate_content(guidance + diff).text
