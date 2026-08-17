from __future__ import annotations

import pytest

from modules.crm_transcribe import transcriber
from core.voice.stt import TranscriptionResult


class _FakeSTT:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def transcribe(self, _audio: object, _language: str | None = None) -> TranscriptionResult:
        return TranscriptionResult(text="привет", detected_language="ru", language_probability=0.98)


def test_transcribe_file_raises_for_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe_file(str(tmp_path / "does-not-exist.wav"))


def test_transcribe_file_returns_text_and_language(tmp_path, monkeypatch) -> None:
    audio_file = tmp_path / "call.wav"
    audio_file.write_bytes(b"fake-audio-bytes")
    monkeypatch.setattr(transcriber, "decode_audio_file", lambda path: object())
    monkeypatch.setattr(transcriber, "SpeechToText", _FakeSTT)

    result = transcriber.transcribe_file(str(audio_file), export_txt=False)

    assert result["text"] == "привет"
    assert result["language"] == "ru"
    assert result["language_probability"] == 0.98
    assert result["txt_path"] is None


def test_transcribe_file_exports_txt_file_next_to_the_audio(tmp_path, monkeypatch) -> None:
    audio_file = tmp_path / "call.wav"
    audio_file.write_bytes(b"fake-audio-bytes")
    monkeypatch.setattr(transcriber, "decode_audio_file", lambda path: object())
    monkeypatch.setattr(transcriber, "SpeechToText", _FakeSTT)

    result = transcriber.transcribe_file(str(audio_file), export_txt=True)

    txt_file = tmp_path / "call.txt"
    assert result["txt_path"] == str(txt_file)
    assert txt_file.read_text(encoding="utf-8") == "привет"


def test_local_whisper_transcriber_delegates_to_transcribe_file(tmp_path, monkeypatch) -> None:
    audio_file = tmp_path / "call.wav"
    audio_file.write_bytes(b"fake-audio-bytes")
    monkeypatch.setattr(transcriber, "decode_audio_file", lambda path: object())
    monkeypatch.setattr(transcriber, "SpeechToText", _FakeSTT)

    result = transcriber.LocalWhisperTranscriber.transcribe_file(str(audio_file), export_txt=False)

    assert result["text"] == "привет"
