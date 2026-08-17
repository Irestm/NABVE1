from __future__ import annotations

import pytest

from modules.crm_transcribe import service_layer


class _FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def transcribe_file(self, path: str, export_txt: bool) -> dict[str, object]:
        self.calls.append((path, export_txt))
        return {"text": "ok"}


def test_transcribe_raises_when_path_missing() -> None:
    with pytest.raises(ValueError, match="path"):
        service_layer.transcribe(_FakeTranscriber(), None, True)


def test_transcribe_raises_when_path_empty() -> None:
    with pytest.raises(ValueError, match="path"):
        service_layer.transcribe(_FakeTranscriber(), "", True)


def test_transcribe_delegates_to_the_transcriber() -> None:
    transcriber = _FakeTranscriber()

    result = service_layer.transcribe(transcriber, "/tmp/call.wav", False)

    assert result == {"text": "ok"}
    assert transcriber.calls == [("/tmp/call.wav", False)]
