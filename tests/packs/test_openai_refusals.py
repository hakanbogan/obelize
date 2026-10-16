"""What `openai/openai-0-to-1` refuses, or writes, for the image, moderation and audio calls.

Graded by running the product over a one-function file, since a rule's refusals are the pack's
claim (ADR-053 D19) and the generic contract only holds the fixtures. Each refused case is one a
review ran on both SDKs and found to differ, or a way to reach the call the scan must not miss.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from obelize.models import Config
from obelize.packs import loader
from obelize.scan import runner as scanner
from obelize.transforms import codemod

LOADED = loader.load("openai/openai-0-to-1")
SPEC = loader.to_scan_spec(LOADED)

# The function body, and the one code that withholds it (None: it is written).
CASES = [
    ('return openai.Image.create(prompt=x)["data"][0]["url"]', None),
    ('return openai.Image.create(x)["data"][0]["url"]', "positional_arg_ambiguous"),
    ('return openai.Image.create(prompt=x, response_format="b64_json")', "unsupported_kwarg"),
    ("return openai.Image.create(prompt=x, api_key=a)", "unsupported_kwarg"),
    ("return openai.Image.create(prompt=x, deployment_id=a)", "unsupported_kwarg"),
    ('return openai.Image.create(prompt=x, model="dall-e-2")["data"][0]["url"]', None),
    ('return openai.Image.create(prompt=x, model="dall-e-3")["data"][0]["url"]', None),
    ('return openai.Image.create(prompt=x, model=a)["data"][0]["url"]', None),
    ('return openai.Image.create(prompt=x, model=None)["data"][0]["url"]', None),
    ('return openai.Image.create(prompt=x, model="dall-e-" + a)["data"][0]["url"]', None),
    (
        'return openai.Image.create(prompt=x, model="gpt-image-1")["data"][0]["url"]',
        "response_shape_changed",
    ),
    (
        'return openai.Image.create(prompt=x, model="DALL-E-3")["data"][0]["url"]',
        "response_shape_changed",
    ),
    ('return openai.Image.create(prompt=x)["data"][0]["b64_json"]', "response_shape_changed"),
    ('return openai.Image.create(prompt=x)["data"][0]["revised_prompt"]', "response_shape_changed"),
    ('return [d["url"] for d in openai.Image.create(prompt=x, n=2)["data"]]', None),
    ('return [d for d in openai.Image.create(prompt=x, n=2)["data"]]', "response_shape_changed"),
    (
        'return [d["b64_json"] for d in openai.Image.create(prompt=x)["data"]]',
        "response_shape_changed",
    ),
    ('return openai.Moderation.create(input=x)["results"][0]["flagged"]', None),
    ("return openai.Moderation.create(x).id", None),
    ("return openai.Moderation.create(x)", "response_shape_changed"),
    ("openai.Moderation.create(input=x)", None),
    ("return openai.Moderation.create(input=x, model=None)", "unsupported_kwarg"),
    ('return openai.Moderation.create(x, "text-moderation-latest")', "positional_arg_ambiguous"),
    ("return openai.Moderation.create(x, None, a)", "positional_arg_ambiguous"),
    (
        'return openai.Moderation.create(input=x)["results"][0]["categories"]["hate"]',
        "response_shape_changed",
    ),
    ('first = openai.Moderation.create(input=x)["results"][0]\n    return first["flagged"]', None),
    (
        'first = openai.Moderation.create(input=x)["results"][0]\n    return first.get("flagged")',
        None,
    ),
    (
        'top = openai.Moderation.create(input=x)["results"][0]\n    return top.get("flagged", 1)',
        "response_shape_changed",
    ),
    (
        'first = openai.Moderation.create(input=x)["results"][0]\n    return first',
        "response_shape_changed",
    ),
    ('return openai.Audio.transcribe("whisper-1", a)["text"]', None),
    ('return openai.Audio.translate(model="whisper-1", file=a, prompt=x).text', None),
    (
        'return openai.Audio.transcribe("whisper-1", a, response_format="text")',
        "unsupported_kwarg",
    ),
    ('return openai.Audio.transcribe("whisper-1", a, deployment_id=x)', "unsupported_kwarg"),
    ('return openai.Audio.translate("whisper-1", a, language="en")', "unsupported_kwarg"),
    ('return openai.Audio.transcribe("whisper-1", a, x, a)', "positional_arg_ambiguous"),
    (
        'heard = openai.Audio.transcribe("whisper-1", a)\n    print(heard)',
        "response_shape_changed",
    ),
    ('heard = openai.Audio.transcribe("whisper-1", a)\n    return heard', "response_shape_changed"),
    ("return openai.Image.create_variation(image=a)", "flag_only_surface"),
    ("return openai.Image.create_edit(image=a, prompt=x)", "flag_only_surface"),
    ('return openai.Audio.transcribe_raw("whisper-1", a, "a.mp3")', "flag_only_surface"),
    ("return await openai.Image.acreate(prompt=x)", "flag_only_surface"),
    ("return await openai.Moderation.acreate(input=x)", "flag_only_surface"),
    ('return await openai.Audio.atranscribe("whisper-1", a)', "flag_only_surface"),
    ('openai.api_base = "http://h/v1"', None),
    ("openai.api_base = x", None),
    ('openai.api_base = x or "http://h/v1"', None),
    ("return openai.api_base", "attribute_removed"),
    ('openai.api_base += "/v1"', "attribute_removed"),
    ("del openai.api_base", "attribute_removed"),
    ("openai.api_base, a = x, 1", "attribute_removed"),
    ("openai.api_base = a = x", "attribute_removed"),
    ('openai.api_base = openai.api_base + "/v1"', "attribute_removed"),
    ('openai.api_base = "http://h/v1"; openai.api_type = "azure"', "flag_only_surface"),
    (
        'return openai.ChatCompletion.create(model=x, messages=a, api_base="http://h/v1")',
        "unsupported_kwarg",
    ),
    ('return openai.ChatCompletion.create(engine=x, messages=a)["id"]', None),
    ("return openai.Completion.create(engine=x, prompt=a).choices[0].text", None),
    ("return openai.Embedding.create(engine=x, input=a).data[0].embedding", None),
    ("return openai.ChatCompletion.create(engine=x, model=x, messages=a)", "unsupported_kwarg"),
    ("return openai.ChatCompletion.create(model=x, engine=x, messages=a)", "unsupported_kwarg"),
    ("return openai.ChatCompletion.create(deployment_id=x, messages=a)", "unsupported_kwarg"),
    ("return openai.Image.create(engine=x, prompt=a)", "unsupported_kwarg"),
    ('return openai.Audio.transcribe("whisper-1", a, request_timeout=30)', "unsupported_kwarg"),
    ("return openai.Embedding.create(model=x, input=a, request_timeout=30).model", None),
    ("return openai.Completion.create(model=x, prompt=a, request_timeout=0.5).id", None),
    (
        "return openai.ChatCompletion.create(model=x, messages=a, request_timeout=x)",
        "unsupported_kwarg",
    ),
    (
        "return openai.ChatCompletion.create(model=x, messages=a, request_timeout=0)",
        "unsupported_kwarg",
    ),
    (
        "return openai.Completion.create(model=x, prompt=a, request_timeout=None)",
        "unsupported_kwarg",
    ),
    (
        "return openai.ChatCompletion.create(model=x, messages=a, request_timeout=(3, 30))",
        "unsupported_kwarg",
    ),
    ("return openai.ChatCompletion.create(model=x, messages=a, timeout=30)", "unsupported_kwarg"),
    ("return openai.Image", "usage_unmapped"),
    ("return openai.Moderation.get_url()", "usage_unmapped"),
    ("return openai.Audio.OBJECT_NAME", "usage_unmapped"),
]


@pytest.mark.parametrize(("body", "withheld"), CASES, ids=[body for body, _ in CASES])
def test_a_call_is_written_or_withheld_by_the_code_the_pack_says(
    tmp_path: Path, body: str, withheld: str | None
) -> None:
    kind = "async def" if "await" in body else "def"
    (tmp_path / "app.py").write_text(
        f"import openai\n\n\n{kind} f(x, a):\n    {body}\n", encoding="utf-8"
    )
    scan = scanner.scan(tmp_path, Config(), SPEC, jobs=1)
    sources = {result.path: (tmp_path / result.path).read_bytes() for result in scan.results}
    run = codemod.run(scan, sources, LOADED.pack, SPEC)
    held = {edit.reason for edit in run.edits if edit.status != "auto"}
    assert (withheld in held) if withheld else not held, held
    assert bool(run.written) is (withheld is None)


@pytest.mark.parametrize(
    "header",
    [
        "from openai import Image\n",
        "from openai import Audio as sound\n",
        "from openai import api_base\n",
    ],
)
def test_a_name_imported_from_the_module_holds_the_file(tmp_path: Path, header: str) -> None:
    (tmp_path / "app.py").write_text(f"{header}\nx = 1\n", encoding="utf-8")
    scan = scanner.scan(tmp_path, Config(), SPEC, jobs=1)
    sources = {result.path: (tmp_path / result.path).read_bytes() for result in scan.results}
    run = codemod.run(scan, sources, LOADED.pack, SPEC)
    assert {edit.reason for edit in run.edits} == {"usage_unmapped"}
    assert run.written == ()


MODULE_LEVEL = "import openai\n\nresp = openai.ChatCompletion.create(model='m', messages=[])\n"
GLOBAL = (
    "import openai\n\n\ndef load():\n    global resp\n"
    "    resp = openai.ChatCompletion.create(model='m', messages=[])\n"
)


@pytest.mark.parametrize(
    ("holder", "reader", "line"),
    [
        (MODULE_LEVEL, "from a import resp\n\nprint(resp['usage']['total_tokens'])\n", 3),
        (MODULE_LEVEL, "import a\n\nprint(a.resp['usage']['total_tokens'])\n", 3),
        (GLOBAL, "from a import resp\n\nprint(resp['usage']['total_tokens'])\n", 6),
    ],
    ids=["imported by name", "read off the module", "assigned by global"],
)
def test_a_result_another_module_takes_holds_the_whole_repository(
    tmp_path: Path, holder: str, reader: str, line: int
) -> None:
    (tmp_path / "a.py").write_text(holder + "print(resp['usage']['total_tokens'])\n", "utf-8")
    (tmp_path / "b.py").write_text(reader, "utf-8")
    scan = scanner.scan(tmp_path, Config(), SPEC, jobs=1)
    sources = {result.path: (tmp_path / result.path).read_bytes() for result in scan.results}
    run = codemod.run(scan, sources, LOADED.pack, SPEC)
    assert ("a.py", line, "response_shape_changed") in {
        (edit.path, edit.line, edit.reason) for edit in run.edits
    }
    assert run.written == ()


MIGRATES = (
    "import openai\n\n\ndef ask(x):\n"
    "    return openai.ChatCompletion.create(model='m', messages=x).id\n"
)
HANDLED = "import openai\n\ntry:\n    pass\nexcept {caught} as e:\n    print(e.{read})\n"
INDIRECT = [
    ("import os\nos.environ['OPENAI_API_BASE'] = 'http://h/v1'\n", "flag_only_surface"),
    ("import os\nos.environ['OPENAI_ORGANIZATION'] += 'x'\n", "flag_only_surface"),
    ("import os\nos.environ.setdefault('OPENAI_API_BASE', 'x')\n", "flag_only_surface"),
    ("import os\nos.putenv('OPENAI_ORGANIZATION', 'org')\n", "flag_only_surface"),
    (
        "import os\nfrom unittest import mock\n"
        "mock.patch.dict(os.environ, {'OPENAI_API_BASE': 'x'})\n",
        "flag_only_surface",
    ),
    (
        "import os\nos.environ['OPENAI_API_KEY'] = 'k'\nbase = os.environ.get('OPENAI_API_BASE')\n"
        "os.environ['OPENAI_BASE_URL'] = base\n",
        None,
    ),
    (
        "from unittest import mock\nmock.patch('myapp.llm.openai.ChatCompletion.create')\n",
        "flag_only_surface",
    ),
    (
        "from unittest import mock\nmock.patch.object(myapp.llm.openai, 'ChatCompletion')\n",
        "flag_only_surface",
    ),
    ("from unittest import mock\nmock.patch.object(myapp.llm.openai, 'OpenAI')\n", None),
    (
        "import sys\nfrom unittest import mock\nmock.patch.dict(sys.modules, {'openai': 1})\n",
        "flag_only_surface",
    ),
    (HANDLED.format(caught="openai.APIError", read="http_status"), "attribute_removed"),
    (HANDLED.format(caught="(OSError, openai.OpenAIError)", read="json_body"), "attribute_removed"),
    (HANDLED.format(caught="openai.OpenAIError", read="user_message"), "attribute_removed"),
    (HANDLED.format(caught="openai.APIError", read="body"), None),
    (HANDLED.format(caught="openai.APIError", read="message"), None),
    ("import openai\n\n\ndef f(result: 'openai.Image'): ...\n", "usage_unmapped"),
    ("import openai\n\n\ndef f(result: 'Optional[openai.Image]'): ...\n", "usage_unmapped"),
    ("import openai\n\n\ndef f(result: 'openai.OpenAI'): ...\n", None),
]


@pytest.mark.parametrize(
    ("extra", "withheld"), INDIRECT, ids=[extra.splitlines()[-1] for extra, _ in INDIRECT]
)
def test_a_name_reached_without_a_call_holds_a_repository_that_would_migrate(
    tmp_path: Path, extra: str, withheld: str | None
) -> None:
    (tmp_path / "app.py").write_text(MIGRATES, encoding="utf-8")
    (tmp_path / "other.py").write_text(extra, encoding="utf-8")
    scan = scanner.scan(tmp_path, Config(), SPEC, jobs=1)
    sources = {result.path: (tmp_path / result.path).read_bytes() for result in scan.results}
    run = codemod.run(scan, sources, LOADED.pack, SPEC)
    held = {edit.reason for edit in run.edits if edit.status != "auto"}
    assert (withheld in held) if withheld else not held, held
    assert bool(run.written) is (withheld is None)
