from __future__ import annotations

import asyncio

import pytest

import core.voice.pipeline as pipeline_module
from core.dispatcher import CommandDispatcher
from core.voice.intent import Command
from core.voice.pipeline import VoiceAssistantLoop
from modules.board_games import service_layer, ui_session
from modules.board_games.domain import GameKind

# Checkers (not chess) throughout — pure Python (modules.board_games.checkers_adapter
# wraps the draughts library directly), so these tests never need a system
# Stockfish binary, same reasoning as tests/modules/board_games/test_ui_session.py.


@pytest.fixture(autouse=True)
def _reset_current_session() -> None:
    ui_session._current = None
    yield
    if ui_session._current is not None:
        service_layer.finish(ui_session._current)
    ui_session._current = None


def _make_loop() -> VoiceAssistantLoop:
    return VoiceAssistantLoop(CommandDispatcher())


def _run_coro_directly(coro, barge_in, language):
    # Stands in for core.voice.interruption.run_cancellable in tests — see
    # tests/core/voice/test_pipeline_task_plan.py's identical helper.
    return asyncio.run(coro)


def _patch_no_barge_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_cancellable", _run_coro_directly)


def _patch_no_image_push(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    pushed: list[str] = []
    monkeypatch.setattr(pipeline_module.state_manager, "request_image", lambda svg: pushed.append(svg))
    return pushed


def test_resolve_board_game_starts_a_ui_session_game_and_pushes_the_board(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed = _patch_no_image_push(monkeypatch)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="start_board_game", params={"game": "checkers"})
    result, interrupted = loop._resolve_board_game(command, tts=None, command_stt=None, response_language="ru")

    assert result is None
    assert interrupted is False
    assert ui_session.current() is not None
    assert ui_session.current().kind == GameKind.CHECKERS
    assert len(pushed) == 1 and pushed[0].startswith("<svg")
    assert "Начинаем партию в шашки" in spoken[0]


def test_active_game_utterance_returns_none_when_no_game_is_active() -> None:
    loop = _make_loop()

    assert loop._resolve_active_board_game_utterance("пешка е4", "ru") is None


def test_active_game_utterance_recognizes_resign_phrase() -> None:
    ui_session.start(GameKind.CHECKERS)
    loop = _make_loop()

    command = loop._resolve_active_board_game_utterance("я сдаюсь", "ru")

    assert command == Command(name="board_game_resign", params={})


def test_active_game_utterance_resolves_a_move_via_the_ai_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    session = ui_session.start(GameKind.CHECKERS)
    legal = service_layer.legal_move_labels(session)

    async def fake_resolve(_session, spoken_text):
        assert spoken_text == "вон той шашкой вперёд"
        return legal[0]

    monkeypatch.setattr(pipeline_module.board_games_service_layer, "resolve_player_move", fake_resolve)
    loop = _make_loop()

    command = loop._resolve_active_board_game_utterance("вон той шашкой вперёд", "ru")

    assert command == Command(name="board_game_apply_move", params={"notation": legal[0]})


def test_active_game_utterance_falls_through_when_nothing_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_barge_in(monkeypatch)
    ui_session.start(GameKind.CHECKERS)

    async def fake_resolve(_session, _spoken_text):
        return None

    monkeypatch.setattr(pipeline_module.board_games_service_layer, "resolve_player_move", fake_resolve)
    loop = _make_loop()

    assert loop._resolve_active_board_game_utterance("открой браузер", "ru") is None


def test_resolve_board_game_move_applies_the_move_and_lets_the_engine_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed = _patch_no_image_push(monkeypatch)
    session = ui_session.start(GameKind.CHECKERS)
    legal = service_layer.legal_move_labels(session)
    loop = _make_loop()
    spoken: list[str] = []
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: spoken.append(text) or False)

    command = Command(name="board_game_apply_move", params={"notation": legal[0]})
    interrupted = loop._resolve_board_game_move(command, tts=None, response_language="ru")

    assert interrupted is False
    assert ui_session.current() is session  # still the same, ongoing game
    assert len(pushed) == 2  # after the player's move, and after the engine's reply
    assert spoken[0].startswith(f"Вы сыграли {legal[0]}.")
    assert "Хожу:" in spoken[0]


def test_resolve_board_game_move_finishes_the_game_when_the_players_move_ends_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed = _patch_no_image_push(monkeypatch)
    session = ui_session.start(GameKind.CHECKERS)
    loop = _make_loop()
    monkeypatch.setattr(loop, "_speak_safely", lambda tts, text, language: False)

    # Force the "player's move ends the game" branch without playing out a
    # full real game — same technique as
    # tests/modules/board_games/test_checkers_adapter.py's _FakeBoard.
    monkeypatch.setattr(pipeline_module.board_games_service_layer, "apply_player_move", lambda _s, _n: None)
    monkeypatch.setattr(pipeline_module.board_games_service_layer, "is_over", lambda _s: True)

    command = Command(name="board_game_apply_move", params={"notation": "24-19"})
    interrupted = loop._resolve_board_game_move(command, tts=None, response_language="ru")

    assert interrupted is False
    assert ui_session.current() is None  # ui_session.finish() cleared it
    assert len(pushed) == 2  # once for the player's move, once for the final summary board


def test_finish_board_game_resigned_speaks_the_stopped_text_first() -> None:
    ui_session.start(GameKind.CHECKERS)
    loop = _make_loop()
    spoken: list[str] = []
    loop._speak_safely = lambda tts, text, language: spoken.append(text) or False  # type: ignore[method-assign]

    interrupted = loop._finish_board_game(tts=None, response_language="ru", resigned=True)

    assert interrupted is False
    assert ui_session.current() is None
    assert spoken[0].startswith("Партия остановлена.")


def test_finish_board_game_with_no_active_game_is_a_safe_noop() -> None:
    loop = _make_loop()

    assert loop._finish_board_game(tts=None, response_language="ru") is False
