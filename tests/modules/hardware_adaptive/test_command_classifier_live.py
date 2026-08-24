from __future__ import annotations

import pytest

from modules.hardware_adaptive import command_classifier as cc

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module", autouse=True)
def _ensure_real_model_loaded():
    if not cc._ensure_initialized():
        pytest.skip(f"Local command classifier unavailable: {cc.unavailable_reason()}")


@pytest.mark.parametrize(
    ("utterance", "expected_command"),
    [
        ("сделай потише немного", "change_volume"),
        ("поставь громкость 70 процентов", "set_volume"),
        ("какой сейчас уровень громкости", "get_volume"),
        ("убери звук совсем", "mute"),
        ("включи звук обратно, пожалуйста", "unmute"),
        ("сверни это окно сейчас", "minimize_window"),
        ("закрой текущее окно программы", "close_os_window"),
        ("закрой вкладку в браузере", "close_browser_tab"),
        ("создай папку /home/user/отчёты", "create_folder"),
        ("перемести файл /home/user/отчёт.txt в /home/user/архив", "move_folder"),
        ("сколько у меня осталось заряда батареи", "get_battery_status"),
        ("проверь, есть ли обновления системы", "check_system_updates"),
    ],
)
def test_live_classifier_matches_realistic_paraphrases(utterance: str, expected_command: str) -> None:
    result = cc.match_system_command(utterance)
    assert result is not None, f"Expected {utterance!r} to match {expected_command!r}, got no match at all"
    assert result.name == expected_command


@pytest.mark.parametrize(
    "utterance",
    [
        "что ты умеешь",
        "спасибо большое",
        "расскажи анекдот",
    ],
)
def test_live_classifier_rejects_small_talk(utterance: str) -> None:
    assert cc.match_system_command(utterance) is None
