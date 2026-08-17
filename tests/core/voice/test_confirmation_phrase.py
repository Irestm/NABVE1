from __future__ import annotations

from core.voice import confirmation_phrase


def _fake_get_fact(values: dict[str, str]):
    return lambda uow, key: values.get(key)


def test_is_enabled_true_when_profile_fact_is_1(monkeypatch) -> None:
    monkeypatch.setattr(
        confirmation_phrase.profile_service_layer, "get_fact", _fake_get_fact({"confirmation_phrase_enabled": "1"})
    )

    assert confirmation_phrase.is_enabled() is True


def test_is_enabled_false_when_profile_fact_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(confirmation_phrase.profile_service_layer, "get_fact", _fake_get_fact({}))

    assert confirmation_phrase.is_enabled() is False


def test_get_confirmation_phrase_uses_male_phrases_by_default(monkeypatch) -> None:
    monkeypatch.setattr(confirmation_phrase, "_last_phrase", None)
    monkeypatch.setattr(confirmation_phrase.profile_service_layer, "get_fact", _fake_get_fact({}))

    phrase = confirmation_phrase.get_confirmation_phrase()

    assert phrase in confirmation_phrase._MALE_PHRASES


def test_get_confirmation_phrase_uses_female_phrases_when_gender_is_female(monkeypatch) -> None:
    monkeypatch.setattr(confirmation_phrase, "_last_phrase", None)
    monkeypatch.setattr(confirmation_phrase.profile_service_layer, "get_fact", _fake_get_fact({"gender": "female"}))

    phrase = confirmation_phrase.get_confirmation_phrase()

    assert phrase in confirmation_phrase._FEMALE_PHRASES


def test_get_confirmation_phrase_never_immediately_repeats(monkeypatch) -> None:
    monkeypatch.setattr(confirmation_phrase, "_last_phrase", confirmation_phrase._MALE_PHRASES[0])
    monkeypatch.setattr(confirmation_phrase.profile_service_layer, "get_fact", _fake_get_fact({}))
    monkeypatch.setattr(confirmation_phrase.random, "choice", lambda candidates: candidates[0])

    phrase = confirmation_phrase.get_confirmation_phrase()

    assert phrase != confirmation_phrase._MALE_PHRASES[0]


def test_get_confirmation_phrase_updates_last_phrase(monkeypatch) -> None:
    monkeypatch.setattr(confirmation_phrase, "_last_phrase", None)
    monkeypatch.setattr(confirmation_phrase.profile_service_layer, "get_fact", _fake_get_fact({}))

    phrase = confirmation_phrase.get_confirmation_phrase()

    assert confirmation_phrase._last_phrase == phrase
