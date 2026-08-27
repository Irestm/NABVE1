from __future__ import annotations

import threading

from modules.user_profile.onboarding import _MANUAL_SETUP_NOTE, _mention_manual_setup

# Onboarding used to also ask for the assistant's own name, preview every
# Silero voice out loud, and ask for a stop word - dropped in favor of
# _mention_manual_setup, a single line pointing at Настройки/Профиль
# instead. Regression coverage: onboarding must not try to record or
# match an answer for any of that anymore, just speak the note (or stay
# silent once already stopped, like every other onboarding step).


class _FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[tuple[str, str]] = []

    def speak(self, text: str, language: str, **kwargs: object) -> None:
        self.spoken.append((text, language))


def test_mention_manual_setup_speaks_the_note_in_requested_language() -> None:
    tts = _FakeTTS()
    _mention_manual_setup(tts, threading.Event(), "ru")
    assert tts.spoken == [(_MANUAL_SETUP_NOTE["ru"], "ru")]


def test_mention_manual_setup_falls_back_to_russian_for_unknown_language() -> None:
    tts = _FakeTTS()
    _mention_manual_setup(tts, threading.Event(), "fr")
    assert tts.spoken == [(_MANUAL_SETUP_NOTE["ru"], "fr")]


def test_mention_manual_setup_says_nothing_once_stop_event_is_set() -> None:
    tts = _FakeTTS()
    stop_event = threading.Event()
    stop_event.set()
    _mention_manual_setup(tts, stop_event, "ru")
    assert tts.spoken == []
