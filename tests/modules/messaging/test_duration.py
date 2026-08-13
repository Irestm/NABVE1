from __future__ import annotations

from modules.messaging.duration import parse_duration_minutes


def test_parse_digit_minutes() -> None:
    assert parse_duration_minutes("10 минут") == 10
    assert parse_duration_minutes("на 5 мин") == 5


def test_parse_digit_hours() -> None:
    assert parse_duration_minutes("2 часа") == 120
    assert parse_duration_minutes("1 час") == 60


def test_parse_fixed_phrases() -> None:
    assert parse_duration_minutes("полчаса") == 30
    assert parse_duration_minutes("отложи на час") == 60
    assert parse_duration_minutes("пару часов") == 120
    assert parse_duration_minutes("минутку") == 1


def test_parse_returns_none_for_empty_or_unrecognized() -> None:
    assert parse_duration_minutes("") is None
    assert parse_duration_minutes("   ") is None
    assert parse_duration_minutes("не знаю") is None


def test_parse_is_case_insensitive() -> None:
    assert parse_duration_minutes("ПОЛЧАСА") == 30
    assert parse_duration_minutes("10 МИНУТ") == 10
