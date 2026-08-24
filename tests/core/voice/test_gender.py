from __future__ import annotations

from core.voice import gender


def _fake_get_fact(values: dict[str, str]):
    return lambda uow, key: values.get(key)


def test_get_user_gender_defaults_to_male_when_no_fact_is_set(monkeypatch) -> None:
    monkeypatch.setattr(gender.profile_service_layer, "get_fact", _fake_get_fact({}))

    assert gender.get_user_gender() == "male"


def test_get_user_gender_reads_female_from_the_profile(monkeypatch) -> None:
    monkeypatch.setattr(gender.profile_service_layer, "get_fact", _fake_get_fact({"gender": "female"}))

    assert gender.get_user_gender() == "female"


def test_pick_returns_male_by_default(monkeypatch) -> None:
    monkeypatch.setattr(gender.profile_service_layer, "get_fact", _fake_get_fact({}))

    assert gender.pick("понял", "поняла") == "понял"


def test_pick_returns_female_when_gender_is_female(monkeypatch) -> None:
    monkeypatch.setattr(gender.profile_service_layer, "get_fact", _fake_get_fact({"gender": "female"}))

    assert gender.pick("понял", "поняла") == "поняла"
