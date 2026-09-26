from __future__ import annotations

import sqlite3

_VERSION_TABLE = "english_schema_version"

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE english_series (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        imdb_id TEXT UNIQUE,
        tmdb_id INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE TABLE english_episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        series_id INTEGER NOT NULL REFERENCES english_series(id) ON DELETE CASCADE,
        season INTEGER NOT NULL,
        episode INTEGER NOT NULL,
        title TEXT,
        source TEXT NOT NULL,
        srt_path TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (series_id, season, episode)
    );
    CREATE TABLE english_episode_words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER NOT NULL REFERENCES english_episodes(id) ON DELETE CASCADE,
        lemma TEXT NOT NULL,
        pos TEXT NOT NULL,
        cefr TEXT,
        category TEXT NOT NULL,
        count INTEGER NOT NULL,
        example TEXT NOT NULL,
        timestamp_ms INTEGER NOT NULL,
        surface TEXT NOT NULL,
        UNIQUE (episode_id, lemma, pos)
    );
    CREATE TABLE english_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER NOT NULL REFERENCES english_episodes(id) ON DELETE CASCADE,
        word TEXT NOT NULL,
        lemma TEXT NOT NULL,
        pos TEXT NOT NULL,
        cefr TEXT,
        translations_ru TEXT NOT NULL,
        definition_en TEXT NOT NULL,
        example TEXT NOT NULL,
        timestamp_ms INTEGER NOT NULL,
        category TEXT NOT NULL
    );
    CREATE TABLE english_learn_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER NOT NULL REFERENCES english_episodes(id) ON DELETE CASCADE,
        settings TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        mistakes INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE english_review_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL REFERENCES english_cards(id) ON DELETE CASCADE,
        session_id INTEGER REFERENCES english_learn_sessions(id) ON DELETE SET NULL,
        mode TEXT NOT NULL,
        correct INTEGER NOT NULL,
        answer TEXT NOT NULL,
        ts TEXT NOT NULL
    );
    CREATE TABLE english_cefr_words (
        headword TEXT NOT NULL,
        pos TEXT NOT NULL,
        level TEXT NOT NULL,
        PRIMARY KEY (headword, pos)
    );
    CREATE INDEX english_cards_episode ON english_cards(episode_id);
    CREATE INDEX english_review_card ON english_review_log(card_id);
    """,
)


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_VERSION_TABLE} (version INTEGER NOT NULL)")
    row = conn.execute(f"SELECT MAX(version) FROM {_VERSION_TABLE}").fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def migrate(conn: sqlite3.Connection) -> int:
    version = current_version(conn)
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN;\n{script}\nINSERT INTO {_VERSION_TABLE} (version) VALUES ({number});\nCOMMIT;")
    return len(MIGRATIONS)
