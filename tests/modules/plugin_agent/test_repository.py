from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from modules.plugin_agent.domain import GapCandidate, GapCandidateStatus
from modules.plugin_agent.repository import GapCandidateRepository


def _connection(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "assistant.db")
    conn.row_factory = sqlite3.Row
    return conn


def test_add_assigns_an_autoincrement_id_and_get_round_trips(tmp_path) -> None:
    repo = GapCandidateRepository(_connection(tmp_path))
    candidate = GapCandidate(representative_text="включи вентилятор")

    candidate_id = repo.add(candidate)

    assert candidate_id
    fetched = repo.get(candidate_id)
    assert fetched is not None
    assert fetched.representative_text == "включи вентилятор"
    assert fetched.status is GapCandidateStatus.COLLECTING
    assert fetched.safety_flags == []


def test_get_returns_none_for_unknown_id(tmp_path) -> None:
    repo = GapCandidateRepository(_connection(tmp_path))

    assert repo.get(999) is None


def test_list_open_only_returns_open_statuses(tmp_path) -> None:
    repo = GapCandidateRepository(_connection(tmp_path))
    open_id = repo.add(GapCandidate(representative_text="a", status=GapCandidateStatus.COLLECTING))
    repo.add(GapCandidate(representative_text="b", status=GapCandidateStatus.ENABLED))
    repo.add(GapCandidate(representative_text="c", status=GapCandidateStatus.DISMISSED))

    open_candidates = repo.list_open()

    assert [c.id for c in open_candidates] == [open_id]


def test_list_by_status_filters_when_given_and_returns_all_when_none(tmp_path) -> None:
    repo = GapCandidateRepository(_connection(tmp_path))
    repo.add(GapCandidate(representative_text="a", status=GapCandidateStatus.COLLECTING))
    repo.add(GapCandidate(representative_text="b", status=GapCandidateStatus.ENABLED))

    enabled_only = repo.list_by_status(GapCandidateStatus.ENABLED)
    everything = repo.list_by_status(None)

    assert [c.status for c in enabled_only] == [GapCandidateStatus.ENABLED]
    assert len(everything) == 2


def test_update_persists_status_and_safety_flags(tmp_path) -> None:
    repo = GapCandidateRepository(_connection(tmp_path))
    candidate_id = repo.add(GapCandidate(representative_text="a"))
    candidate = repo.get(candidate_id)
    assert candidate is not None

    candidate.status = GapCandidateStatus.REQUIRES_REVIEW
    candidate.safety_flags = ["network_access"]
    candidate.generated_plugin_name = "plugin_a"
    candidate.generated_plugin_path = "modules/plugins/_pending/plugin_a.py"
    candidate.error = None
    repo.update(candidate)

    updated = repo.get(candidate_id)
    assert updated is not None
    assert updated.status is GapCandidateStatus.REQUIRES_REVIEW
    assert updated.safety_flags == ["network_access"]
    assert updated.generated_plugin_name == "plugin_a"


def test_record_event_and_count_recent_events(tmp_path) -> None:
    repo = GapCandidateRepository(_connection(tmp_path))
    candidate_id = repo.add(GapCandidate(representative_text="a"))
    now = datetime.now()

    repo.record_event(candidate_id, "включи вентилятор", now)
    repo.record_event(candidate_id, "включи вентилятор пожалуйста", now)

    recent_count = repo.count_recent_events(candidate_id, cutoff=now - timedelta(days=1))
    old_cutoff_count = repo.count_recent_events(candidate_id, cutoff=now + timedelta(days=1))

    assert recent_count == 2
    assert old_cutoff_count == 0
