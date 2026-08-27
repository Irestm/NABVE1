from __future__ import annotations

import asyncio

import pytest

import core.dispatcher as dispatcher_module
import core.voice.tts as tts


# Regression: core/voice/tts.py's get_assistant_volume/set_assistant_volume
# already existed (used internally by TTS to scale output samples) but had
# no dispatcher command at all — a voice request for "свою"/"личную"
# громкость had nothing to resolve to and fell through to the AI free-text
# fallback, which could answer as if it complied without changing anything.
# These exercise the three handlers added to close that gap.


def _fake_store(monkeypatch: pytest.MonkeyPatch, start: int = 100) -> dict[str, int]:
    state = {"percent": start}
    monkeypatch.setattr(tts, "get_assistant_volume", lambda: state["percent"])

    def fake_set(percent: int) -> None:
        state["percent"] = max(0, min(100, percent))

    monkeypatch.setattr(tts, "set_assistant_volume", fake_set)
    return state


def test_set_assistant_volume_sets_exact_level(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _fake_store(monkeypatch)

    result = asyncio.run(dispatcher_module._handle_set_assistant_volume({"percent": "40"}))

    assert state["percent"] == 40
    assert result["percent"] == 40


def test_set_assistant_volume_requires_percent() -> None:
    with pytest.raises(ValueError):
        asyncio.run(dispatcher_module._handle_set_assistant_volume({}))


def test_change_assistant_volume_is_relative_and_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _fake_store(monkeypatch, start=90)

    result = asyncio.run(dispatcher_module._handle_change_assistant_volume({"delta_percent": "20"}))

    assert state["percent"] == 100
    assert result["percent"] == 100


def test_change_assistant_volume_accepts_negative_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _fake_store(monkeypatch, start=50)

    result = asyncio.run(dispatcher_module._handle_change_assistant_volume({"delta_percent": "-20"}))

    assert state["percent"] == 30
    assert result["percent"] == 30


def test_get_assistant_volume_reports_current_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_store(monkeypatch, start=65)

    result = asyncio.run(dispatcher_module._handle_get_assistant_volume({}))

    assert result["percent"] == 65


def test_assistant_volume_commands_are_registered_and_distinct_from_system_volume() -> None:
    dispatcher = dispatcher_module.build_dispatcher()
    commands = {c.name for c in dispatcher.list_commands()}
    assert {"set_assistant_volume", "change_assistant_volume", "get_assistant_volume"} <= commands
    assert {"set_volume", "change_volume", "get_volume"} <= commands
