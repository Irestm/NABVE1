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

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
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


def test_pause_is_checked_before_wake_when_both_are_configured(monkeypatch) -> None:
    # Regression: wake_word._listen_for_any walks the phrases dict in
    # insertion order and returns on the first fuzzy match — with "wake"
    # listed first, an utterance containing both the wake phrase and the
    # stop word in the same breath ("привет стоп") always resolved as
    # "wake", so the stop word never paused anything and instead fell
    # through to the AI-classification fallback as ordinary command text.
    # "pause" must be the first key whenever a stop word is configured.
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
    calls = []

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
        calls.append(phrases)
        # First call is the main wait pass (offers "pause"); once paused,
        # _wait_for_wake_or_pause switches to waiting for "resume" instead —
        # answering "pause" again here regardless of what's asked would spin
        # the loop forever, since neither stop_event nor _paused_event would
        # ever clear. Set stop_event once resumed so the loop actually exits
        # after this single pause/resume round-trip rather than looping back
        # into a third listen_for_phrases call.
        if "resume" in phrases:
            stop_event.set()
            return "resume"
        return "pause"

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    loop._wait_for_wake_or_pause(_FakeTTS())

    phrases = calls[0]
    assert list(phrases.keys())[0] == "pause"
    assert phrases["pause"] == ("стоп", "stop")


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

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
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


def test_barge_in_interruption_pauses_instead_of_listening_immediately(monkeypatch) -> None:
    # Regression: _handle_command returning True (BargeInMonitor heard the
    # stop word mid-reply) used to make _run() skip straight back into
    # _handle_command for a new command ("listen immediately"), never
    # requiring the wake word again. It must now pause exactly like
    # _wait_for_wake_or_pause's own "pause" branch: set _paused_event, set
    # AssistantState.PAUSED, and go through _wait_for_wake_or_pause again on
    # the next iteration instead of skipping it.
    loop = _make_loop()
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)

    wait_calls = {"count": 0}

    def fake_wait(tts):
        wait_calls["count"] += 1
        if wait_calls["count"] == 2:
            loop._stop_event.set()
            return False
        return True

    monkeypatch.setattr(loop, "_wait_for_wake_or_pause", fake_wait)
    monkeypatch.setattr(loop, "_handle_command", lambda command_stt, tts: True)

    states = []
    monkeypatch.setattr(
        pipeline_module.state_manager, "set_state", lambda state, detail="": states.append(state)
    )

    loop._run()

    assert wait_calls["count"] == 2  # went through _wait_for_wake_or_pause again, not skipped
    assert loop._paused_event.is_set()
    assert pipeline_module.AssistantState.PAUSED in states


def test_continuous_conversation_handles_several_commands_without_a_new_wake_phrase(monkeypatch) -> None:
    # Found live: the assistant used to end the "conversation" after every
    # single command, requiring the wake phrase again for each follow-up
    # question. One activation should now cover a whole back-to-back
    # exchange - _wait_for_wake_or_pause is only called once here, even
    # though _handle_command runs three times before the loop ends.
    loop = _make_loop()
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)

    wait_calls = {"count": 0}

    def fake_wait(tts):
        wait_calls["count"] += 1
        return True  # only ever "hears" the wake phrase once

    handle_calls = {"count": 0}

    def fake_handle(command_stt, tts):
        handle_calls["count"] += 1
        if handle_calls["count"] == 3:
            loop._stop_event.set()
        return False  # never interrupted/paused

    monkeypatch.setattr(loop, "_wait_for_wake_or_pause", fake_wait)
    monkeypatch.setattr(loop, "_handle_command", fake_handle)

    loop._run()

    assert wait_calls["count"] == 1  # the wake phrase was needed exactly once
    assert handle_calls["count"] == 3  # three commands handled back-to-back


