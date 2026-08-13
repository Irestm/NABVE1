from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.message_bus import MessageBus
from modules.plugin_agent import plugin_generator, service_layer
from modules.plugin_agent.domain import GapCandidate, GapCandidateStatus
from modules.plugin_agent.events import PluginCandidateReadyForReview
from modules.plugin_agent.plugin_generator import GenerationResult, SafetyReport


class FakeGapCandidateRepository:
    def __init__(self) -> None:
        self._candidates: dict[int, GapCandidate] = {}
        self._events: list[tuple[int, str, datetime]] = []
        self._next_id = 1

    def add(self, item: GapCandidate) -> int:
        item.id = self._next_id
        self._candidates[self._next_id] = item
        self._next_id += 1
        return item.id

    def get(self, key: int) -> GapCandidate | None:
        return self._candidates.get(key)

    def list_open(self) -> list[GapCandidate]:
        from modules.plugin_agent.domain import OPEN_STATUSES

        return [c for c in self._candidates.values() if c.status in OPEN_STATUSES]

    def list_by_status(self, status: GapCandidateStatus | None = None) -> list[GapCandidate]:
        if status is None:
            return list(self._candidates.values())
        return [c for c in self._candidates.values() if c.status == status]

    def update(self, candidate: GapCandidate) -> None:
        self._candidates[candidate.id] = candidate

    def record_event(self, candidate_id: int, raw_text: str, created_at: datetime) -> None:
        self._events.append((candidate_id, raw_text, created_at))

    def count_recent_events(self, candidate_id: int, cutoff: datetime) -> int:
        return sum(1 for cid, _, ts in self._events if cid == candidate_id and ts >= cutoff)


class FakePluginAgentUnitOfWork:
    def __init__(self) -> None:
        self.candidates = FakeGapCandidateRepository()

    def __enter__(self) -> "FakePluginAgentUnitOfWork":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_too_short_text_is_ignored() -> None:
    uow = FakePluginAgentUnitOfWork()
    assert service_layer.record_question(uow, "ok") is None


def test_new_question_creates_a_collecting_candidate() -> None:
    uow = FakePluginAgentUnitOfWork()
    result = service_layer.record_question(uow, "открой калькулятор")
    assert result is not None
    assert result.occurrence_count == 1
    assert result.promoted is False
    candidate = uow.candidates.get(result.candidate_id)
    assert candidate.status == GapCandidateStatus.COLLECTING


def test_similar_questions_fold_into_the_same_candidate() -> None:
    uow = FakePluginAgentUnitOfWork()
    first = service_layer.record_question(uow, "открой калькулятор пожалуйста")
    second = service_layer.record_question(uow, "открой калькулятор пожалуйста")
    assert first.candidate_id == second.candidate_id
    assert second.occurrence_count == 2


def test_candidate_is_promoted_after_occurrence_threshold() -> None:
    uow = FakePluginAgentUnitOfWork()
    results = [service_layer.record_question(uow, "включи ночной режим") for _ in range(3)]
    assert results[-1].promoted is True
    candidate = uow.candidates.get(results[-1].candidate_id)
    assert candidate.status == GapCandidateStatus.READY_FOR_GENERATION


def test_reject_marks_candidate_dismissed_and_removes_generated_file(tmp_path) -> None:
    uow = FakePluginAgentUnitOfWork()
    candidate = GapCandidate(
        representative_text="x",
        status=GapCandidateStatus.PENDING_REVIEW,
        created_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )
    generated = tmp_path / "generated.py"
    generated.write_text("plugin = None")
    candidate.generated_plugin_path = str(generated)
    candidate_id = uow.candidates.add(candidate)

    service_layer.reject(uow, candidate_id)

    assert uow.candidates.get(candidate_id).status == GapCandidateStatus.DISMISSED
    assert not generated.exists()


# --- process_next_ready_candidate / PluginCandidateReadyForReview ---------


def _ready_candidate(uow: FakePluginAgentUnitOfWork) -> int:
    candidate = GapCandidate(
        representative_text="открой калькулятор",
        status=GapCandidateStatus.READY_FOR_GENERATION,
        created_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )
    return uow.candidates.add(candidate)


async def test_publishes_review_event_on_successful_generation(monkeypatch) -> None:
    uow = FakePluginAgentUnitOfWork()
    _ready_candidate(uow)

    fake_result = GenerationResult(
        success=True,
        plugin_path=Path("/fake/plugin_open_calc.py"),
        plugin_name="plugin_open_calc",
        safety_report=SafetyReport(flags=[]),
    )
    monkeypatch.setattr(plugin_generator, "generate_plugin_for_candidate", lambda payload: fake_result)

    bus = MessageBus()
    received: list[PluginCandidateReadyForReview] = []

    async def _record(event: PluginCandidateReadyForReview) -> None:
        received.append(event)

    bus.subscribe(PluginCandidateReadyForReview, _record)

    await service_layer.process_next_ready_candidate(uow, bus)

    assert len(received) == 1
    assert received[0].plugin_name == "plugin_open_calc"
    assert received[0].requires_manual_review is False


async def test_review_event_flags_manual_review_when_safety_scan_found_something(monkeypatch) -> None:
    uow = FakePluginAgentUnitOfWork()
    _ready_candidate(uow)

    fake_result = GenerationResult(
        success=True,
        plugin_path=Path("/fake/plugin_risky.py"),
        plugin_name="plugin_risky",
        safety_report=SafetyReport(flags=["subprocess call with shell=True"]),
    )
    monkeypatch.setattr(plugin_generator, "generate_plugin_for_candidate", lambda payload: fake_result)

    bus = MessageBus()
    received: list[PluginCandidateReadyForReview] = []

    async def _record(event: PluginCandidateReadyForReview) -> None:
        received.append(event)

    bus.subscribe(PluginCandidateReadyForReview, _record)

    await service_layer.process_next_ready_candidate(uow, bus)

    assert received[0].requires_manual_review is True


async def test_no_event_published_when_generation_fails(monkeypatch) -> None:
    uow = FakePluginAgentUnitOfWork()
    candidate_id = _ready_candidate(uow)

    fake_result = GenerationResult(success=False, error="boom")
    monkeypatch.setattr(plugin_generator, "generate_plugin_for_candidate", lambda payload: fake_result)

    bus = MessageBus()
    received: list[PluginCandidateReadyForReview] = []

    async def _record(event: PluginCandidateReadyForReview) -> None:
        received.append(event)

    bus.subscribe(PluginCandidateReadyForReview, _record)

    await service_layer.process_next_ready_candidate(uow, bus)

    assert received == []
    assert uow.candidates.get(candidate_id).status == GapCandidateStatus.GENERATION_FAILED


async def test_no_event_published_when_nothing_is_ready() -> None:
    uow = FakePluginAgentUnitOfWork()
    bus = MessageBus()
    received: list[PluginCandidateReadyForReview] = []

    async def _record(event: PluginCandidateReadyForReview) -> None:
        received.append(event)

    bus.subscribe(PluginCandidateReadyForReview, _record)

    await service_layer.process_next_ready_candidate(uow, bus)

    assert received == []
