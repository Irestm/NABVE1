from __future__ import annotations

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop


def _make_loop() -> VoiceAssistantLoop:
    return VoiceAssistantLoop(CommandDispatcher())


def test_resolve_media_target_corrects_a_named_query_before_building_the_search_url(monkeypatch) -> None:
    # Regression: "открой видео дед селс" used to build a YouTube search URL
    # straight from the raw, garbled STT text, which usually found nothing
    # (or the wrong thing) on the first try - see modules.media.query_correction.
    loop = _make_loop()
    command = Command(name="open_media", params={"kind": "video", "query": "дед селс"})

    async def fake_correct_query(query: str) -> str:
        assert query == "дед селс"
        return "Dead Cells"

    monkeypatch.setattr(pipeline_module.media_query_correction, "correct_query", fake_correct_query)
    captured_urls: list[str] = []
    monkeypatch.setattr(
        pipeline_module.media_youtube, "build_search_url", lambda q: captured_urls.append(q) or f"url:{q}"
    )

    resolved, interrupted = loop._resolve_media_target(command, command_stt=None, tts=None, response_language="ru")

    assert interrupted is False
    assert resolved.params["target"] == "url:Dead Cells"
    assert captured_urls == ["Dead Cells"]


def test_resolve_media_target_skips_correction_for_the_mood_flow(monkeypatch) -> None:
    # A bare "включи музыку" (no named query) is turned into a search query
    # by modules.media.recommender's own AI call, which already returns a
    # clean, correct query - running it through correct_query again would
    # just be a wasted extra AI call.
    loop = _make_loop()
    command = Command(name="open_media", params={"kind": "music", "query": ""})

    def fail_if_called(query: str):
        raise AssertionError("correct_query must not be called for the mood-recommendation flow")

    monkeypatch.setattr(pipeline_module.media_query_correction, "correct_query", fail_if_called)
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)
    monkeypatch.setattr(
        pipeline_module.audio_io, "record_until_silence", lambda settings, stop_event: object()
    )

    class _FakeSTT:
        def transcribe(self, audio):
            class _Result:
                text = "грустное"

            return _Result()

    async def fake_recommend(kind, mood):
        return "sad piano music"

    monkeypatch.setattr(pipeline_module.media_recommender, "recommend", fake_recommend)
    monkeypatch.setattr(
        pipeline_module.media_youtube, "build_search_url", lambda q: f"url:{q}"
    )

    resolved, interrupted = loop._resolve_media_target(
        command, command_stt=_FakeSTT(), tts=None, response_language="ru"
    )

    assert interrupted is False
    assert resolved.params["target"] == "url:sad piano music"
