from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from modules.meeting_recorder import audio_processing


def _fake_which(name_to_path: dict[str, str]):
    def which(name: str) -> str | None:
        return name_to_path.get(name)

    return which


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_find_binary_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({}))
    with pytest.raises(RuntimeError, match="ffmpeg"):
        audio_processing._find_binary("ffmpeg")


def test_convert_to_ogg_succeeds_on_first_loudnorm_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({"ffmpeg": "/usr/bin/ffmpeg"}))
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed(0)

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    audio_processing.convert_to_ogg(Path("in.webm"), Path("out.ogg"))

    assert len(calls) == 1
    assert "-af" in calls[0] and "loudnorm" in calls[0]


def test_convert_to_ogg_falls_back_to_plain_reencode_when_loudnorm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({"ffmpeg": "/usr/bin/ffmpeg"}))
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        # First call (loudnorm) fails, second (plain re-encode) succeeds.
        return _completed(1 if len(calls) == 1 else 0)

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    audio_processing.convert_to_ogg(Path("in.webm"), Path("out.ogg"))

    assert len(calls) == 2
    assert "loudnorm" in calls[0]
    assert "loudnorm" not in calls[1]


def test_convert_to_ogg_raises_when_both_passes_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({"ffmpeg": "/usr/bin/ffmpeg"}))
    monkeypatch.setattr(
        audio_processing.subprocess, "run", lambda args, **kwargs: _completed(1, stderr="broken input")
    )

    with pytest.raises(RuntimeError, match="ffmpeg conversion failed"):
        audio_processing.convert_to_ogg(Path("in.webm"), Path("out.ogg"))


def test_run_wraps_timeout_expired_as_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(audio_processing.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="did not finish within"):
        audio_processing._run(["ffmpeg"], timeout_seconds=1)


def test_probe_duration_seconds_parses_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({"ffprobe": "/usr/bin/ffprobe"}))
    monkeypatch.setattr(audio_processing.subprocess, "run", lambda args, **kwargs: _completed(0, stdout="123.45\n"))

    assert audio_processing.probe_duration_seconds(Path("audio.ogg")) == pytest.approx(123.45)


def test_probe_duration_seconds_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({"ffprobe": "/usr/bin/ffprobe"}))
    monkeypatch.setattr(
        audio_processing.subprocess, "run", lambda args, **kwargs: _completed(1, stderr="no such file")
    )

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        audio_processing.probe_duration_seconds(Path("audio.ogg"))


def test_probe_duration_seconds_raises_on_unparseable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_processing.shutil, "which", _fake_which({"ffprobe": "/usr/bin/ffprobe"}))
    monkeypatch.setattr(audio_processing.subprocess, "run", lambda args, **kwargs: _completed(0, stdout="N/A"))

    with pytest.raises(RuntimeError, match="unparseable duration"):
        audio_processing.probe_duration_seconds(Path("audio.ogg"))
