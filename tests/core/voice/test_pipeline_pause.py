from __future__ import annotations

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.pipeline import VoiceAssistantLoop


class _FakeWakeDetector:
    def __init__(self, result: bool) -> None:
        self._result = result

    def listen(self, stop_event) -> bool:
        return self._result


def _make_loop() -> VoiceAssistantLoop:
    return VoiceAssistantLoop(CommandDispatcher())


def _mock_stop_word(monkeypatch, value: str | None) -> None:
    monkeypatch.setattr(pipeline_module.profile_service_layer, "get_fact", lambda uow, key: value)


def test_uses_plain_wake_detector_when_no_stop_word_configured(monkeypatch) -> None:
    loop = _make_loop()
    _mock_stop_word(monkeypatch, None)
    calls = []
    monkeypatch.setattr(
        pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: calls.append(1) or None
    )

    result = loop._wait_for_wake_or_pause(_FakeWakeDetector(True))

    assert result is True
    assert calls == []  # listen_for_phrases must not be used at all in this mode


def test_returns_false_immediately_if_already_stopped(monkeypatch) -> None:
    loop = _make_loop()
    _mock_stop_word(monkeypatch, "стоп")
    loop._stop_event.set()

    assert loop._wait_for_wake_or_pause(_FakeWakeDetector(True)) is False


def test_run_survives_a_transient_wake_word_failure_and_keeps_looping(monkeypatch) -> None:
    """Regression: an exception from _wait_for_wake_or_pause used to set
    state ERROR and `return` from _run entirely — permanently killing the
    voice loop's thread, with nothing to restart it — unlike the identical
    category of transient failure in _handle_command a few lines below,
    which already just logs and keeps looping. Reproduces a wake-word
    failure on the first pass and asserts the loop survives it and retries,
    instead of exiting for good."""
    loop = _make_loop()
    monkeypatch.setattr(pipeline_module, "get_wake_word_detector", lambda settings: _FakeWakeDetector(True))
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)

    calls = {"count": 0}

    def fake_wait(wake_detector):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated transient failure")
        loop._stop_event.set()
        return False

    monkeypatch.setattr(loop, "_wait_for_wake_or_pause", fake_wait)

    loop._run()

    assert calls["count"] == 2  # survived the first failure and retried instead of returning


def test_pause_then_resume_then_wake(monkeypatch) -> None:
    # Sequence the real code produces for stop_word="стоп": first call checks
    # {"wake": ..., "pause": "стоп"} -> heard "pause"; second call (now
    # paused) checks {"resume": "стоп"} -> heard "resume"; third call is
    # back to checking wake+pause -> heard "wake".
    _mock_stop_word(monkeypatch, "стоп")
    responses = iter(["pause", "resume", "wake"])
    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: next(responses))

    loop = _make_loop()
    result = loop._wait_for_wake_or_pause(_FakeWakeDetector(False))

    assert result is True
    assert not loop._paused_event.is_set()


def test_paused_event_is_actually_set_while_waiting_for_the_resume_phrase(monkeypatch) -> None:
    loop = _make_loop()
    _mock_stop_word(monkeypatch, "стоп")
    observed_paused_mid_sequence: list[bool] = []
    call_count = {"n": 0}

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None):
        call_count["n"] += 1
        if "resume" in phrases:
            # This call only ever happens while paused - check it from the
            # inside, since _wait_for_wake_or_pause blocks until it returns
            # and there's no other way to observe the intermediate state.
            observed_paused_mid_sequence.append(loop._paused_event.is_set())
            return "resume"
        return "pause" if call_count["n"] == 1 else "wake"

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    result = loop._wait_for_wake_or_pause(_FakeWakeDetector(False))

    assert result is True
    assert observed_paused_mid_sequence == [True]


def test_paused_with_no_stop_word_self_clears(monkeypatch) -> None:
    loop = _make_loop()
    loop._paused_event.set()
    _mock_stop_word(monkeypatch, None)
    calls = []
    monkeypatch.setattr(
        pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: calls.append(1) or None
    )

    result = loop._wait_for_wake_or_pause(_FakeWakeDetector(True))

    assert result is True
    assert not loop._paused_event.is_set()
    assert calls == []


def test_stop_word_set_while_running_takes_effect_without_restart(monkeypatch) -> None:
    # Regression: the stop word used to be read once when the voice thread
    # started (in _run(), before this loop existed), so saving one for the
    # first time via the personality settings panel (profile_set) while the
    # assistant was already running had no effect at all until a full
    # restart. It must now be picked up on the very next listening pass.
    loop = _make_loop()
    stop_word_values = iter([None, "стоп"])
    monkeypatch.setattr(
        pipeline_module.profile_service_layer, "get_fact", lambda uow, key: next(stop_word_values)
    )
    listen_for_phrases_calls: list[tuple[dict[str, str], str | None]] = []
    monkeypatch.setattr(
        pipeline_module.wake_word,
        "listen_for_phrases",
        lambda settings, phrases, stop_event, *, model_size=None: listen_for_phrases_calls.append(
            (phrases, model_size)
        )
        or "wake",
    )

    # First pass: no stop word configured yet -> goes straight to the plain
    # wake detector, never touches listen_for_phrases.
    first_result = loop._wait_for_wake_or_pause(_FakeWakeDetector(True))
    assert first_result is True
    assert listen_for_phrases_calls == []

    # Second pass: stop word now configured, no restart in between - must be
    # picked up immediately.
    second_result = loop._wait_for_wake_or_pause(_FakeWakeDetector(True))
    assert second_result is True
    assert listen_for_phrases_calls == [
        ({"wake": loop._settings.wake_word, "pause": "стоп"}, loop._settings.whisper_model_size)
    ]


def test_pause_and_resume_use_command_tier_model_not_wake_tier(monkeypatch) -> None:
    # Regression: the stop word/pause phrase used to be listened for with
    # settings.whisper_wake_model_size (the fast "tiny" tier, same as the
    # fixed wake word) - fine for a short, common, well-enunciated wake
    # word, but a user's own arbitrary stop word has no such guarantee and
    # was routinely missed. Both the "waiting to pause" and "waiting to
    # resume" listens must now ask for the bigger command tier instead.
    loop = _make_loop()
    _mock_stop_word(monkeypatch, "стоп")
    assert loop._settings.whisper_model_size != loop._settings.whisper_wake_model_size

    model_sizes_seen: list[str | None] = []
    responses = iter(["pause", "resume", "wake"])
    monkeypatch.setattr(
        pipeline_module.wake_word,
        "listen_for_phrases",
        lambda settings, phrases, stop_event, *, model_size=None: (
            model_sizes_seen.append(model_size) or next(responses)
        ),
    )

    result = loop._wait_for_wake_or_pause(_FakeWakeDetector(False))

    assert result is True
    assert model_sizes_seen == [loop._settings.whisper_model_size] * 3
