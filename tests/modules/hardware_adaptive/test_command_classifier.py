from __future__ import annotations

import pytest

from modules.hardware_adaptive import command_classifier as cc


def test_extract_set_volume_parses_and_clamps() -> None:
    assert cc._extract_set_volume("поставь громкость 50 процентов") == {"percent": "50"}
    assert cc._extract_set_volume("поставь громкость 500") == {"percent": "100"}
    assert cc._extract_set_volume("поставь громкость -10") == {"percent": "0"}


def test_extract_set_volume_returns_none_without_a_number() -> None:
    assert cc._extract_set_volume("поставь громкость") is None


def test_extract_change_volume_detects_decrease_word() -> None:
    assert cc._extract_change_volume("убавь громкость на 20 процентов") == {"delta_percent": "-20"}


def test_extract_change_volume_detects_increase_word() -> None:
    assert cc._extract_change_volume("прибавь громкость на 10") == {"delta_percent": "10"}


def test_extract_change_volume_uses_default_step_without_a_number() -> None:
    assert cc._extract_change_volume("сделай погромче") == {"delta_percent": str(cc._DEFAULT_VOLUME_STEP)}
    assert cc._extract_change_volume("сделай потише") == {"delta_percent": str(-cc._DEFAULT_VOLUME_STEP)}


def test_extract_change_volume_respects_explicit_negative_number() -> None:
    assert cc._extract_change_volume("измени громкость на -15") == {"delta_percent": "-15"}


def test_extract_minimize_window_with_app_name() -> None:
    assert cc._extract_minimize_window("сверни окно спотифай") == {"app_name": "спотифай"}


def test_extract_minimize_window_without_app_name_falls_back_to_active_window() -> None:
    assert cc._extract_minimize_window("сверни окно") == {}
    assert cc._extract_minimize_window("minimize this window") == {}


def test_extract_close_os_window_with_app_name() -> None:
    assert cc._extract_close_os_window("закрой окно браузера") == {"app_name": "браузера"}


def test_extract_create_folder_parses_path() -> None:
    assert cc._extract_create_folder("создай папку /home/user/notes") == {"path": "/home/user/notes"}


def test_extract_create_folder_returns_none_without_a_path() -> None:
    assert cc._extract_create_folder("создай папку") is None


def test_extract_delete_folder_parses_path() -> None:
    assert cc._extract_delete_folder("удали папку /home/user/temp") == {"path": "/home/user/temp"}


def test_extract_move_folder_parses_source_and_destination() -> None:
    result = cc._extract_move_folder("перемести /home/a в /home/b")
    assert result == {"source": "/home/a", "destination": "/home/b"}


def test_extract_move_folder_returns_none_when_incomplete() -> None:
    assert cc._extract_move_folder("перемести куда-то") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("смени раскладку на английскую", {"language_code": "en"}),
        ("поставь русскую раскладку", {"language_code": "ru"}),
        ("зміни мову на українську", {"language_code": "uk"}),
        ("change keyboard layout to english", {"language_code": "en"}),
    ],
)
def test_extract_language_code_recognizes_known_languages(text: str, expected: dict) -> None:
    assert cc._extract_language_code(text) == expected


def test_extract_language_code_returns_none_for_unrecognized_language() -> None:
    assert cc._extract_language_code("смени раскладку клавиатуры") is None


def test_match_system_command_returns_none_for_empty_text() -> None:
    assert cc.match_system_command("   ") is None


def test_match_system_command_returns_none_when_classifier_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_ensure_initialized", lambda: False)

    assert cc.match_system_command("поставь громкость 50") is None


def test_match_system_command_matches_best_scoring_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_ensure_initialized", lambda: True)
    monkeypatch.setattr(cc._matcher, "best_match", lambda query: ("set_volume", 0.95))

    result = cc.match_system_command("поставь громкость 60")

    assert result is not None
    assert result.name == "set_volume"
    assert result.params == {"percent": "60"}


def test_match_system_command_returns_none_below_similarity_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_ensure_initialized", lambda: True)
    monkeypatch.setattr(cc._matcher, "best_match", lambda query: ("set_volume", 0.5))

    assert cc.match_system_command("что-то совсем нерелевантное") is None


def test_match_system_command_returns_none_when_extractor_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_ensure_initialized", lambda: True)
    monkeypatch.setattr(cc._matcher, "best_match", lambda query: ("switch_keyboard_layout", 0.95))

    assert cc.match_system_command("смени раскладку без указания языка") is None


def test_unavailable_reason_reflects_initialization_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_ensure_initialized", lambda: False)
    monkeypatch.setattr(
        cc.semantic_matcher, "unavailable_reason", lambda model_name: "sentence-transformers is not installed: boom"
    )

    assert cc.unavailable_reason() == "sentence-transformers is not installed: boom"
