from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.english_learning import assistant_http, cefr, difficulty, link_import, service_layer
from modules.english_learning.assistant_engine import AnswerGuard, parse_action
from modules.english_learning.domain import Card, EpisodeStats, ReviewEntry, Title
from modules.english_learning.english_assistant import (
    GENERAL_KNOWLEDGE_NOTE,
    EnglishAssistant,
    ScreenContext,
    TurnAction,
    TurnOutput,
    build_context,
)
from modules.english_learning.repository import LemmaRecord
from modules.english_learning.uow import EnglishUnitOfWork
from tests.modules.english_learning.conftest import CEFR_CSV, FakeLemmatizer
from tests.modules.english_learning.test_service_layer import SRT


class ScriptedStream:
    def __init__(self, *replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[list[dict[str, str]]] = []

    def __call__(self, messages: Any, max_tokens: int) -> AsyncIterator[str]:
        self.prompts.append(list(messages))
        reply = self.replies.pop(0) if self.replies else ["ok"]

        async def gen() -> AsyncIterator[str]:
            for chunk in reply:
                yield chunk

        return gen()


def _events(raw: list[str]) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in raw:
        event, data = block.strip().split("\n", 1)
        parsed.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return parsed


def _collect(iterator: AsyncIterator[str]) -> list[tuple[str, dict[str, Any]]]:
    async def run() -> list[str]:
        return [event async for event in iterator]

    return _events(asyncio.run(run()))


def _text(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(data["text"] for name, data in events if name == "delta")


@pytest.fixture
def episode(uow_factory: Callable[[], EnglishUnitOfWork]) -> tuple[int, int]:
    result = service_layer.import_srt_file(
        series_title="Breaking Bad",
        season=1,
        episode=1,
        raw=SRT,
        lemmatizer=FakeLemmatizer(),
        uow_factory=uow_factory,
        ensure_cefr=lambda: cefr.ensure_loaded(uow_factory, lambda: CEFR_CSV),
    )
    assert result.episode.id is not None
    with uow_factory() as uow:
        card = Card(result.episode.id, "give up", "give up", "MWE", "A2", ["сдаваться", "опускать руки"], "Stop trying.", "I will never give up.", 0, "core", kind="phrasal_verb", surface_form="give up")
        uow.cards.add(card)
        uow.commit()
    assert card.id is not None
    return result.episode.id, card.id


def test_guard_masks_answers_split_across_chunks_and_yo() -> None:
    guard = AnswerGuard(["сдаваться", "опускать руки"])
    chunks = ["Подумайте: это не «сда", "ваться», а… ОПУСКАТЬ ", "РУКИ. И ещё сдаёться нет."]

    out = "".join(guard.feed(chunk) for chunk in chunks) + guard.flush()

    assert "сдаваться" not in out.lower() and "опускать руки" not in out.lower()
    assert "•••" in out and guard.masked
    assert AnswerGuard([]).feed("free text") == "free text"


def test_context_hides_current_translation_until_answered(uow_factory: Callable[[], EnglishUnitOfWork], episode: tuple[int, int]) -> None:
    episode_id, card_id = episode
    active = ScreenContext(screen="learn", episode_id=episode_id, card_id=card_id, answered=False, mistake_card_ids=[card_id])

    text, forbidden = build_context(active, uow_factory)

    assert "сдаваться" not in text and "give up" in text
    assert forbidden == ["сдаваться", "опускать руки"]

    answered, forbidden_after = build_context(
        ScreenContext(screen="learn", episode_id=episode_id, card_id=card_id, answered=True), uow_factory
    )
    assert "сдаваться" in answered and forbidden_after == []

    service_layer.save_module_settings(allow_answer_hints=True, uow_factory=uow_factory)
    hinted, _ = build_context(active, uow_factory)
    assert "сдаваться" in hinted


def test_learn_chat_never_leaks_current_translation(uow_factory: Callable[[], EnglishUnitOfWork], episode: tuple[int, int]) -> None:
    episode_id, card_id = episode
    stream = ScriptedStream(["Ответ: сдава", "ться! Или опускать руки."])
    assistant = EnglishAssistant(uow_factory, stream)
    context = ScreenContext(screen="learn", episode_id=episode_id, card_id=card_id, answered=False)

    events = _collect(assistant.chat([], context, TurnOutput()))

    text = _text(events)
    assert "сдаваться" not in text and "опускать руки" not in text
    assert "НЕ называй перевод" in stream.prompts[0][0]["content"]


def test_json_action_is_intercepted_and_answer_follows_computed_verdict(
    uow_factory: Callable[[], EnglishUnitOfWork], episode: tuple[int, int]
) -> None:
    stream = ScriptedStream(
        ['{"action":"difficulty_check",', '"title":"breaking bad","year":null,"kind":"series"}'],
        ["Покрытие низкое, много новых слов.\n", "Смотрите с субтитрами."],
    )
    output = TurnOutput()

    events = _collect(EnglishAssistant(uow_factory, stream).chat([], ScreenContext(), output))

    names = [name for name, _ in events]
    assert names[0] == "difficulty"
    card = events[0][1]
    assert card["title"] == "Breaking Bad" and card["source"] == "subtitles" and card["small_sample"] is True
    text = _text(events)
    assert text.startswith(f"**{card['verdict']}**")
    assert "action" not in text
    assert output.meta["difficulty"]["verdict"] == card["verdict"]
    assert "по субтитрам 1 эпизод" in stream.prompts[1][0]["content"]


def test_unknown_title_offers_analysis(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    stream = ScriptedStream(['{"action":"difficulty_check","title":"Sherlock Holmes","year":2009,"kind":"movie"}'])
    output = TurnOutput()

    events = _collect(EnglishAssistant(uow_factory, stream).chat([], ScreenContext(), output))

    assert events[0] == ("offer", {"title": "Sherlock Holmes", "year": 2009, "kind": "movie"})
    assert "OpenSubtitles" in _text(events)
    assert len(stream.prompts) == 1


def test_general_knowledge_answer_is_labelled(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    stream = ScriptedStream(["**Подходит с усилием** — много жаргона."])
    action = TurnAction("difficulty_general", "Sherlock Holmes", 2009, "movie")

    events = _collect(EnglishAssistant(uow_factory, stream).difficulty(action, TurnOutput()))

    assert _text(events).startswith(f"_{GENERAL_KNOWLEDGE_NOTE}_")


def test_set_level_action(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    stream = ScriptedStream(['```json\n{"action":"set_level","level":"b2"}\n```'])

    events = _collect(EnglishAssistant(uow_factory, stream).chat([], ScreenContext(), TurnOutput()))

    assert "B2" in _text(events)
    assert service_layer.get_module_settings(uow_factory).user_level == "B2"


def test_plain_reply_passes_through(uow_factory: Callable[[], EnglishUnitOfWork]) -> None:
    stream = ScriptedStream(["  **Idioms** are ", "fun."])

    events = _collect(EnglishAssistant(uow_factory, stream).chat([], ScreenContext(), TurnOutput()))

    assert _text(events) == "  **Idioms** are fun."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"action":"difficulty_check","title":"X"}', "difficulty_check"),
        ('Sure! {"action":"set_level","level":"B1"}', None),
        ('{"action":"delete_everything"}', None),
        ("not json", None),
    ],
)
def test_parse_action(text: str, expected: str | None) -> None:
    action = parse_action(text)
    assert (action or {}).get("action") == expected


def _stats(counts: dict[str, int], levels: dict[str, str | None], **extra: Any) -> EpisodeStats:
    base: dict[str, Any] = {
        "token_count": sum(counts.values()),
        "lemma_count": len(counts),
        "tokens_by_level": {},
        "lemmas_by_level": {},
        "expressions_per_1000": 0.0,
        "words_per_minute": 150.0,
        "non_english_share": 0.0,
        "off_list_share": 0.0,
        "top_above_b2": [],
        "lemma_counts": counts,
        "lemma_levels": levels,
        "cue_count": 100,
        "non_english_cues": 0,
        "speech_minutes": 10.0,
    }
    base.update(extra)
    return EpisodeStats(**base)


def test_coverage_on_fixture_counts_known_tokens() -> None:
    counts = {"the": 50, "house": 30, "grim": 10, "ubiquitous": 5, "dude": 5}
    levels: dict[str, str | None] = {"the": "A1", "house": "A1", "grim": "B2", "ubiquitous": "C1", "dude": None}

    known = difficulty.known_words("B1", [])
    assert difficulty.coverage(counts, levels, known) == pytest.approx(0.80)

    learned = difficulty.known_words("B1", [LemmaRecord("grim", 1, 0, True), LemmaRecord("house", 0, 3, False)])
    assert difficulty.coverage(counts, levels, learned) == pytest.approx(0.60)

    report = difficulty.build_report(Title(name="X", kind="movie", id=1), [_stats(counts, levels)], known)
    assert report.verdict == "Пока рано"
    assert report.examples == ["grim", "ubiquitous"]
    assert report.above_level_count == 2


@pytest.mark.parametrize(
    ("value", "factors", "verdict"),
    [
        (0.985, [], "Подходит"),
        (0.98, [], "Подходит"),
        (0.975, [], "Подходит с усилием"),
        (0.95, [], "Подходит с усилием"),
        (0.949, [], "Пока рано"),
        (0.985, ["fast"], "Подходит с усилием"),
        (0.995, ["fast"], "Подходит"),
        (0.995, ["fast", "slang"], "Подходит с усилием"),
        (0.955, ["fast"], "Пока рано"),
        (0.90, ["fast", "slang"], "Пока рано"),
    ],
)
def test_verdict_thresholds_and_adjustments(value: float, factors: list[str], verdict: str) -> None:
    assert difficulty.adjusted_verdict(value, factors) == verdict


def test_fast_speech_and_foreign_lines_become_factors() -> None:
    stats = _stats({"the": 100}, {"the": "A1"}, words_per_minute=210.0, non_english_cues=10)

    report = difficulty.build_report(Title(name="Narcos", id=2), [stats], difficulty.known_words("B1", []))

    assert report.coverage == 1.0
    assert any("быстрая речь" in factor for factor in report.factors)
    assert any("не на английском" in factor for factor in report.factors)
    assert report.verdict == "Подходит с усилием"


def test_find_title_matches_loosely_and_by_year() -> None:
    titles = [Title(name="Sherlock Holmes", kind="movie", year=1922, id=1), Title(name="Sherlock Holmes", kind="movie", year=2009, id=2)]

    assert difficulty.find_title(titles, "sherlock holmes", 2009).id == 2  # type: ignore[union-attr]
    assert difficulty.find_title(titles, "Sherlock", None, "movie").id == 1  # type: ignore[union-attr]
    assert difficulty.find_title(titles, "Dark", None) is None


def test_mistakes_reduce_known_words(uow_factory: Callable[[], EnglishUnitOfWork], episode: tuple[int, int]) -> None:
    _, card_id = episode
    with uow_factory() as uow:
        for _ in range(3):
            uow.reviews.add(ReviewEntry(card_id=card_id, mode="input", correct=False, answer="x"))
        uow.commit()
        records = uow.reviews.lemma_records()

    known = difficulty.known_words("B1", records)
    assert not known.knows("give up", "A2")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, uow_factory: Callable[[], EnglishUnitOfWork]) -> tuple[TestClient, ScriptedStream]:
    stream = ScriptedStream(["Привет", "! Чем помочь?"], ["Второй ", "вариант."])
    monkeypatch.setattr(assistant_http, "uow_factory", uow_factory)
    monkeypatch.setattr(assistant_http, "assistant_factory", lambda: EnglishAssistant(uow_factory, stream))
    app = FastAPI()
    app.include_router(assistant_http.router, prefix="/api/english")
    return TestClient(app), stream


def _sse(response: Any) -> list[tuple[str, dict[str, Any]]]:
    return _events([block for block in response.text.split("\n\n") if block.strip()])


def test_threads_messages_stream_and_regenerate(client: tuple[TestClient, ScriptedStream]) -> None:
    http, _ = client
    thread = http.post("/api/english/assistant/threads", json={"scope": "episode", "scope_id": 5}).json()
    assert http.get("/api/english/assistant/threads", params={"scope": "episode", "scope_id": 5}).json()[0]["id"] == thread["id"]

    response = http.post(f"/api/english/assistant/threads/{thread['id']}/messages", json={"content": "hi"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse(response)
    assert _text(events) == "Привет! Чем помочь?"
    assert events[-1][0] == "done" and events[-1][1]["message_id"]

    again = _sse(http.post(f"/api/english/assistant/threads/{thread['id']}/messages", json={"regenerate": True}))
    assert _text(again) == "Второй вариант."
    messages = http.get(f"/api/english/assistant/threads/{thread['id']}/messages").json()
    assert [(item["role"], item["content"]) for item in messages] == [("user", "hi"), ("assistant", "Второй вариант.")]

    assert http.post(f"/api/english/assistant/threads/{thread['id']}/messages", json={"content": " "}).status_code == 422
    assert http.post("/api/english/assistant/threads/999/messages", json={"content": "x"}).status_code == 404


def test_ui_settings_round_trip(client: tuple[TestClient, ScriptedStream]) -> None:
    http, _ = client

    assert http.get("/api/english/ui-settings/assistant_panel").json() == {"key": "assistant_panel", "value": None}
    http.put("/api/english/ui-settings/assistant_panel", json={"value": {"open": True, "width": 420}})
    assert http.get("/api/english/ui-settings/assistant_panel").json()["value"] == {"open": True, "width": 420}
    assert http.get("/api/english/ui-settings/Bad-Key").status_code == 422


def test_analyze_endpoint_reports_needs_input(client: tuple[TestClient, ScriptedStream], monkeypatch: pytest.MonkeyPatch) -> None:
    http, _ = client

    async def no_subs(title: str, kind: str | None, year: int | None) -> link_import.NeedsInput:
        from modules.english_learning.link_parser import LinkGuess

        return link_import.NeedsInput(kind="subtitles", message="Субтитры не найдены.", guess=LinkGuess("", title, None, None), problems=["OpenSubtitles: лимит"])

    monkeypatch.setattr(link_import, "import_by_title", no_subs)

    body = http.post("/api/english/assistant/analyze", json={"title": "Dark", "kind": "series"}).json()

    assert body["status"] == "needs_input" and "лимит" in body["message"]
