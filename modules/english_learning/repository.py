from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.ports import AbstractRepository
from modules.english_learning.domain import (
    AiExpression,
    Card,
    Episode,
    EpisodeStats,
    EpisodeWord,
    Example,
    FilterSettings,
    LearnSession,
    LexiconEntry,
    ReviewEntry,
    Title,
)


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _examples_from_json(raw: str | None) -> list[Example]:
    examples: list[Example] = []
    for item in json.loads(raw or "[]"):
        if isinstance(item, dict) and item.get("text"):
            examples.append(
                Example(
                    text=str(item["text"]),
                    timestamp_ms=int(item.get("timestamp_ms") or 0),
                    cue_index=int(item.get("cue_index") or 0),
                )
            )
    return examples


def _row_to_title(row: sqlite3.Row) -> Title:
    return Title(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        year=row["year"],
        imdb_id=row["imdb_id"],
        tmdb_id=row["tmdb_id"],
        created_at=_parse_time(row["created_at"]),
    )


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        title_id=row["title_id"],
        season=row["season"],
        episode=row["episode"],
        part=row["part"],
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        title=row["title"],
        source=row["source"],
        srt_path=row["srt_path"],
        created_at=_parse_time(row["created_at"]),
    )


def _row_to_word(row: sqlite3.Row) -> EpisodeWord:
    details = row["details"]
    return EpisodeWord(
        id=row["id"],
        episode_id=row["episode_id"],
        lemma=row["lemma"],
        pos=row["pos"],
        cefr=row["cefr"],
        category=row["category"],
        count=row["count"],
        example=row["example"],
        timestamp_ms=row["timestamp_ms"],
        surface=row["surface"],
        kind=row["kind"],
        examples=_examples_from_json(row["examples"]),
        cefr_source=row["cefr_source"],
        confidence=row["confidence"],
        details=dict(json.loads(details)) if details else None,
    )


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        episode_id=row["episode_id"],
        word=row["word"],
        lemma=row["lemma"],
        pos=row["pos"],
        cefr=row["cefr"],
        translations_ru=list(json.loads(row["translations_ru"])),
        definition_en=row["definition_en"],
        example=row["example"],
        timestamp_ms=row["timestamp_ms"],
        category=row["category"],
        kind=row["kind"],
        surface_form=row["surface_form"],
        sense_label=row["sense_label"],
        literal_translation=row["literal_translation"],
        cefr_source=row["cefr_source"],
        confidence=row["confidence"],
        archived=bool(row["archived"]),
    )


