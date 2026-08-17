from __future__ import annotations

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.pipeline import VoiceAssistantLoop


class _FakeTTS:
    def synthesize(self, text, language):
        raise AssertionError("synthesize should not be called in these tests")


def _make_loop() -> VoiceAssistantLoop:
    return VoiceAssistantLoop(CommandDispatcher())


def _mock_facts(
    monkeypatch,
    *,
    stop_word: str | None = None,
    hide_phrase: str | None = None,
    show_phrase: str | None = None,
    wake_phrase: str | None = None,
) -> None:
    from modules.tray_hide.config import HIDE_PHRASE_KEY, SHOW_PHRASE_KEY
    from modules.user_profile.domain import STOP_WORD_KEY, WAKE_PHRASE_KEY

    values = {
        STOP_WORD_KEY: stop_word,
        HIDE_PHRASE_KEY: hide_phrase,
        SHOW_PHRASE_KEY: show_phrase,
        WAKE_PHRASE_KEY: wake_phrase,
    }
    monkeypatch.setattr(pipeline_module.profile_service_layer, "get_fact", lambda uow, key: values.get(key))


def test_wake_word_and_tray_phrases_are_always_checked_in_one_pass(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch)
    calls = []

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None):
        calls.append(phrases)
        return "wake"

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert len(calls) == 1
    phrases = calls[0]
    assert phrases["wake"] == pipeline_module.wake_word.resolve_wake_phrases(loop._settings, None)
    assert "pause" not in phrases  # no stop word configured
    assert "tray_hide" in phrases and "tray_show" in phrases


def test_background_listening_state_is_set_while_waiting(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch)
    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: "wake")

    states = []
    monkeypatch.setattr(
        pipeline_module.state_manager, "set_state", lambda state, detail="": states.append(state)
    )

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert pipeline_module.AssistantState.BACKGROUND_LISTENING in states


def test_custom_wake_phrase_is_folded_into_the_wake_phrase_tuple(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch, wake_phrase="джарвис проснись")
    calls = []

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None):
        calls.append(phrases)
        return "wake"

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert "джарвис проснись" in calls[0]["wake"]
    # Defaults must still be present alongside the custom phrase.
    assert set(pipeline_module.wake_word.DEFAULT_WAKE_PHRASES) <= set(calls[0]["wake"])


def test_returns_false_immediately_if_already_stopped(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
    loop._stop_event.set()

    assert loop._wait_for_wake_or_pause(_FakeTTS()) is False


def test_run_survives_a_transient_wake_word_failure_and_keeps_looping(monkeypatch) -> None:
    """Regression: an exception from _wait_for_wake_or_pause used to set
    state ERROR and `return` from _run entirely — permanently killing the
    voice loop's thread, with nothing to restart it — unlike the identical
    category of transient failure in _handle_command a few lines below,
    which already just logs and keeps going. Reproduces a wake-word
    failure on the first pass and asserts the loop survives it and retries,
    instead of exiting for good."""
    loop = _make_loop()
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)

    calls = {"count": 0}

    def fake_wait(tts):
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
    # {"wake": ..., "tray_hide": ..., "tray_show": ..., "pause": "стоп"} ->
    # heard "pause"; second call (now paused) checks {"resume": "стоп"} ->
    # heard "resume"; third call is back to checking wake+pause -> heard
    # "wake".
    _mock_facts(monkeypatch, stop_word="стоп")
    responses = iter(["pause", "resume", "wake"])
    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: next(responses))

    loop = _make_loop()
    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert not loop._paused_event.is_set()


def test_paused_event_is_actually_set_while_waiting_for_the_resume_phrase(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
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

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert observed_paused_mid_sequence == [True]


def test_paused_with_no_stop_word_self_clears(monkeypatch) -> None:
    loop = _make_loop()
    loop._paused_event.set()
    _mock_facts(monkeypatch)
    calls = []
    monkeypatch.setattr(
        pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: calls.append(1) or "wake"
    )

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert not loop._paused_event.is_set()
    assert calls == [1]  # no stop word to resume on -> falls through to the normal wake/tray pass


def test_stop_word_set_while_running_takes_effect_without_restart(monkeypatch) -> None:
    # Regression: the stop word used to be read once when the voice thread
    # started (in _run(), before this loop existed), so saving one for the
    # first time via the personality settings panel (profile_set) while the
    # assistant was already running had no effect at all until a full
    # restart. It must now be picked up on the very next listening pass.
    loop = _make_loop()
    from modules.tray_hide.config import HIDE_PHRASE_KEY, SHOW_PHRASE_KEY
    from modules.user_profile.domain import STOP_WORD_KEY, WAKE_PHRASE_KEY

    stop_word_values = iter([None, "стоп"])

    def fake_get_fact(uow, key):
        if key == STOP_WORD_KEY:
            return next(stop_word_values)
        assert key in (HIDE_PHRASE_KEY, SHOW_PHRASE_KEY, WAKE_PHRASE_KEY)
        return None

    monkeypatch.setattr(pipeline_module.profile_service_layer, "get_fact", fake_get_fact)
    listen_for_phrases_calls: list[tuple[dict, str | None]] = []
    monkeypatch.setattr(
        pipeline_module.wake_word,
        "listen_for_phrases",
        lambda settings, phrases, stop_event, *, model_size=None: listen_for_phrases_calls.append(
            (phrases, model_size)
        )
        or "wake",
    )

    # First pass: no stop word configured yet -> "pause" is absent from the
    # phrases dict, but wake/tray_hide/tray_show are still checked in the
    # same STT pass (there is no fast path anymore).
    first_result = loop._wait_for_wake_or_pause(_FakeTTS())
    assert first_result is True
    assert len(listen_for_phrases_calls) == 1
    assert "pause" not in listen_for_phrases_calls[0][0]

    # Second pass: stop word now configured, no restart in between - must be
    # picked up immediately.
    second_result = loop._wait_for_wake_or_pause(_FakeTTS())
    assert second_result is True
    assert len(listen_for_phrases_calls) == 2
    assert listen_for_phrases_calls[1][0]["pause"] == "стоп"
    assert listen_for_phrases_calls[1][1] == loop._settings.whisper_model_size


def test_pause_and_resume_use_command_tier_model_not_wake_tier(monkeypatch) -> None:
    # Regression: the stop word/pause phrase used to be listened for with
    # settings.whisper_wake_model_size (the fast "tiny" tier, same as the
    # fixed wake word) - fine for a short, common, well-enunciated wake
    # word, but a user's own arbitrary stop word has no such guarantee and
    # was routinely missed. Both the "waiting to pause" and "waiting to
    # resume" listens must now ask for the bigger command tier instead.
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
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

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert model_sizes_seen == [loop._settings.whisper_model_size] * 3


def test_tray_hide_phrase_speaks_ack_and_requests_hide(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch)
    responses = iter(["tray_hide", "wake"])
    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: next(responses))

    spoken = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    hide_calls = []
    monkeypatch.setattr(
        pipeline_module.ui_control_service_layer, "hide_window", lambda state: hide_calls.append(state)
    )

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert len(spoken) == 1  # spoke the ack before requesting the hide
    assert len(hide_calls) == 1


def test_tray_show_phrase_speaks_ack_and_requests_show(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch)
    responses = iter(["tray_show", "wake"])
    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: next(responses))

    spoken = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    show_calls = []
    monkeypatch.setattr(
        pipeline_module.ui_control_service_layer, "show_window", lambda state: show_calls.append(state)
    )

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert len(spoken) == 1
    assert len(show_calls) == 1
