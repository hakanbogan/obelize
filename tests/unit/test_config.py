"""`.obelize.yml` loading, the flag merge and path selection.

docs/CLI.md's key table, always-excluded set and worked example are checked against the code.
"""

from __future__ import annotations

import errno
import re
import shlex
from pathlib import Path
from typing import Annotated, Any, Literal, get_args, get_origin

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from obelize.config import (
    ALWAYS_EXCLUDED,
    CONFIG_FILENAME,
    MISTAKEN_FILENAME,
    ConfigError,
    LoadedConfig,
    Overrides,
    Selection,
    documented_keys,
    flags,
    load,
    merge,
    model,
)
from obelize.models import DEFAULT_INCLUDE, PROVIDER_NAMES, Config, ModelConfig, VerifyConfig
from obelize.native import processes
from obelize.verify.runner import user_config
from platforms import AS_ROOT, deny, windows_only

ROOT = Path(__file__).resolve().parents[2]
CLI_DOC = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
RUN_FOLDER_DOC = (ROOT / "docs" / "RUN_FOLDER.md").read_text(encoding="utf-8")
EXAMPLE_APP = ROOT / "examples" / "gemini-legacy-app"

# `\|` is an escaped pipe inside a cell (the `model.provider` type row), not a boundary.
_CELL = re.compile(r"(?<!\\)\|")
_BACKTICKED = re.compile(r"`([^`]+)`")


def _rows(document: str, heading: str) -> list[list[str]]:
    body = document[document.index(heading) + len(heading) :]
    rows: list[list[str]] = []
    for line in body.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in _CELL.split(line)[1:-1]]
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue  # the ---|--- separator
        rows.append(cells)
    assert rows, f"no table found under {heading!r}"
    return rows[1:]  # the first row is the header


def _documented_default(cell: str) -> Any:
    if cell == "empty":
        return ()
    if cell == "unset":
        return None
    value = cell.strip("`")
    if value in ("true", "false"):
        return value == "true"
    return int(value) if value.isdigit() else value


def _type_name(annotation: Any) -> str:
    """The `Type` cell docs/CLI.md gives `annotation`."""
    if hasattr(annotation, "__metadata__"):  # typing.Annotated
        annotation = annotation.__origin__
    arguments = get_args(annotation)
    if type(None) in arguments:
        (inner,) = [argument for argument in arguments if argument is not type(None)]
        return _type_name(inner)
    origin = get_origin(annotation)
    if origin is Literal:
        return " \\| ".join(f"`{value}`" for value in arguments)
    if origin is tuple:
        return f"list of {_type_name(arguments[0])}s"
    return {bool: "boolean", int: "integer", str: "string"}[annotation]


def _field(dotted: str) -> Any:
    model: Any = Config
    for part in dotted.split("."):
        field = model.model_fields[part]
        model = field.annotation
    return field


def _value(config: Config, dotted: str) -> Any:
    value: Any = config
    for part in dotted.split("."):
        value = getattr(value, part)
    return value


DOCUMENTED = _rows(CLI_DOC, "\n## Configuration file (`.obelize.yml`)\n")
DOCUMENTED_KEYS = [row[0].strip("`") for row in DOCUMENTED]
# The `model:` table of the user's config file, the only place the model is configured.
USER_MODEL = _rows(CLI_DOC, "\nThe `model` keys are acted on by `obelize fix`")
ALWAYS_EXCLUDED_ROWS = _rows(CLI_DOC, "\n### The always-excluded set\n")
DOCUMENTED_PATTERNS = [
    pattern for row in ALWAYS_EXCLUDED_ROWS for pattern in _BACKTICKED.findall(row[0])
]


def _write(directory: Path, body: str, name: str = CONFIG_FILENAME) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_the_configuration_table_parses() -> None:
    """So a zero-row parse cannot pass the parametrized tests vacuously."""
    assert len(DOCUMENTED) == 7, DOCUMENTED_KEYS
    assert len(USER_MODEL) == 5, USER_MODEL
    assert DOCUMENTED_KEYS[0] == "include"
    assert all(len(row) == 4 for row in DOCUMENTED), DOCUMENTED


