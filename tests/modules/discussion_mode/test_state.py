from __future__ import annotations

from modules.discussion_mode.state import DiscussionSession


def test_activate_resets_and_deactivate_clears() -> None:
    s = DiscussionSession()
    assert s.is_active() is False
    s.activate()
    s.add_line("спикер 1", "привет")
    assert s.is_active() is True
    assert s.line_count() == 1

    s.deactivate()
    assert s.is_active() is False
    assert s.line_count() == 0
    assert s.full_transcript() == ""


def test_transcript_since_last_opinion_returns_only_new_lines() -> None:
    s = DiscussionSession()
    s.activate()
    s.add_line("спикер 1", "надо брать ипотеку")
    s.add_line("спикер 2", "нет, копить")
    assert "ипотеку" in s.transcript_since_last_opinion()

    s.mark_opinion_given()
    assert s.transcript_since_last_opinion() == ""

    s.add_line("спикер 1", "а если ставка упадёт")
    assert s.transcript_since_last_opinion() == "спикер 1: а если ставка упадёт"
    # full transcript still has everything
    assert s.full_transcript().count("\n") == 2


def test_activate_clears_a_previous_session() -> None:
    s = DiscussionSession()
    s.activate()
    s.add_line("спикер 1", "старое")
    s.pitch_centroids.append(150.0)

    s.activate()
    assert s.line_count() == 0
    assert s.pitch_centroids == []