class TitleRepository(AbstractRepository[Title, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: Title) -> int:
        item.created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO english_titles (kind, name, year, imdb_id, tmdb_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (item.kind, item.name, item.year, item.imdb_id, item.tmdb_id, item.created_at.isoformat()),
        )
        item.id = int(cursor.lastrowid)
        return item.id

    def get(self, key: int) -> Title | None:
        row = self._conn.execute("SELECT * FROM english_titles WHERE id = ?", (key,)).fetchone()
        return _row_to_title(row) if row is not None else None

    def find(self, *, imdb_id: str | None, name: str, kind: str | None = None, year: int | None = None) -> Title | None:
        if imdb_id:
            row = self._conn.execute("SELECT * FROM english_titles WHERE imdb_id = ?", (imdb_id,)).fetchone()
            if row is not None:
                return _row_to_title(row)
        query = "SELECT * FROM english_titles WHERE lower(name) = lower(?)"
        params: list[Any] = [name.strip()]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        if year is not None:
            query += " AND (year IS NULL OR year = ?)"
            params.append(year)
        row = self._conn.execute(query + " ORDER BY id LIMIT 1", params).fetchone()
        return _row_to_title(row) if row is not None else None

    def list_all(self) -> list[Title]:
        rows = self._conn.execute("SELECT * FROM english_titles ORDER BY lower(name), year").fetchall()
        return [_row_to_title(row) for row in rows]

    def update(self, item: Title) -> None:
        if item.id is None:
            raise ValueError("Title has no id")
        self._conn.execute(
            "UPDATE english_titles SET kind = ?, name = ?, year = ?, imdb_id = ?, tmdb_id = ? WHERE id = ?",
            (item.kind, item.name, item.year, item.imdb_id, item.tmdb_id, item.id),
        )

    def delete(self, key: int) -> bool:
        return self._conn.execute("DELETE FROM english_titles WHERE id = ?", (key,)).rowcount > 0


class EpisodeRepository(AbstractRepository[Episode, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: Episode) -> int:
        item.created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO english_episodes "
            "(title_id, season, episode, part, start_ms, end_ms, title, source, srt_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.title_id,
                item.season,
                item.episode,
                item.part,
                item.start_ms,
                item.end_ms,
                item.title,
                item.source,
                item.srt_path,
                item.created_at.isoformat(),
            ),
        )
        item.id = int(cursor.lastrowid)
        return item.id

    def get(self, key: int) -> Episode | None:
        row = self._conn.execute("SELECT * FROM english_episodes WHERE id = ?", (key,)).fetchone()
        return _row_to_episode(row) if row is not None else None

    def find(self, title_id: int, season: int | None, episode: int | None, part: int | None = None) -> Episode | None:
        row = self._conn.execute(
            "SELECT * FROM english_episodes WHERE title_id = ? AND season IS ? AND episode IS ? AND part IS ?",
            (title_id, season, episode, part),
        ).fetchone()
        return _row_to_episode(row) if row is not None else None

    def list_for_title(self, title_id: int) -> list[Episode]:
        rows = self._conn.execute(
            "SELECT * FROM english_episodes WHERE title_id = ? "
            "ORDER BY IFNULL(season, 0), IFNULL(episode, 0), IFNULL(part, 0)",
            (title_id,),
        ).fetchall()
        return [_row_to_episode(row) for row in rows]

    def list_all(self) -> list[Episode]:
        rows = self._conn.execute("SELECT * FROM english_episodes ORDER BY id").fetchall()
        return [_row_to_episode(row) for row in rows]

    def update(self, item: Episode) -> None:
        if item.id is None:
            raise ValueError("Episode has no id")
        self._conn.execute(
            "UPDATE english_episodes SET title = ?, source = ?, srt_path = ?, start_ms = ?, end_ms = ? WHERE id = ?",
            (item.title, item.source, item.srt_path, item.start_ms, item.end_ms, item.id),
        )

    def delete(self, key: int) -> bool:
        return self._conn.execute("DELETE FROM english_episodes WHERE id = ?", (key,)).rowcount > 0


def _word_row(episode_id: int, word: EpisodeWord) -> tuple[Any, ...]:
    return (
        episode_id,
        word.lemma,
        word.pos,
        word.cefr,
        word.category,
        word.count,
        word.example,
        word.timestamp_ms,
        word.surface,
        word.kind,
        json.dumps([example.as_dict() for example in word.examples], ensure_ascii=False),
        word.cefr_source,
        word.confidence,
        json.dumps(word.details, ensure_ascii=False) if word.details is not None else None,
    )


class EpisodeWordRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def replace_for_episode(self, episode_id: int, words: Iterable[EpisodeWord]) -> None:
        self._conn.execute("DELETE FROM english_episode_words WHERE episode_id = ?", (episode_id,))
        self._conn.executemany(
            "INSERT INTO english_episode_words "
            "(episode_id, lemma, pos, cefr, category, count, example, timestamp_ms, surface, kind, examples, "
            "cefr_source, confidence, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_word_row(episode_id, word) for word in words],
        )

    def list_for_episode(self, episode_id: int) -> list[EpisodeWord]:
        rows = self._conn.execute(
            "SELECT * FROM english_episode_words WHERE episode_id = ? ORDER BY category, count DESC, lemma",
            (episode_id,),
        ).fetchall()
        return [_row_to_word(row) for row in rows]

    def count_for_episode(self, episode_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM english_episode_words WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        return int(row[0])


def _card_values(item: Card) -> tuple[Any, ...]:
    return (
        item.episode_id,
        item.word,
        item.lemma,
        item.pos,
        item.cefr,
        json.dumps(item.translations_ru, ensure_ascii=False),
        item.definition_en,
        item.example,
        item.timestamp_ms,
        item.category,
        item.kind,
        item.surface_form,
        item.sense_label,
        item.literal_translation,
        item.cefr_source,
        item.confidence,
        int(item.archived),
    )


class CardRepository(AbstractRepository[Card, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: Card) -> int:
        cursor = self._conn.execute(
            "INSERT INTO english_cards "
            "(episode_id, word, lemma, pos, cefr, translations_ru, definition_en, example, timestamp_ms, category, "
            "kind, surface_form, sense_label, literal_translation, cefr_source, confidence, archived) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _card_values(item),
        )
        item.id = int(cursor.lastrowid)
        return item.id

    def get(self, key: int) -> Card | None:
        row = self._conn.execute("SELECT * FROM english_cards WHERE id = ?", (key,)).fetchone()
        return _row_to_card(row) if row is not None else None

    def list_for_episode(self, episode_id: int, *, include_archived: bool = False) -> list[Card]:
        query = "SELECT * FROM english_cards WHERE episode_id = ?"
        if not include_archived:
            query += " AND archived = 0"
        rows = self._conn.execute(query + " ORDER BY id", (episode_id,)).fetchall()
        return [_row_to_card(row) for row in rows]

    def list_all(self, *, include_archived: bool = False) -> list[Card]:
        query = "SELECT * FROM english_cards" + ("" if include_archived else " WHERE archived = 0")
        return [_row_to_card(row) for row in self._conn.execute(query + " ORDER BY id").fetchall()]

    def count_for_episode(self, episode_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM english_cards WHERE episode_id = ? AND archived = 0", (episode_id,)
        ).fetchone()
        return int(row[0])

    def existing_keys(self, episode_id: int) -> set[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT lemma, pos FROM english_cards WHERE episode_id = ? AND archived = 0", (episode_id,)
        ).fetchall()
        return {(row["lemma"], row["pos"]) for row in rows}

    def set_archived(self, card_ids: Iterable[int], archived: bool) -> int:
        ids = list(card_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cursor = self._conn.execute(
            f"UPDATE english_cards SET archived = ? WHERE id IN ({placeholders})", (int(archived), *ids)
        )
        return cursor.rowcount

    def delete(self, key: int) -> bool:
        return self._conn.execute("DELETE FROM english_cards WHERE id = ?", (key,)).rowcount > 0


class CefrRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def replace_all(self, entries: Iterable[tuple[str, str, str]]) -> int:
        self._conn.execute("DELETE FROM english_cefr_words")
        cursor = self._conn.executemany(
            "INSERT OR IGNORE INTO english_cefr_words (headword, pos, level) VALUES (?, ?, ?)", list(entries)
        )
        return cursor.rowcount

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM english_cefr_words").fetchone()[0])

    def load_index(self) -> dict[tuple[str, str], str]:
        rows = self._conn.execute("SELECT headword, pos, level FROM english_cefr_words").fetchall()
        return {(row["headword"], row["pos"]): row["level"] for row in rows}


class MweLexiconRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def replace_all(self, entries: Iterable[LexiconEntry]) -> int:
        self._conn.execute("DELETE FROM english_mwe_lexicon")
        self._conn.executemany(
            "INSERT OR IGNORE INTO english_mwe_lexicon (expression, normalized, kind, cefr, source) "
            "VALUES (?, ?, ?, ?, ?)",
            [(item.expression, item.normalized, item.kind, item.cefr, item.source) for item in entries],
        )
        return self.count()

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM english_mwe_lexicon").fetchone()[0])

    def list_all(self) -> list[LexiconEntry]:
        rows = self._conn.execute("SELECT expression, normalized, kind, cefr, source FROM english_mwe_lexicon").fetchall()
        return [
            LexiconEntry(
                expression=row["expression"],
                normalized=row["normalized"],
                kind=row["kind"],
                cefr=row["cefr"],
                source=row["source"],
            )
            for row in rows
        ]


class AiExpressionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def replace_for_episode(self, episode_id: int, items: Iterable[AiExpression]) -> None:
        self._conn.execute("DELETE FROM english_ai_expressions WHERE episode_id = ?", (episode_id,))
        self._conn.executemany(
            "INSERT INTO english_ai_expressions (episode_id, cue_index, surface_form, normalized, kind, meaning_en, "
            "translations_ru, literal_translation, cefr_estimate, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    episode_id,
                    item.cue_index,
                    item.surface_form,
                    item.normalized,
                    item.kind,
                    item.meaning_en,
                    json.dumps(item.translations_ru, ensure_ascii=False),
                    item.literal_translation,
                    item.cefr_estimate,
                    item.confidence,
                )
                for item in items
            ],
        )

    def has_run(self, episode_id: int) -> bool:
        row = self._conn.execute(
            "SELECT value FROM english_settings WHERE key = ?", (f"ai_expressions_done:{episode_id}",)
        ).fetchone()
        return row is not None

    def mark_run(self, episode_id: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO english_settings (key, value) VALUES (?, ?)",
            (f"ai_expressions_done:{episode_id}", json.dumps(datetime.now().isoformat())),
        )

    def list_for_episode(self, episode_id: int) -> list[AiExpression]:
        rows = self._conn.execute(
            "SELECT * FROM english_ai_expressions WHERE episode_id = ? ORDER BY cue_index, id", (episode_id,)
        ).fetchall()
        return [
            AiExpression(
                cue_index=row["cue_index"],
                surface_form=row["surface_form"],
                normalized=row["normalized"],
                kind=row["kind"],
                meaning_en=row["meaning_en"],
                translations_ru=list(json.loads(row["translations_ru"])),
                literal_translation=row["literal_translation"],
                cefr_estimate=row["cefr_estimate"],
                confidence=float(row["confidence"]),
            )
            for row in rows
        ]


class EpisodeStatsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def save(self, episode_id: int, stats: EpisodeStats) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO english_episode_stats (episode_id, data, updated_at) VALUES (?, ?, ?)",
            (episode_id, json.dumps(stats.as_dict(), ensure_ascii=False), datetime.now().isoformat()),
        )

    def get(self, episode_id: int) -> EpisodeStats | None:
        row = self._conn.execute(
            "SELECT data FROM english_episode_stats WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        return EpisodeStats.from_dict(dict(json.loads(row["data"]))) if row is not None else None


class FilterSettingsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def get(self, scope: str, scope_id: int = 0) -> FilterSettings | None:
        row = self._conn.execute(
            "SELECT * FROM english_filter_settings WHERE scope = ? AND scope_id = ?", (scope, scope_id)
        ).fetchone()
        if row is None:
            return None
        return FilterSettings(
            levels=tuple(str(level) for level in json.loads(row["levels"])),
            include_unleveled=bool(row["include_unleveled"]),
            mwe_mode=row["mwe_mode"],
        )

    def save(self, scope: str, scope_id: int, settings: FilterSettings) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO english_filter_settings (scope, scope_id, levels, include_unleveled, mwe_mode) "
            "VALUES (?, ?, ?, ?, ?)",
            (scope, scope_id, json.dumps(list(settings.levels)), int(settings.include_unleveled), settings.mwe_mode),
        )

    def delete(self, scope: str, scope_id: int) -> bool:
        return (
            self._conn.execute(
                "DELETE FROM english_filter_settings WHERE scope = ? AND scope_id = ?", (scope, scope_id)
            ).rowcount
            > 0
        )