def test_every_documented_key_exists_and_every_key_is_documented() -> None:
    assert list(documented_keys()) == DOCUMENTED_KEYS, (
        "docs/CLI.md's configuration table and obelize.models.Config disagree. "
        "A key in one and not the other is a setting nobody can use or nobody can find."
    )


@pytest.mark.parametrize(("key", "type_name", "default", "_description"), DOCUMENTED)
def test_every_documented_type_is_the_type_the_model_declares(
    key: str, type_name: str, default: str, _description: str
) -> None:
    assert _type_name(_field(key.strip("`")).annotation) == type_name


@pytest.mark.parametrize(("key", "_type_name", "default", "_description"), DOCUMENTED)
def test_every_documented_default_is_the_default_the_model_uses(
    key: str, _type_name: str, default: str, _description: str
) -> None:
    assert _value(Config(), key.strip("`")) == _documented_default(default)


def test_the_users_model_table_is_the_model_block_in_both_directions() -> None:
    documented = [row[0].strip("`") for row in USER_MODEL]
    assert documented == [f"model.{key}" for key in documented_keys(ModelConfig)]


@pytest.mark.parametrize(("key", "type_name", "default", "_description"), USER_MODEL)
def test_every_documented_model_type_and_default_is_the_models(
    key: str, type_name: str, default: str, _description: str
) -> None:
    name = key.strip("`").removeprefix("model.")
    assert _type_name(ModelConfig.model_fields[name].annotation) == type_name
    assert getattr(ModelConfig(), name) == _documented_default(default)


def test_the_documented_include_default_is_the_constant_the_scanner_shares() -> None:
    assert Config().include == DEFAULT_INCLUDE
    assert f"`{DEFAULT_INCLUDE}`" in CLI_DOC


def test_the_worked_example_in_the_documentation_loads(tmp_path: Path) -> None:
    start = CLI_DOC.index("\n### Worked example\n")
    block = CLI_DOC[CLI_DOC.index("```yaml", start) + len("```yaml") :]
    _write(tmp_path, block[: block.index("```")])
    loaded = load(tmp_path)
    assert loaded.source == "file"
    assert loaded.config.verify.timeout_s == 900
    assert loaded.config.exclude == ("migrations/**", "docs/examples/**")


def test_the_always_excluded_table_and_the_code_agree() -> None:
    """Order too: the document groups the patterns in the tuple's order."""
    assert list(ALWAYS_EXCLUDED) == DOCUMENTED_PATTERNS, (
        "docs/CLI.md's always-excluded table and obelize.config.ALWAYS_EXCLUDED disagree"
    )
    assert len(ALWAYS_EXCLUDED) == len(set(ALWAYS_EXCLUDED))


def test_the_obelize_folder_leads_the_always_excluded_set() -> None:
    """The one entry that is a correctness property, not a performance one."""
    assert ALWAYS_EXCLUDED[0] == ".obelize/"


def test_the_run_folder_records_configuration_fields_that_exist() -> None:
    recorded = {row[0].strip("`") for row in _rows(RUN_FOLDER_DOC, "\n### `config`\n")}
    assert recorded - {"source"} <= set(documented_keys()), sorted(recorded)
    # `source` is not a setting: it records whether the file existed, which only the load knows.
    assert "source" in recorded
    assert set(get_args(LoadedConfig.model_fields["source"].annotation)) == {"file", "defaults"}


def test_a_repository_without_a_configuration_file_gets_the_documented_defaults(
    tmp_path: Path,
) -> None:
    loaded = load(tmp_path)
    assert loaded == LoadedConfig(config=Config(), source="defaults")


def test_an_empty_configuration_file_is_the_defaults_and_says_it_was_read(tmp_path: Path) -> None:
    _write(tmp_path, "# nothing but a comment\n")
    loaded = load(tmp_path)
    assert loaded.config == Config()
    assert loaded.source == "file"


