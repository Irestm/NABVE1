from __future__ import annotations

import sqlite3
from pathlib import Path

from modules.english_learning.migrations import MIGRATIONS, _VERSION_TABLE, migrate
from modules.english_learning.uow import EnglishUnitOfWork


def _legacy_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {_VERSION_TABLE} (version INTEGER NOT NULL)")
    for number, script in enumerate(MIGRATIONS[:2], start=1):
        conn.executescript(f"BEGIN;\n{script}\nINSERT INTO {_VERSION_TABLE} (version) VALUES ({number});\nCOMMIT;")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO english_series (id, title, imdb_id, tmdb_id, created_at) "
        "VALUES (5, 'Breaking Bad', 'tt0903747', 1396, '2026-09-01T10:00:00')"
    )
    conn.execute(
        "INSERT INTO english_episodes (id, series_id, season, episode, title, source, srt_path, created_at) "
        "VALUES (9, 5, 1, 2, 'Cat in the Bag', 'opensubtitles', '/x.srt', '2026-09-01T10:00:00')"
    )
    conn.execute(
        "INSERT INTO english_episode_words (episode_id, lemma, pos, cefr, category, count, example, timestamp_ms, "
        "surface) VALUES (9, 'figure', 'VERB', 'B1', 'core', 2, 'I figured.', 1000, 'figured')"
    )
    conn.execute(
        "INSERT INTO english_cards (id, episode_id, word, lemma, pos, cefr, translations_ru, definition_en, example, "
        "timestamp_ms, category) VALUES (3, 9, 'figure out', 'figure', 'VERB', 'B1', '[\"понять\"]', 'x', 'e', 1, 'core')"
    )
    conn.execute(
        "INSERT INTO english_learn_sessions (id, episode_id, settings, started_at) VALUES (4, 9, '{}', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO english_review_log (card_id, session_id, mode, correct, answer, ts) "
        "VALUES (3, 4, 'input', 1, 'понять', '2026-09-01')"
    )
    conn.commit()
    conn.close()


def test_migration_moves_series_to_titles_without_losing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _legacy_db(db_path)

    with EnglishUnitOfWork(db_path) as uow:
        titles = uow.titles.list_all()
        episodes = uow.episodes.list_for_title(5)
        words = uow.words.list_for_episode(9)
        cards = uow.cards.list_for_episode(9)
        reviews = uow.reviews.count_for_card(3)
        session = uow.sessions.get(4)

    assert [(t.id, t.kind, t.name, t.imdb_id, t.tmdb_id) for t in titles] == [
        (5, "series", "Breaking Bad", "tt0903747", 1396)
    ]
    assert [(e.id, e.code, e.title, e.source, e.part) for e in episodes] == [
        (9, "S01E02", "Cat in the Bag", "opensubtitles", None)
    ]
    assert [(w.lemma, w.kind, w.examples) for w in words] == [("figure", "word", [])]
    assert [(c.id, c.kind, c.cefr_source, c.archived) for c in cards] == [(3, "word", "list", False)]
    assert reviews == 1
    assert session is not None and session.episode_id == 9


def test_migrated_foreign_keys_still_cascade(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _legacy_db(db_path)

    with EnglishUnitOfWork(db_path) as uow:
        uow.titles.delete(5)
        uow.commit()
        assert uow.episodes.get(9) is None
        assert uow.cards.get(3) is None
        assert uow.reviews.count_for_card(3) == 0


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    assert migrate(conn) == len(MIGRATIONS)
    assert migrate(conn) == len(MIGRATIONS)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0


def test_movie_parts_are_distinct_slots(tmp_path: Path) -> None:
    from modules.english_learning.domain import Episode, Title

    with EnglishUnitOfWork(tmp_path / "db.sqlite") as uow:
        title = Title(name="Sherlock Holmes", kind="movie", year=2009)
        uow.titles.add(title)
        assert title.id is not None
        for part, (start, end) in enumerate(((0, 1_214_000), (1_214_000, 2_400_000)), start=1):
            uow.episodes.add(Episode(title_id=title.id, source="manual", part=part, start_ms=start, end_ms=end))
        uow.commit()
        parts = uow.episodes.list_for_title(title.id)
        assert [p.code for p in parts] == ["Часть 1 · 00:00–20:14", "Часть 2 · 20:14–40:00"]
        assert uow.episodes.find(title.id, None, None, 2) is not None
        assert uow.titles.get(title.id).display_name == "Sherlock Holmes (2009)"  # type: ignore[union-attr]