class KeyValueRepository:
    def __init__(self, connection: sqlite3.Connection, table: str) -> None:
        if table not in ("english_settings", "ui_settings"):
            raise ValueError(f"Unknown settings table {table}")
        self._conn = connection
        self._table = table

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(f"SELECT value FROM {self._table} WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row is not None else None

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self._table} (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )


class LearnSessionRepository(AbstractRepository[LearnSession, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: LearnSession) -> int:
        item.started_at = item.started_at or datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO english_learn_sessions (episode_id, settings, started_at, mistakes) VALUES (?, ?, ?, ?)",
            (item.episode_id, json.dumps(item.settings), item.started_at.isoformat(), item.mistakes),
        )
        item.id = int(cursor.lastrowid)
        return item.id

    def get(self, key: int) -> LearnSession | None:
        row = self._conn.execute("SELECT * FROM english_learn_sessions WHERE id = ?", (key,)).fetchone()
        if row is None:
            return None
        return LearnSession(
            id=row["id"],
            episode_id=row["episode_id"],
            settings=dict(json.loads(row["settings"])),
            started_at=_parse_time(row["started_at"]),
            finished_at=_parse_time(row["finished_at"]),
            mistakes=row["mistakes"],
        )

    def finish(self, key: int, mistakes: int) -> None:
        self._conn.execute(
            "UPDATE english_learn_sessions SET finished_at = ?, mistakes = ? WHERE id = ?",
            (datetime.now().isoformat(), mistakes, key),
        )


@dataclass(frozen=True)
class LemmaRecord:
    lemma: str
    correct: int
    wrong: int
    learned: bool


class ReviewRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, entry: ReviewEntry) -> int:
        entry.ts = entry.ts or datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO english_review_log (card_id, session_id, mode, correct, answer, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (entry.card_id, entry.session_id, entry.mode, int(entry.correct), entry.answer, entry.ts.isoformat()),
        )
        entry.id = int(cursor.lastrowid)
        return entry.id

    def mistakes_by_card(self, session_id: int) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT card_id, COUNT(*) AS wrong FROM english_review_log WHERE session_id = ? AND correct = 0 "
            "GROUP BY card_id ORDER BY wrong DESC",
            (session_id,),
        ).fetchall()
        return {row["card_id"]: row["wrong"] for row in rows}

    def count_for_card(self, card_id: int) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM english_review_log WHERE card_id = ?", (card_id,)).fetchone()
        return int(row[0])

    def lemma_records(self) -> list[LemmaRecord]:
        rows = self._conn.execute(
            "SELECT c.lemma AS lemma, SUM(r.correct) AS correct, SUM(1 - r.correct) AS wrong, "
            "MAX(CASE WHEN r.correct = 1 AND r.mode = 'input' THEN 1 ELSE 0 END) AS learned "
            "FROM english_review_log r JOIN english_cards c ON c.id = r.card_id GROUP BY c.lemma"
        ).fetchall()
        return [
            LemmaRecord(
                lemma=row["lemma"], correct=int(row["correct"] or 0), wrong=int(row["wrong"] or 0), learned=bool(row["learned"])
            )
            for row in rows
        ]


class ListeningRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def save(self, episode_id: int, video_path: str, questions: list[dict[str, object]]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO english_listening_quizzes (episode_id, video_path, questions, created_at) "
            "VALUES (?, ?, ?, ?)",
            (episode_id, video_path, json.dumps(questions, ensure_ascii=False), datetime.now().isoformat()),
        )

    def get(self, episode_id: int) -> tuple[str, list[dict[str, object]]] | None:
        row = self._conn.execute(
            "SELECT video_path, questions FROM english_listening_quizzes WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        if row is None:
            return None
        return row["video_path"], list(json.loads(row["questions"]))


@dataclass(frozen=True)
class AssistantThread:
    id: int
    module: str
    scope: str
    scope_id: int
    created_at: datetime


@dataclass(frozen=True)
class AssistantMessage:
    id: int
    thread_id: int
    role: str
    content: str
    meta: dict[str, Any] | None
    ts: datetime


class AssistantRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def create_thread(self, module: str, scope: str, scope_id: int) -> AssistantThread:
        created = datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO assistant_threads (module, scope, scope_id, created_at) VALUES (?, ?, ?, ?)",
            (module, scope, scope_id, created.isoformat()),
        )
        return AssistantThread(int(cursor.lastrowid), module, scope, scope_id, created)

    def get_thread(self, thread_id: int) -> AssistantThread | None:
        row = self._conn.execute("SELECT * FROM assistant_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        return AssistantThread(
            row["id"], row["module"], row["scope"], row["scope_id"], datetime.fromisoformat(row["created_at"])
        )

    def list_threads(self, module: str, scope: str, scope_id: int) -> list[AssistantThread]:
        rows = self._conn.execute(
            "SELECT * FROM assistant_threads WHERE module = ? AND scope = ? AND scope_id = ? ORDER BY id DESC",
            (module, scope, scope_id),
        ).fetchall()
        return [
            AssistantThread(
                row["id"], row["module"], row["scope"], row["scope_id"], datetime.fromisoformat(row["created_at"])
            )
            for row in rows
        ]

    def add_message(self, thread_id: int, role: str, content: str, meta: dict[str, Any] | None = None) -> AssistantMessage:
        ts = datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO assistant_messages (thread_id, role, content, meta, ts) VALUES (?, ?, ?, ?, ?)",
            (thread_id, role, content, json.dumps(meta, ensure_ascii=False) if meta else None, ts.isoformat()),
        )
        return AssistantMessage(int(cursor.lastrowid), thread_id, role, content, meta, ts)

    def messages(self, thread_id: int) -> list[AssistantMessage]:
        rows = self._conn.execute(
            "SELECT * FROM assistant_messages WHERE thread_id = ? ORDER BY id", (thread_id,)
        ).fetchall()
        return [
            AssistantMessage(
                row["id"],
                row["thread_id"],
                row["role"],
                row["content"],
                dict(json.loads(row["meta"])) if row["meta"] else None,
                datetime.fromisoformat(row["ts"]),
            )
            for row in rows
        ]

    def delete_message(self, message_id: int) -> bool:
        return self._conn.execute("DELETE FROM assistant_messages WHERE id = ?", (message_id,)).rowcount > 0