def test_the_example_application_configuration_loads_exactly_as_written() -> None:
    """Four `must_not_report` rows in the example app's ground truth depend on this file."""
    loaded = load(EXAMPLE_APP)
    assert loaded == LoadedConfig(
        source="file",
        config=Config(
            include="**/*.py",
            exclude=("scripts/**",),
            verify=VerifyConfig(commands=("pytest -q",), timeout_s=300, junit=True),
        ),
    )


def test_the_example_applications_excluded_script_is_not_selected() -> None:
    selection = Selection(load(EXAMPLE_APP).config)
    assert not selection.selects("scripts/one_off_summary.py")
    assert selection.selects("src/gemini_legacy_app/config.py")


def test_a_configuration_file_under_the_other_spelling_is_refused_not_ignored(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "include: '**/*.py'\n", name=MISTAKEN_FILENAME)
    with pytest.raises(ConfigError, match="Rename it"):
        load(tmp_path)


def test_the_documented_spelling_wins_when_both_are_present(tmp_path: Path) -> None:
    _write(tmp_path, "max_file_bytes: 11\n")
    _write(tmp_path, "max_file_bytes: 22\n", name=MISTAKEN_FILENAME)
    assert load(tmp_path).config.max_file_bytes == 11


def test_a_configuration_file_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_bytes(b"include: '\xff\xfe.py'\n")
    with pytest.raises(ConfigError, match="not UTF-8"):
        load(tmp_path)


def test_something_named_like_the_configuration_file_that_is_not_one_is_refused(
    tmp_path: Path,
) -> None:
    """Present but unreadable is an error; only absent is the defaults."""
    (tmp_path / CONFIG_FILENAME).mkdir()
    with pytest.raises(ConfigError, match="cannot be read"):
        load(tmp_path)


@pytest.mark.skipif(AS_ROOT, reason="root searches a directory it may not")
def test_a_repository_that_will_not_say_whether_it_has_a_configuration_is_refused(
    tmp_path: Path,
) -> None:
    """3.14's `Path.exists` swallows a denial; the defaults could lose `allow_dirty: false`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo, "include: '**/*.py'\n")
    with deny(repo), pytest.raises(ConfigError, match="cannot be read"):
        load(repo)


def test_a_configuration_file_the_filesystem_will_not_describe_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows describes a denied name from its directory's listing, so a stub stands in there."""
    named = tmp_path / CONFIG_FILENAME
    lstat = Path.lstat

    def refusing(path: Path) -> Any:
        if path == named:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", refusing)
    with pytest.raises(ConfigError, match="cannot be read: Permission denied"):
        load(tmp_path)


def test_a_repository_cannot_configure_the_model(tmp_path: Path) -> None:
    """A cloned repository must not pick the endpoint or which env var is sent as the key."""
    _write(
        tmp_path,
        "model:\n  provider: openai_compat\n  base_url: https://example.invalid/v1\n"
        "  model: m\n  api_key_env: AWS_SECRET_ACCESS_KEY\n",
    )
    with pytest.raises(ConfigError, match="model settings are not read from a repository") as no:
        load(tmp_path)
    assert "Put the model block in ~/.config/obelize/config.yml" in str(no.value)


def test_a_refused_value_keeps_its_key_and_loses_pydantics_prefix(tmp_path: Path) -> None:
    _write(tmp_path, "verify:\n  commands: ['']\n")
    with pytest.raises(ConfigError) as refused:
        load(tmp_path)
    assert str(refused.value) == (
        f"{CONFIG_FILENAME} is not valid:\n"
        "  - verify.commands.0: a verification command must not be empty"
    )


def test_a_refused_verify_flag_is_named_as_the_flag_once_per_command() -> None:
    with pytest.raises(ConfigError) as refused:
        flags(["", "pytest 'x"], None, allow_dirty=False)
    assert str(refused.value).splitlines() == [
        "--verify is not valid: a verification command must not be empty",
        '--verify is not valid: "pytest \'x" does not split into arguments: No closing quotation',
    ]


# Commands a terminal displays as something other than what runs.
DISGUISED = {
    "carriage return and erase line": "python steal.py \r\x1b[2Kpytest -q",
    "cursor up": "python steal.py\x1b[1A",
    "right-to-left override": "python steal.py \u202eq- tsetyp",
}


