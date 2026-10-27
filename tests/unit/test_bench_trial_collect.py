"""The parts of the trial collector that need no Docker: its arguments, what it refuses before it
touches a container, what it removes, and how it keeps and resumes a record."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import trialrecords as records
import yaml

from bench import trial_box, trial_collect
from platforms import BENCH

pytestmark = BENCH

INSTALLED = {"3.9": "3.9.25", "3.12": "3.12.14", "3.13": "3.13.15"}


def test_a_work_directory_inside_the_repository_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    inside = trial_collect.ROOT / "bench" / "work" / "trial"
    with pytest.raises(SystemExit) as raised:
        trial_collect.main(["smoke", "proj", "lib", "--work", str(inside)])
    assert raised.value.code == 2
    assert "--work must be outside the repository" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        trial_collect.main(["run", "-m", "pydantic-1-to-2", "--work", str(trial_collect.ROOT)])


def test_work_is_required_and_only_needs_an_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        trial_collect.main(["run", "-m", "pydantic-1-to-2"])
    with pytest.raises(SystemExit):
        trial_collect.main(
            ["run", "-m", "pydantic-1-to-2", "--only", "o/r", "--work", str(tmp_path)]
        )
    assert "--only measures part of a frame" in capsys.readouterr().err


def test_a_migration_that_is_not_a_frame_is_refused() -> None:
    with pytest.raises(SystemExit):
        trial_collect.main(["run", "-m", "not-a-frame", "--work", "/nowhere"])


def test_the_home_directory_is_never_copied_into_a_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "me")
    for held in (tmp_path / "me", tmp_path):
        with pytest.raises(SystemExit, match="holds the home directory"):
            trial_collect.smoke(held, "lib", None, tmp_path, None, None, trial_box.Limits(), None)


def test_a_frame_with_no_repository_whose_dry_run_writes_a_file_stops_before_any_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "frames" / "lib").mkdir(parents=True)
    (tmp_path / "frames" / "lib" / "sample.yaml").write_text(
        yaml.safe_dump({"repositories": [{"full_name": "o/r", "sha": "a" * 40, "band": "b"}]})
    )
    (tmp_path / "dry").mkdir()
    (tmp_path / "dry" / "lib.json").write_text(
        json.dumps({"upgrade": [{"full_name": "o/r", "files": 0}]})
    )
    monkeypatch.setattr(trial_collect, "FRAMES", tmp_path / "frames")
    monkeypatch.setattr(trial_collect, "DRY_RUNS", tmp_path / "dry")
    monkeypatch.setattr(trial_collect, "docker", lambda *a, **k: pytest.fail("docker was run"))
    with pytest.raises(SystemExit, match="no repository whose dry run writes a file"):
        trial_collect.run("lib", tmp_path, tmp_path, None, 2, None, False, trial_box.Limits(), None)


def test_the_committed_dry_runs_select_nothing_until_they_are_measured_again() -> None:
    """0.9.0 wrote no file in any of the 80 plans, so no repository is tried until the dry run is
    made again with the rule that writes a file at a time."""
    for path in sorted(trial_collect.DRY_RUNS.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "unit" not in record:
            assert trial_box.select(record) == [], path.name


class Docker:
    """A stand-in for `docker` that records what it is asked."""

    def __init__(self, listed: str) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.listed = listed

    def __call__(self, *arguments: str, **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments, 0, self.listed if arguments[0] == "ps" else "", ""
        )


def test_cleanup_removes_only_what_has_the_label_and_the_prefix_and_the_two_networks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Docker("obelize-trial-r-1\nemlaksal-postgres\nobelize-trial-proxy\nobelize-other\n")
    monkeypatch.setattr(trial_collect, "docker", fake)
    trial_collect.cleanup()
    assert fake.calls == [
        ("ps", "--all", "--filter", "label=obelize-trial=1", "--format", "{{.Names}}"),
        ("rm", "--force", "--volumes", "obelize-trial-r-1"),
        ("rm", "--force", "--volumes", "obelize-trial-proxy"),
        ("network", "rm", "obelize-trial-net"),
        ("network", "rm", "obelize-trial-out"),
    ]
    assert "removed 2 container(s)" in capsys.readouterr().out
    monkeypatch.setattr(trial_collect, "docker", lambda *a, **k: pytest.fail("not run"))
    with pytest.raises(SystemExit):
        trial_collect.main(["cleanup", "--bad"])


def test_cleanup_is_a_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Docker("")
    monkeypatch.setattr(trial_collect, "docker", fake)
    assert trial_collect.main(["cleanup"]) == 0
    assert fake.calls[0][0] == "ps"


def test_a_docker_command_that_fails_stops_with_its_words(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert argv[0] == "docker"
        return subprocess.CompletedProcess(argv, 1, "", "no such image")

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(SystemExit, match="docker image inspect failed: no such image"):
        trial_collect.docker("image", "inspect", "x")
    assert trial_collect.docker("image", "inspect", "x", check=False).returncode == 1


def test_a_repository_is_copied_in_as_a_user_the_box_has() -> None:
    info = tarfile.TarInfo("repo/run.sh")
    info.uid, info.gid, info.uname, info.gname, info.mode = 501, 20, "me", "staff", 0o4755
    owned = trial_collect._owned(info)
    assert (owned.uid, owned.gid, owned.uname, owned.gname, owned.mode) == (
        10001,
        10001,
        "",
        "",
        0o755,
    )


def test_the_python_comes_from_the_files_of_the_repository(tmp_path: Path) -> None:
    assert trial_collect.python_for(tmp_path, INSTALLED) == "3.12"
    (tmp_path / ".python-version").write_text("3.9\n")
    assert trial_collect.python_for(tmp_path, INSTALLED) == "3.9"
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.10"\n')
    assert trial_collect.python_for(tmp_path, INSTALLED) == "3.13"
    (tmp_path / "pyproject.toml").write_bytes(b"\xff\xfe not utf-8")
    assert trial_collect.python_for(tmp_path, INSTALLED) == "3.9"


def test_a_stream_is_drained_into_a_capture() -> None:
    capture = trial_box.Capture(head=3, tail=3)
    trial_collect.drain(io.BytesIO(b"abcdefghij"), capture)
    assert capture.text() == "abc\n[4 byte(s) cut]\nhij"


HEADER = {"wheel_sha256": "a" * 64, "image": "sha256:" + "b" * 64}


def test_an_earlier_record_is_resumed_only_by_the_wheel_and_image_that_made_it(
    tmp_path: Path,
) -> None:
    target = tmp_path / "lib.json"
    assert trial_collect._resumed(target, HEADER, False) == {}
    rows = [records.row(full_name="o/a"), records.row(full_name="o/b")]
    target.write_text(json.dumps({**HEADER, "trial": rows}))
    assert set(trial_collect._resumed(target, HEADER, False)) == {"o/a", "o/b"}
    assert trial_collect._resumed(target, HEADER, True) == {}
    with pytest.raises(SystemExit, match="another wheel or image: pass --again"):
        trial_collect._resumed(target, {**HEADER, "image": "sha256:other"}, False)
    with pytest.raises(SystemExit, match="another wheel or image"):
        trial_collect._resumed(target, {**HEADER, "wheel_sha256": "0" * 64}, False)


def test_a_record_is_kept_whole_in_the_order_of_its_frame_after_every_repository(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out" / "lib.json"
    entries = [{"full_name": name} for name in ("o/a", "o/b", "o/c")]
    done = {"o/c": records.row(full_name="o/c"), "o/a": records.row(full_name="o/a")}
    trial_collect._save(target, HEADER, entries, done, {"allow": {}, "deny": {}, "error": {}})
    saved = json.loads(target.read_text())
    assert [row["full_name"] for row in saved["trial"]] == ["o/a", "o/c"]
    assert saved["wheel_sha256"] == HEADER["wheel_sha256"]
    assert saved["proxy"] == {"allow": {}, "deny": {}, "error": {}}
    assert not target.with_suffix(".tmp").exists()


def test_a_repository_that_could_not_be_fetched_is_a_record_that_validates() -> None:
    failed = trial_collect._failed(
        {"full_name": "o/r", "sha": "a" * 40, "band": "b"}, {"distribution": "lib", "from": "1"}
    )
    assert (failed["status"], failed["reason"]) == ("error", "fetch")
    record = records.record([failed])
    assert trial_box.validate_record(record) == []


def test_the_limits_are_the_defaults_unless_a_flag_changes_one() -> None:
    import argparse

    assert trial_collect._limits(argparse.Namespace()) == trial_box.Limits()
    changed = trial_collect._limits(argparse.Namespace(wall=60, disk_gb=1))
    assert (changed.wall_s, changed.disk_gb, changed.memory_gb) == (60, 1, 2)


def test_the_collectors_own_records_and_frames_are_where_the_scorer_reads_them() -> None:
    from bench import trial_score, upgrade_collect

    assert trial_collect.RESULTS == trial_score.RECORDS
    assert trial_collect.FRAMES == upgrade_collect.FRAMES
    assert trial_collect.DRY_RUNS == upgrade_collect.RESULTS
    assert trial_collect.BOX.joinpath("Dockerfile").is_file()
