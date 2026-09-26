from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from core.ports import AbstractRepository
from modules.english_learning.domain import Card, Episode, EpisodeWord, LearnSession, ReviewEntry, Series


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_series(row: sqlite3.Row) -> Series:
    return Series(
        id=row["id"],
        title=row["title"],
        imdb_id=row["imdb_id"],
        tmdb_id=row["tmdb_id"],
        created_at=_parse_time(row["created_at"]),
    )


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        series_id=row["series_id"],
        season=row["season"],
        episode=row["episode"],
        title=row["title"],
        source=row["source"],
        srt_path=row["srt_path"],
        created_at=_parse_time(row["created_at"]),
    )


def _row_to_word(row: sqlite3.Row) -> EpisodeWord:
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
    )


class SeriesRepository(AbstractRepository[Series, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: Series) -> int:
        item.created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO english_series (title, imdb_id, tmdb_id, created_at) VALUES (?, ?, ?, ?)",
            (item.title, item.imdb_id, item.tmdb_id, item.created_at.isoformat()),
        )
        item.id = int(cursor.lastrowid)
        return item.id

    def get(self, key: int) -> Series | None:
        row = self._conn.execute("SELECT * FROM english_series WHERE id = ?", (key,)).fetchone()
        return _row_to_series(row) if row is not None else None

    def find(self, *, imdb_id: str | None, title: str) -> Series | None:
        if imdb_id:
            row = self._conn.execute("SELECT * FROM english_series WHERE imdb_id = ?", (imdb_id,)).fetchone()
            if row is not None:
                return _row_to_series(row)
        row = self._conn.execute(
            "SELECT * FROM english_series WHERE lower(title) = lower(?) ORDER BY id LIMIT 1", (title,)
        ).fetchone()
        return _row_to_series(row) if row is not None else None

    def list_all(self) -> list[Series]:
        rows = self._conn.execute("SELECT * FROM english_series ORDER BY lower(title)").fetchall()
        return [_row_to_series(row) for row in rows]

    def delete(self, key: int) -> bool:
        return self._conn.execute("DELETE FROM english_series WHERE id = ?", (key,)).rowcount > 0


class EpisodeRepository(AbstractRepository[Episode, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: Episode) -> int:
        item.created_at = item.created_at or datetime.now()
        cursor = self._conn.execute(
            "INSERT INTO english_episodes (series_id, season, episode, title, source, srt_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.series_id,
                item.season,
                item.episode,
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

    def find(self, series_id: int, season: int, episode: int) -> Episode | None:
        row = self._conn.execute(
            "SELECT * FROM english_episodes WHERE series_id = ? AND season = ? AND episode = ?",
            (series_id, season, episode),
        ).fetchone()
        return _row_to_episode(row) if row is not None else None

    def list_for_series(self, series_id: int) -> list[Episode]:
        rows = self._conn.execute(
            "SELECT * FROM english_episodes WHERE series_id = ? ORDER BY season, episode", (series_id,)
        ).fetchall()
        return [_row_to_episode(row) for row in rows]

    def update(self, item: Episode) -> None:
        if item.id is None:
            raise ValueError("Episode has no id")
        self._conn.execute(
            "UPDATE english_episodes SET title = ?, source = ?, srt_path = ? WHERE id = ?",
            (item.title, item.source, item.srt_path, item.id),
        )

    def delete(self, key: int) -> bool:
        return self._conn.execute("DELETE FROM english_episodes WHERE id = ?", (key,)).rowcount > 0


class EpisodeWordRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def replace_for_episode(self, episode_id: int, words: Iterable[EpisodeWord]) -> None:
        self._conn.execute("DELETE FROM english_episode_words WHERE episode_id = ?", (episode_id,))
        self._conn.executemany(
            "INSERT INTO english_episode_words "
            "(episode_id, lemma, pos, cefr, category, count, example, timestamp_ms, surface) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    episode_id,
                    word.lemma,
                    word.pos,
                    word.cefr,
                    word.category,
                    word.count,
                    word.example,
                    word.timestamp_ms,
                    word.surface,
                )
                for word in words
            ],
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


class CardRepository(AbstractRepository[Card, int]):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, item: Card) -> int:
        cursor = self._conn.execute(
            "INSERT INTO english_cards "
            "(episode_id, word, lemma, pos, cefr, translations_ru, definition_en, example, timestamp_ms, category) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
            ),
        )
        item.id = int(cursor.lastrowid)
        return item.id

    def get(self, key: int) -> Card | None:
        row = self._conn.execute("SELECT * FROM english_cards WHERE id = ?", (key,)).fetchone()
        return _row_to_card(row) if row is not None else None

    def list_for_episode(self, episode_id: int) -> list[Card]:
        rows = self._conn.execute("SELECT * FROM english_cards WHERE episode_id = ? ORDER BY id", (episode_id,)).fetchall()
        return [_row_to_card(row) for row in rows]

    def count_for_episode(self, episode_id: int) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM english_cards WHERE episode_id = ?", (episode_id,)).fetchone()
        return int(row[0])

    def existing_keys(self, episode_id: int) -> set[tuple[str, str]]:
        rows = self._conn.execute("SELECT lemma, pos FROM english_cards WHERE episode_id = ?", (episode_id,)).fetchall()
        return {(row["lemma"], row["pos"]) for row in rows}

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