@pytest.mark.parametrize("command", DISGUISED.values(), ids=list(DISGUISED))
def test_a_command_a_terminal_would_render_as_another_is_refused_where_it_is_read(
    tmp_path: Path, command: str
) -> None:
    """The approval prompt shows the text, so it must be what runs; refused before any prompt."""
    (tmp_path / CONFIG_FILENAME).write_text(
        yaml.safe_dump({"verify": {"commands": [command]}}), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="control, format or surrogate character"):
        load(tmp_path)


def test_a_tab_or_a_newline_in_a_command_is_only_whitespace() -> None:
    """`shlex` splits on both, so neither can disguise the command."""
    assert VerifyConfig(commands=("pytest\t-q", "pytest\n-q")).commands


def test_a_file_that_is_not_yaml_is_refused_with_a_line_and_a_column(tmp_path: Path) -> None:
    _write(tmp_path, "include: '**/*.py'\nexclude: [oops\n")
    with pytest.raises(ConfigError, match=rf"{re.escape(CONFIG_FILENAME)}:\d+:\d+: "):
        load(tmp_path)


def test_a_yaml_failure_without_a_position_still_names_the_file(tmp_path: Path) -> None:
    """A `ReaderError` carries no mark, so the message falls back to the reason."""
    (tmp_path / CONFIG_FILENAME).write_bytes(b"include: \x00\n")
    with pytest.raises(ConfigError, match="is not valid YAML: unacceptable character"):
        load(tmp_path)


def test_a_document_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    _write(tmp_path, "- include\n- exclude\n")
    with pytest.raises(ConfigError, match=r"holds a mapping of settings.*holds a list"):
        load(tmp_path)


def test_a_repeated_key_is_an_error_rather_than_the_last_one_winning(tmp_path: Path) -> None:
    """Plain YAML silently keeps the last one."""
    _write(tmp_path, "exclude: ['a/**']\nmax_file_bytes: 10\nexclude: ['b/**']\n")
    with pytest.raises(ConfigError, match=r"\.obelize\.yml:3: duplicate key 'exclude'"):
        load(tmp_path)


def test_a_repeated_key_inside_a_nested_mapping_is_an_error_too(tmp_path: Path) -> None:
    _write(tmp_path, "verify:\n  timeout_s: 10\n  timeout_s: 20\n")
    with pytest.raises(ConfigError, match="duplicate key 'timeout_s'"):
        load(tmp_path)


def test_a_key_that_is_not_a_string_is_refused_as_the_key_the_file_wrote(tmp_path: Path) -> None:
    """The duplicate-key check tracks string keys only; this is what catches the rest."""
    _write(tmp_path, "1: true\n2: false\n")
    with pytest.raises(ConfigError, match="1: Keys should be strings"):
        load(tmp_path)


def test_an_anchor_on_a_value_is_ordinary_yaml_and_works(tmp_path: Path) -> None:
    _write(tmp_path, "verify:\n  commands: &c ['pytest -q']\nexclude: *c\n")
    loaded = load(tmp_path)
    assert loaded.config.exclude == ("pytest -q",)


def test_a_merge_key_is_refused_and_was_never_usable_anyway(tmp_path: Path) -> None:
    """The key that would hold the anchor is itself unknown under `extra="forbid"`."""
    _write(tmp_path, "_base: &b {timeout_s: 30}\nverify:\n  <<: *b\n")
    with pytest.raises(ConfigError, match="constructor for the tag"):
        load(tmp_path)
    _write(tmp_path, "_base: {timeout_s: 30}\n")
    with pytest.raises(ConfigError, match="unknown key '_base'"):
        load(tmp_path)


def test_a_configuration_file_cannot_construct_a_python_object(tmp_path: Path) -> None:
    """The loader is a `SafeLoader` subclass, so a tag is refused, never called."""
    _write(tmp_path, "include: !!python/object/apply:os.system ['echo pwned']\n")
    with pytest.raises(ConfigError):
        load(tmp_path)


