from __future__ import annotations

from datetime import datetime

import pytest

from modules.delayed_execution.command_parser import extract_delay

_NOW = datetime(2026, 8, 30, 12, 0, 0)


def test_no_marker_returns_none() -> None:
    assert extract_delay("открой браузер", "ru", now=_NOW) is None


def test_through_minutes() -> None:
    spec = extract_delay("открой браузер через 10 минут", "ru", now=_NOW)
    assert spec is not None
    assert spec.remainder == "открой браузер"
    assert spec.run_at == datetime(2026, 8, 30, 12, 10, 0)
    assert spec.spoken_delay == "10 мин"


def test_through_hour_wordform() -> None:
    spec = extract_delay("выключи компьютер через час", "ru", now=_NOW)
    assert spec is not None
    assert spec.remainder == "выключи компьютер"
    assert spec.run_at == datetime(2026, 8, 30, 13, 0, 0)


def test_through_seconds() -> None:
    spec = extract_delay("поставь музыку через 5 секунд", "ru", now=_NOW)
    assert spec is not None and spec.run_at == datetime(2026, 8, 30, 12, 0, 5)


def test_absolute_hour_today() -> None:
    spec = extract_delay("выключи свет в 18 часов", "ru", now=_NOW)
    assert spec is not None
    assert spec.remainder == "выключи свет"
    assert spec.run_at == datetime(2026, 8, 30, 18, 0, 0)


def test_absolute_hour_already_passed_rolls_to_tomorrow() -> None:
    spec = extract_delay("выключи свет в 9 часов", "ru", now=_NOW)
    assert spec is not None and spec.run_at == datetime(2026, 8, 31, 9, 0, 0)


def test_bare_v_number_is_not_a_clock_time() -> None:
    # "в 20 процентов" must not read as "at 20:00".
    assert extract_delay("поставь громкость в 20 процентов", "ru", now=_NOW) is None


def test_marker_with_empty_remainder_returns_none() -> None:
    assert extract_delay("через 10 минут", "ru", now=_NOW) is None


def test_english_relative() -> None:
    spec = extract_delay("open the browser in 10 minutes", "en", now=_NOW)
    assert spec is not None
    assert spec.remainder == "open the browser"
    assert spec.run_at == datetime(2026, 8, 30, 12, 10, 0)


@pytest.mark.parametrize("count", [1, 3, 45])
def test_minute_count_scales(count: int) -> None:
    spec = extract_delay(f"сверни окно через {count} минут", "ru", now=_NOW)
    assert spec is not None
    assert (spec.run_at - _NOW).total_seconds() == count * 60
