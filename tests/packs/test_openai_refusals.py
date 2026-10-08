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
    "header", ["from openai import Image\n", "from openai import Audio as sound\n"]
)
def test_a_name_imported_from_the_module_holds_the_file(tmp_path: Path, header: str) -> None:
    (tmp_path / "app.py").write_text(f"{header}\nx = 1\n", encoding="utf-8")
    scan = scanner.scan(tmp_path, Config(), SPEC, jobs=1)
    sources = {result.path: (tmp_path / result.path).read_bytes() for result in scan.results}
    run = codemod.run(scan, sources, LOADED.pack, SPEC)
    assert {edit.reason for edit in run.edits} == {"usage_unmapped"}
    assert run.written == ()