def test_an_error_message_never_carries_the_path_of_the_machine_it_ran_on(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "exclude: [oops\n")
    with pytest.raises(ConfigError) as caught:
        load(tmp_path)
    assert str(tmp_path) not in str(caught.value)
    assert CONFIG_FILENAME in str(caught.value)


def test_an_unknown_key_is_refused_and_the_near_miss_is_named(tmp_path: Path) -> None:
    _write(tmp_path, "verify:\n  timout_s: 30\n")
    with pytest.raises(ConfigError, match=re.escape("unknown key 'verify.timout_s'; did you mean")):
        load(tmp_path)


def test_an_unknown_key_with_no_near_miss_is_still_refused(tmp_path: Path) -> None:
    _write(tmp_path, "telemetry: true\n")
    with pytest.raises(ConfigError, match=r"unknown key 'telemetry'$"):
        load(tmp_path)


def test_every_problem_in_the_file_is_reported_not_just_the_first(tmp_path: Path) -> None:
    _write(tmp_path, "telemetry: true\nmax_file_bytes: 0\n")
    with pytest.raises(ConfigError) as caught:
        load(tmp_path)
    assert "unknown key 'telemetry'" in str(caught.value)
    assert "max_file_bytes: " in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        "max_file_bytes: 0\n",
        "max_file_bytes: -1\n",
        "verify:\n  timeout_s: 0\n",
        "include: ''\n",
        "include: '!**/*.py'\n",
        "exclude: ['scripts\\\\**']\n",
        "exclude: ['']\n",
        "include: ['**/*.py']\n",
        "verify:\n  commands: ['pytest -q | tee log']\n",
        'verify:\n  commands: ["\'unbalanced"]\n',
        "verify:\n  commands: ['   ']\n",
        "allow_dirty: 'yes please'\n",
    ],
)
def test_a_value_the_documentation_does_not_admit_is_refused(tmp_path: Path, body: str) -> None:
    _write(tmp_path, body)
    with pytest.raises(ConfigError):
        load(tmp_path)


# `model:` values the user's file refuses, with the message; a repository file refuses any `model:`.
USER_MODEL_REFUSALS = [
    ("api_key_env: 'sk-not-a-variable-name'", "is not a variable name"),
    ("provider: openai_compat", "needs base_url and model to be set"),
    ("provider: gemini", "should be 'none' or 'openai_compat'"),
    ("base_url: 'file:///etc/passwd'\n  model: m\n  provider: openai_compat", "http(s) URL"),
    ("base_url: 'https://'", "names no host"),
    ("base_url: 'https://user:secret@host/v1'", "must not carry credentials"),
]