def test_continuous_conversation_stops_and_requires_a_new_wake_phrase_after_a_pause(monkeypatch) -> None:
    # The other half of the same behavior: once a command in the middle of
    # an ongoing conversation sets _paused_event (e.g. the stop word said as
    # an ordinary command, or the "Завершить разговор" button), the inner
    # loop must stop calling _handle_command immediately - not keep going
    # until the next command also happens to be a pause.
    loop = _make_loop()
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)

    wait_calls = {"count": 0}

    def fake_wait(tts):
        wait_calls["count"] += 1
        if wait_calls["count"] == 2:
            loop._stop_event.set()
        return True

    handle_calls = {"count": 0}

    def fake_handle(command_stt, tts):
        handle_calls["count"] += 1
        if handle_calls["count"] == 2:
            loop._paused_event.set()
        return False

    monkeypatch.setattr(loop, "_wait_for_wake_or_pause", fake_wait)
    monkeypatch.setattr(loop, "_handle_command", fake_handle)

    loop._run()

    assert handle_calls["count"] == 2  # stopped right after _paused_event was set, no third call
    assert wait_calls["count"] == 2  # went back through _wait_for_wake_or_pause for the next activation


def test_continuous_conversation_ends_on_a_hard_error_instead_of_retrying_tightly(monkeypatch) -> None:
    # An exception from _handle_command must send this back to
    # _wait_for_wake_or_pause (which does have a blocking mic wait) rather
    # than retrying _handle_command again immediately - a persistently
    # broken _handle_command would otherwise spin with no blocking wait at
    # all in between attempts.
    loop = _make_loop()
    monkeypatch.setattr(pipeline_module, "SpeechToText", lambda settings: object())
    monkeypatch.setattr(pipeline_module, "TextToSpeech", lambda settings: object())
    monkeypatch.setattr(loop, "_run_onboarding_if_needed", lambda: None)

    wait_calls = {"count": 0}

    def fake_wait(tts):
        wait_calls["count"] += 1
        if wait_calls["count"] == 2:
            loop._stop_event.set()
        return True

    handle_calls = {"count": 0}

    def fake_handle(command_stt, tts):
        handle_calls["count"] += 1
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(loop, "_wait_for_wake_or_pause", fake_wait)
    monkeypatch.setattr(loop, "_handle_command", fake_handle)

    loop._run()

    assert handle_calls["count"] == 1  # one failed attempt, not a tight retry loop
    assert wait_calls["count"] == 2


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

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
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
        lambda settings, phrases, stop_event, *, model_size=None, extra_stop_event=None: listen_for_phrases_calls.append(
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
    assert listen_for_phrases_calls[1][0]["pause"] == ("стоп", "stop")
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
        lambda settings, phrases, stop_event, *, model_size=None, extra_stop_event=None: (
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


def test_request_manual_wake_returns_false_when_loop_is_not_running() -> None:
    loop = _make_loop()

    assert loop.request_manual_wake() is False
    assert not loop._manual_trigger_event.is_set()


def test_request_manual_wake_sets_the_event_when_loop_is_running(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(VoiceAssistantLoop, "is_running", property(lambda self: True))

    assert loop.request_manual_wake() is True
    assert loop._manual_trigger_event.is_set()


def test_request_pause_returns_false_when_loop_is_not_running() -> None:
    loop = _make_loop()

    assert loop.request_pause() is False
    assert not loop._paused_event.is_set()


def test_request_pause_sets_paused_event_and_state_when_loop_is_running(monkeypatch) -> None:
    loop = _make_loop()
    monkeypatch.setattr(VoiceAssistantLoop, "is_running", property(lambda self: True))
    states = []
    monkeypatch.setattr(
        pipeline_module.state_manager, "set_state", lambda state, detail="": states.append((state, detail))
    )

    assert loop.request_pause() is True
    assert loop._paused_event.is_set()
    assert states == [(pipeline_module.AssistantState.PAUSED, "Скажите стоп-слово ещё раз, чтобы продолжить")]
    # Also forces any currently-blocked listen_for_phrases call to return,
    # so the pause takes effect immediately instead of only whenever that
    # call happens to end on its own - see _wait_for_wake_or_pause's
    # top-of-loop disambiguation (_paused_event still set when this fires
    # means "just re-sync", not "start a turn").
    assert loop._manual_trigger_event.is_set()


def test_manual_trigger_while_idle_starts_a_turn_without_a_spoken_wake_phrase(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch)
    loop._manual_trigger_event.set()

    # extra_stop_event firing looks like an ordinary "nothing heard" return
    # from listen_for_phrases's point of view - it can't tell the caller
    # *why* it returned None, so the fake mirrors that instead of returning
    # some sentinel wake_word itself never actually returns.
    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: None)

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert not loop._manual_trigger_event.is_set()


def test_manual_trigger_is_forwarded_as_extra_stop_event(monkeypatch) -> None:
    loop = _make_loop()
    _mock_facts(monkeypatch)
    seen = []

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
        seen.append(extra_stop_event)
        return "wake"

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    loop._wait_for_wake_or_pause(_FakeTTS())

    assert seen == [loop._manual_trigger_event]


def test_manual_trigger_while_paused_unpauses_and_starts_a_turn_immediately(monkeypatch) -> None:
    # Deliberately different from the voice "resume" phrase (see
    # test_pause_then_resume_then_wake), which only unpauses and still
    # requires the wake word afterward - the button is meant to reliably
    # start listening on a single press. Goes through the real
    # request_manual_wake() (not raw Event manipulation) since it's what
    # actually clears _paused_event before setting the trigger - that
    # ordering is exactly what tells _wait_for_wake_or_pause this is a
    # genuine start request, not request_pause()'s own interrupt-only use
    # of the same event (see the next test).
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
    monkeypatch.setattr(VoiceAssistantLoop, "is_running", property(lambda self: True))
    loop._paused_event.set()
    loop.request_manual_wake()

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", lambda *a, **k: None)

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is True
    assert not loop._paused_event.is_set()
    assert not loop._manual_trigger_event.is_set()


def test_manual_trigger_from_pause_while_idle_transitions_to_paused_branch_instead_of_starting_a_turn(
    monkeypatch,
) -> None:
    # Regression, found live: request_pause() sets _manual_trigger_event
    # purely to interrupt a blocking idle-branch listen so the pause takes
    # effect right away - it must NOT be mistaken for a genuine
    # request_manual_wake() and start a turn instead of actually pausing.
    # _paused_event still being set when the trigger fires is exactly what
    # tells the two apart.
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
    monkeypatch.setattr(VoiceAssistantLoop, "is_running", property(lambda self: True))
    loop.request_pause()  # sets _paused_event AND _manual_trigger_event

    # First call (now genuinely inside the paused branch): nothing heard
    # yet. Second call: "resume" - also stops the loop so the test doesn't
    # need a third call to end deterministically.
    responses = iter([None, "resume"])

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
        result = next(responses)
        if result == "resume":
            loop._stop_event.set()
        return result

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    result = loop._wait_for_wake_or_pause(_FakeTTS())

    assert result is False  # stop_event fired after a real "resume" - never mistaken for a turn start
    assert not loop._paused_event.is_set()


def test_paused_branch_reasserts_paused_state_on_every_pass(monkeypatch) -> None:
    # Regression, found via live testing: a pause requested while a command
    # turn was still in flight left /api/status showing whatever state that
    # turn's own later updates landed on (processing/thinking/idle/...),
    # since PAUSED had only ever been broadcast once, at the moment the
    # pause was first requested - by the time the loop actually reached this
    # branch to really wait for the resume phrase, nothing re-asserted it.
    loop = _make_loop()
    _mock_facts(monkeypatch, stop_word="стоп")
    loop._paused_event.set()
    states = []
    monkeypatch.setattr(
        pipeline_module.state_manager, "set_state", lambda state, detail="": states.append(state)
    )

    # First pass: nothing heard yet, stays paused (loops back into this same
    # branch). Second pass: "resume" heard - also sets stop_event so the
    # outer while exits right after, instead of falling through to the
    # unpaused branch and blocking on a third listen_for_phrases call.
    responses = iter([None, "resume"])

    def fake_listen_for_phrases(settings, phrases, stop_event, *, model_size=None, extra_stop_event=None):
        result = next(responses)
        if result == "resume":
            loop._stop_event.set()
        return result

    monkeypatch.setattr(pipeline_module.wake_word, "listen_for_phrases", fake_listen_for_phrases)

    loop._wait_for_wake_or_pause(_FakeTTS())

    paused_count = states.count(pipeline_module.AssistantState.PAUSED)
    assert paused_count == 2  # asserted again on the second pass, not just the first


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
