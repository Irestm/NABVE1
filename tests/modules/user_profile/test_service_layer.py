from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.user_profile import service_layer
from modules.user_profile.domain import (
    EPISODIC_MAX_FACTS,
    EPISODIC_TTL_DAYS,
    ONBOARDING_COMPLETE_KEY,
    FactCategory,
    ProfileFact,
)
from modules.user_profile.uow import ProfileUnitOfWork


class FakeProfileFactRepository:
    """In-memory stand-in for modules.user_profile.repository.ProfileFactRepository
    — no sqlite, no keyring, so service_layer's actual business rules (fact
    retention/eviction, onboarding gating) can be tested in isolation. This
    is the payoff cosmicpython's repository pattern is meant to enable."""

    def __init__(self) -> None:
        self._facts: dict[str, ProfileFact] = {}

    def add(self, item: ProfileFact) -> str:
        self._facts[item.key] = item
        return item.key

    def get(self, key: str) -> ProfileFact | None:
        return self._facts.get(key)

    def delete(self, key: str) -> bool:
        return self._facts.pop(key, None) is not None

    def list_keys(self) -> list[str]:
        return sorted(self._facts)

    def list_by_category(self, category: FactCategory) -> list[ProfileFact]:
        return [fact for fact in self._facts.values() if fact.category == category]

    def touch(self, key: str) -> None:
        fact = self._facts.get(key)
        if fact is not None:
            fact.last_used_at = datetime.now(timezone.utc)


class FakeProfileUnitOfWork:
    def __init__(self) -> None:
        self.facts = FakeProfileFactRepository()
        self.committed = False

    def __enter__(self) -> "FakeProfileUnitOfWork":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


def test_set_and_get_fact_roundtrip() -> None:
    uow = FakeProfileUnitOfWork()
    service_layer.set_fact(uow, "name", "Даниил")
    assert service_layer.get_fact(uow, "name") == "Даниил"


def test_get_fact_returns_none_for_missing_key() -> None:
    uow = FakeProfileUnitOfWork()
    assert service_layer.get_fact(uow, "nonexistent") is None


def test_delete_and_forget_are_the_same_operation() -> None:
    uow = FakeProfileUnitOfWork()
    service_layer.set_fact(uow, "name", "Даниил")
    assert service_layer.forget(uow, "name") is True
    assert service_layer.get_fact(uow, "name") is None
    assert service_layer.forget(uow, "name") is False


def test_onboarding_gate_starts_false_and_flips_once_completed() -> None:
    uow = FakeProfileUnitOfWork()
    assert service_layer.is_onboarded(uow) is False
    service_layer.complete_onboarding(uow)
    assert service_layer.is_onboarded(uow) is True


def test_onboarding_flag_is_excluded_from_context_facts() -> None:
    uow = FakeProfileUnitOfWork()
    service_layer.complete_onboarding(uow)
    service_layer.set_fact(uow, "name", "Даниил")
    facts = service_layer.get_context_facts(uow)
    assert ONBOARDING_COMPLETE_KEY not in {f.key for f in facts}
    assert {f.key for f in facts} == {"name"}


def test_context_facts_prioritize_core_over_episodic_within_budget() -> None:
    uow = FakeProfileUnitOfWork()
    for i in range(3):
        service_layer.set_fact(uow, f"core_{i}", "x", category=FactCategory.CORE)
    for i in range(3):
        service_layer.set_fact(uow, f"episodic_{i}", "x", category=FactCategory.EPISODIC)

    facts = service_layer.get_context_facts(uow, budget=4)

    core_count = sum(1 for f in facts if f.category == FactCategory.CORE)
    assert core_count == 3
    assert len(facts) == 4


def test_episodic_facts_are_capped_at_max_and_lowest_score_evicted() -> None:
    uow = FakeProfileUnitOfWork()
    for i in range(EPISODIC_MAX_FACTS + 5):
        service_layer.record_episodic_fact(uow, f"fact_{i}", "value", importance=0.1 + i * 0.001)

    remaining = uow.facts.list_by_category(FactCategory.EPISODIC)
    assert len(remaining) <= EPISODIC_MAX_FACTS
    # The earliest (lowest-importance, least-recent) facts should be the
    # ones evicted, not an arbitrary subset.
    assert "fact_0" not in {f.key for f in remaining}


def test_expired_episodic_facts_are_evicted_regardless_of_count() -> None:
    uow = FakeProfileUnitOfWork()
    stale = ProfileFact(
        key="stale",
        value="old",
        category=FactCategory.EPISODIC,
        last_used_at=datetime.now(timezone.utc) - timedelta(days=EPISODIC_TTL_DAYS + 1),
    )
    uow.facts.add(stale)

    removed = service_layer.evict_stale_facts(uow)

    assert removed == 1
    assert uow.facts.get("stale") is None


def test_core_facts_are_never_evicted() -> None:
    uow = FakeProfileUnitOfWork()
    old_core = ProfileFact(
        key="ancient_core_fact",
        value="still here",
        category=FactCategory.CORE,
        last_used_at=datetime.now(timezone.utc) - timedelta(days=EPISODIC_TTL_DAYS * 10),
    )
    uow.facts.add(old_core)

    service_layer.evict_stale_facts(uow)

    assert uow.facts.get("ancient_core_fact") is not None


def test_format_context_summary_is_none_for_no_facts() -> None:
    assert service_layer.format_context_summary([]) is None


def test_save_about_me_stores_raw_text_and_extracts_facts() -> None:
    uow = FakeProfileUnitOfWork()

    extracted_keys = service_layer.save_about_me(
        uow, "Меня зовут Даниил, я работаю программистом и я живу в Киеве."
    )

    assert service_layer.get_fact(uow, "about_me") == (
        "Меня зовут Даниил, я работаю программистом и я живу в Киеве."
    )
    assert set(extracted_keys) == {"about_name", "about_work", "about_location"}
    assert service_layer.get_fact(uow, "about_name") == "Даниил"
    assert service_layer.get_fact(uow, "about_work") == "программистом"
    assert service_layer.get_fact(uow, "about_location") == "Киеве"


def test_save_about_me_with_no_recognizable_facts_still_stores_raw_text() -> None:
    uow = FakeProfileUnitOfWork()

    extracted_keys = service_layer.save_about_me(uow, "Просто немного текста без шаблонных фраз.")

    assert extracted_keys == []
    assert service_layer.get_fact(uow, "about_me") == "Просто немного текста без шаблонных фраз."


def test_save_about_me_extracted_facts_are_core_and_never_evicted() -> None:
    uow = FakeProfileUnitOfWork()

    service_layer.save_about_me(uow, "Меня зовут Даниил.")

    fact = uow.facts.get("about_name")
    assert fact is not None
    assert fact.category == FactCategory.CORE


def test_real_sqlite_repository_roundtrip_and_schema_migration(tmp_db_path: Path) -> None:
    """Integration test against the real repository/uow (sqlite + keyring),
    not the fake — confirms the additive schema migration in
    repository.ensure_schema actually works end to end."""
    uow_factory = lambda: ProfileUnitOfWork(db_path=tmp_db_path)

    service_layer.set_fact(uow_factory(), "name", "Даниил")
    assert service_layer.get_fact(uow_factory(), "name") == "Даниил"
    assert service_layer.is_onboarded(uow_factory()) is False
    service_layer.complete_onboarding(uow_factory())
    assert service_layer.is_onboarded(uow_factory()) is True