@pytest.mark.parametrize(("body", "said"), USER_MODEL_REFUSALS)
def test_a_model_block_the_documentation_does_not_admit_is_refused_in_the_users_file(
    tmp_path: Path, body: str, said: str
) -> None:
    (tmp_path / "config.yml").write_text(f"model:\n  {body}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape(said)):
        user_config(tmp_path)


def test_a_pattern_that_does_not_compile_is_refused_when_the_file_is_read(tmp_path: Path) -> None:
    """Not mid-walk, where the message would not name the file."""
    _write(tmp_path, "exclude: ['!']\n")
    with pytest.raises(ConfigError, match="exclude is not a usable pattern"):
        load(tmp_path)


def test_a_command_that_needs_a_shell_says_so_and_offers_the_alternative() -> None:
    with pytest.raises(ValidationError, match=r"sh -c '<command>'"):
        VerifyConfig(commands=("pytest -q && ruff check .",))


def test_a_redirection_inside_a_token_is_not_a_shell_operator() -> None:
    assert VerifyConfig(commands=('python -c "print(1>2)"',)).commands


def test_a_command_this_system_would_read_otherwise_is_refused_wherever_one_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer for a backslash `shlex` would drop, stubbed here."""
    monkeypatch.setattr(processes, "command_problem", lambda text: f"{text!r} reads otherwise")
    _write(tmp_path, "verify:\n  commands: ['pytest -q']\n")
    with pytest.raises(ConfigError, match="'pytest -q' reads otherwise"):
        load(tmp_path)
    with pytest.raises(ValidationError, match="'pytest -q' reads otherwise"):
        Overrides(verify_commands=("pytest -q",))
    (tmp_path / "config.yml").write_text("verify:\n  allow: ['pytest -q']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="'pytest -q' reads otherwise"):
        user_config(tmp_path)


@windows_only("POSIX reads a backslash as `shlex` does; the stubbed test above refuses it there")
def test_a_backslash_windows_would_lose_is_refused_when_the_configuration_is_read(
    tmp_path: Path,
) -> None:
    """Control: split as every command is, the unquoted path loses its separator."""
    assert shlex.split("pytest tests\\unit") == ["pytest", "testsunit"]
    _write(tmp_path, "verify:\n  commands: ['pytest tests\\unit']\n")
    with pytest.raises(ConfigError, match="backslash"):
        load(tmp_path)
    assert VerifyConfig(commands=("pytest 'tests\\unit'",)).commands


def test_the_model_endpoint_is_recorded_as_a_host_and_never_as_a_url() -> None:
    """A query string can carry a credential; a host cannot."""
    assert ModelConfig(base_url="https://example.test:8443/v1?key=x").host == "example.test"
    assert ModelConfig().host is None


def test_every_provider_the_documentation_names_is_accepted() -> None:
    assert {"none", "openai_compat"} == PROVIDER_NAMES
    assert ModelConfig(provider="none").provider == "none"
    assert ModelConfig(provider="openai_compat", base_url="http://h/v1", model="m").provider


def test_no_flags_change_nothing() -> None:
    config = load(EXAMPLE_APP).config
    assert merge(config, Overrides()) == config


def test_a_verify_flag_replaces_the_files_commands_rather_than_adding_to_them() -> None:
    """So every command in such a run is one the user typed."""
    merged = merge(load(EXAMPLE_APP).config, Overrides(verify_commands=("pytest -q tests/unit",)))
    assert merged.verify.commands == ("pytest -q tests/unit",)


def test_a_timeout_flag_beats_the_file() -> None:
    merged = merge(load(EXAMPLE_APP).config, Overrides(timeout_s=30))
    assert merged.verify.timeout_s == 30
    assert merged.verify.junit is True


# Where the user's own file was read; a refusal names it as it is.
READ = Path("elsewhere", "obelize", "config.yml")


def test_a_provider_flag_beats_the_users_own_file() -> None:
    user = ModelConfig(base_url="http://localhost:11434/v1", model="qwen")
    assert model(user, "openai_compat", READ).provider == "openai_compat"
    assert model(user, None, READ) == user


def test_a_provider_flag_with_nowhere_to_send_a_request_fails_at_the_merge() -> None:
    with pytest.raises(ConfigError) as refused:
        model(ModelConfig(), "openai_compat", READ)
    assert str(refused.value) == (
        f"--model openai_compat with the model block in {READ} "
        "is not valid:\n  - provider 'openai_compat' needs base_url and model to be set"
    )


def test_a_provider_nobody_ships_is_refused_at_the_merge() -> None:
    with pytest.raises(ConfigError) as refused:
        model(ModelConfig(), "anthropic", READ)
    assert str(refused.value).splitlines()[1:] == [
        "  - provider: Input should be 'none' or 'openai_compat'"
    ]


def test_the_dirty_flag_adds_permission() -> None:
    assert merge(Config(), Overrides(allow_dirty=True)).allow_dirty is True


def test_the_dirty_flag_cannot_be_unset_by_its_own_absence() -> None:
    """A bare flag has no negative spelling, so the file's `true` stands."""
    assert merge(Config(allow_dirty=True), Overrides()).allow_dirty is True


def test_the_merge_carries_every_other_setting_through_untouched() -> None:
    config = Config(
        include="src/**/*.py",
        exclude=("a/**",),
        max_file_bytes=99,
    )
    merged = merge(config, Overrides(timeout_s=1))
    assert (merged.include, merged.exclude, merged.max_file_bytes) == ("src/**/*.py", ("a/**",), 99)


def test_the_model_flag_carries_every_other_model_setting_through_untouched() -> None:
    user = ModelConfig(
        provider="openai_compat",
        base_url="https://example.test/v1",
        model="m",
        api_key_env="MY_KEY",
        log_prompts=True,
    )
    assert model(user, "none", READ).model_dump() == {**user.model_dump(), "provider": "none"}


def test_a_command_from_the_command_line_is_validated_like_one_from_the_file() -> None:
    with pytest.raises(ValidationError):
        Overrides(verify_commands=("pytest | tee log",))


def test_an_override_carries_only_the_flags_that_overlap_the_file() -> None:
    """`--jobs`, `--json` and the trust flags are decisions about one run."""
    assert set(Overrides.model_fields) == {"verify_commands", "timeout_s", "allow_dirty"}
    with pytest.raises(ValidationError):
        Overrides.model_validate({"non_interactive": True})


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        (".obelize/", ".obelize/runs/20260917T142530Z-3f9a1c72/REPORT.md"),
        (".*/", ".git/config"),
        ("__pycache__/", "src/__pycache__/app.cpython-312.pyc"),
        ("site-packages/", "env/lib/python3.12/site-packages/google/generativeai/__init__.py"),
        ("venv/", "venv/bin/activate.py"),
        ("node_modules/", "node_modules/a/b.py"),
        ("vendor/", "third_party/vendor/a.py"),
        ("_vendor/", "pip/_vendor/a.py"),
        ("build/", "build/lib/a.py"),
        ("dist/", "dist/a.py"),
        ("*.egg-info/", "obelize.egg-info/a.py"),
    ],
)
def test_each_always_excluded_pattern_excludes_something(pattern: str, path: str) -> None:
    assert pattern in ALWAYS_EXCLUDED
    assert not Selection(Config(include="**/*")).selects(path)


