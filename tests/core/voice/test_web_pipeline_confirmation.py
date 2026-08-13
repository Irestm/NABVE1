from __future__ import annotations

import numpy as np

import core.voice.web_pipeline as web_pipeline
from core.dispatcher import CommandDispatcher
from core.voice.stt import TranscriptionResult


def _make_dangerous_dispatcher() -> tuple[CommandDispatcher, list[str]]:
    executed: list[str] = []

    async def handler(_params: dict) -> dict:
        executed.append("shutdown")
        return {}

    dispatcher = CommandDispatcher()
    dispatcher.register("shutdown", handler, dangerous=True, description="")
    return dispatcher, executed


def _mock_audio_pipeline(monkeypatch, spoken_text: str) -> None:
    monkeypatch.setattr(web_pipeline, "_decode_uploaded_audio", lambda data, suffix: np.ones(1, dtype=np.float32))
    monkeypatch.setattr(
        web_pipeline._stt,
        "transcribe",
        lambda audio, language=None: TranscriptionResult(
            text=spoken_text, detected_language="ru", language_probability=0.99
        ),
    )
    monkeypatch.setattr(web_pipeline, "synthesize_speech", lambda text, language, speaker=None: None)


async def _dispatch_and_get_token(dispatcher: CommandDispatcher) -> str:
    response = await dispatcher.dispatch("shutdown", {})
    assert response.token is not None
    return response.token


def test_voice_confirmation_with_affirmative_answer_executes_the_command(monkeypatch) -> None:
    dispatcher, executed = _make_dangerous_dispatcher()
    _mock_audio_pipeline(monkeypatch, "да")

    import asyncio

    async def run() -> None:
        token = await _dispatch_and_get_token(dispatcher)
        result = await web_pipeline.process_voice_confirmation(dispatcher, b"fake", "confirm.webm", token)
        assert result.status == "executed"

    asyncio.run(run())
    assert executed == ["shutdown"]


def test_voice_confirmation_with_negative_answer_cancels_without_executing(monkeypatch) -> None:
    dispatcher, executed = _make_dangerous_dispatcher()
    _mock_audio_pipeline(monkeypatch, "нет отмена")

    import asyncio

    async def run() -> None:
        token = await _dispatch_and_get_token(dispatcher)
        result = await web_pipeline.process_voice_confirmation(dispatcher, b"fake", "confirm.webm", token)
        assert result.status == "cancelled"

    asyncio.run(run())
    assert executed == []