def test_a_virtual_environment_is_caught_by_its_contents_not_by_its_name() -> None:
    """A venv can have any name, which is why `site-packages/` is in the set."""
    selection = Selection(Config())
    assert not selection.selects("whatever-i-called-it/lib/python3.12/site-packages/x.py")


def test_the_always_excluded_set_cannot_be_undone_by_the_configuration() -> None:
    """Otherwise the second scan of a repository reports the first one's report."""
    selection = Selection(Config(include="**/*", exclude=("!.obelize/**",)))
    assert not selection.selects(".obelize/runs/a/REPORT.md")


def test_a_negation_re_includes_something_the_same_list_excluded() -> None:
    selection = Selection(Config(exclude=("a/**", "!a/keep.py")))
    assert not selection.selects("a/drop.py")
    assert selection.selects("a/keep.py")


def test_include_is_applied_and_a_readme_is_never_a_python_file() -> None:
    """The byte prefilter runs after this; a README about a migration matches every token."""
    selection = Selection(Config())
    assert not selection.selects("README.md")
    assert not selection.selects("docs/MIGRATING.md")
    assert selection.selects("src/app.py")


def test_include_narrows_what_is_already_allowed_and_never_widens_it() -> None:
    selection = Selection(Config(include="src/**/*.py"))
    assert selection.selects("src/app.py")
    assert not selection.selects("tests/test_app.py")


def test_selection_does_not_touch_the_filesystem(tmp_path: Path) -> None:
    assert Selection(Config()).selects("nothing/like/this/exists.py")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("path", ["", "/etc/passwd", "src\\app.py"])
def test_a_path_that_is_not_repository_relative_is_refused(path: str) -> None:
    """A silent `False` here is a file that is never scanned and never explained."""
    with pytest.raises(ValueError, match="path to match"):
        Selection(Config()).selects(path)


def test_a_manifest_is_asked_about_without_include() -> None:
    """The default `include` (`**/*.py`) would drop every manifest; both exclusions still apply."""
    default = Selection(Config())
    assert default.decide("requirements.txt") == "not_included"
    assert default.selects_manifest("requirements.txt")
    assert not default.selects_manifest("vendor/requirements.txt")
    assert not Selection(Config(exclude=("scripts/**",))).selects_manifest(
        "scripts/requirements.txt"
    )


def test_a_directory_in_the_always_excluded_set_is_skipped_whole() -> None:
    assert Selection(Config()).prunes_directory("node_modules")
    assert Selection(Config()).prunes_directory("a/b/node_modules/")


def test_a_directory_the_user_excluded_is_still_walked(tmp_path: Path) -> None:
    """An excluded file importing the legacy package still breaks its pin; the report names it."""
    selection = Selection(Config(exclude=("scripts/**",)))
    assert not selection.prunes_directory("scripts")
    assert selection.decide("scripts/one_off.py") == "excluded"


def test_a_negating_list_still_re_includes_the_file_it_names() -> None:
    selection = Selection(Config(exclude=("a/**", "!a/keep.py")))
    assert selection.selects("a/keep.py")
    assert not selection.selects("a/drop.py")


def test_an_ordinary_directory_is_not_skipped() -> None:
    assert not Selection(Config()).prunes_directory("src")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", "selected"),
        (".obelize/runs/x/REPORT.md", "always_excluded"),
        ("node_modules/pkg/index.py", "always_excluded"),
        ("scripts/one_off.py", "excluded"),
        ("README.md", "not_included"),
        # Excluded and never included: `excluded` means a file the scan would otherwise read.
        ("scripts/helper.md", "not_included"),
    ],
)
def test_decide_names_the_rule_that_answered(path: str, expected: str) -> None:
    assert Selection(Config(exclude=("scripts/**",))).decide(path) == expected


def test_selects_is_exactly_the_selected_answer() -> None:
    selection = Selection(Config(exclude=("scripts/**",)))
    for path in ("src/app.py", "scripts/one_off.py", "README.md", ".obelize/x.py"):
        assert selection.selects(path) is (selection.decide(path) == "selected")


def test_the_key_list_is_dotted_and_in_declaration_order() -> None:
    keys = documented_keys()
    assert keys[:2] == ("include", "exclude")
    assert "verify.commands" in keys
    assert "verify" not in keys, "a nested model is not itself a settable key"


def test_the_key_list_walks_a_model_it_is_given() -> None:
    assert documented_keys(VerifyConfig) == ("commands", "timeout_s", "junit")


def test_a_configuration_model_refuses_an_unknown_key_by_construction() -> None:
    for kind in (Config, VerifyConfig, ModelConfig, Overrides, LoadedConfig):
        assert issubclass(kind, BaseModel)
        assert kind.model_config["extra"] == "forbid"
        assert kind.model_config["frozen"] is True


def test_annotated_types_survive_the_type_name_reader() -> None:
    """`verify.commands` is a tuple of an `Annotated[str, ...]`, not of a plain `str`."""
    assert _type_name(Annotated[str, "irrelevant"]) == "string"


# Answers from `git check-ignore --no-index` with each pattern in a scratch `.gitignore`.
GIT_ANSWERS = [
    # A directory matched by `*` is ignored whole; pathspec's plain gitignore pattern disagrees.
    ("legacy/*", "legacy/y.py", True),
    ("legacy/*", "legacy/sub/x.py", True),
    ("legacy/*", "keep/a.py", False),
    # A leading space is part of the pattern; only a trailing one is trimmed.
    (" spaced.py", " spaced.py", True),
    (" spaced.py", "spaced.py", False),
]


@pytest.mark.parametrize(("pattern", "path", "ignored"), GIT_ANSWERS)
def test_exclude_answers_the_way_git_answers(pattern: str, path: str, ignored: bool) -> None:
    decision = Selection(Config(exclude=(pattern,))).decide(path)
    assert decision == ("excluded" if ignored else "selected"), (pattern, path)


@pytest.mark.parametrize(("pattern", "path", "matched"), GIT_ANSWERS)
def test_include_matches_with_the_same_semantics(pattern: str, path: str, matched: bool) -> None:
    """One pattern language: `include: "src/*"` takes all of `src/` at any depth, as git does."""
    decision = Selection(Config(include=pattern)).decide(path)
    assert decision == ("selected" if matched else "not_included"), (pattern, path)
