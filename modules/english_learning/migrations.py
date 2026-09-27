from __future__ import annotations

import sqlite3

from core.logger import get_logger

logger = get_logger(__name__)

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
    """
    CREATE TABLE english_listening_quizzes (
        episode_id INTEGER PRIMARY KEY REFERENCES english_episodes(id) ON DELETE CASCADE,
        video_path TEXT NOT NULL,
        questions TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE english_titles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL DEFAULT 'series',
        name TEXT NOT NULL,
        year INTEGER,
        imdb_id TEXT UNIQUE,
        tmdb_id INTEGER,
        created_at TEXT NOT NULL
    );
    INSERT INTO english_titles (id, kind, name, year, imdb_id, tmdb_id, created_at)
        SELECT id, 'series', title, NULL, imdb_id, tmdb_id, created_at FROM english_series;
    CREATE TABLE english_episodes_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title_id INTEGER NOT NULL REFERENCES english_titles(id) ON DELETE CASCADE,
        season INTEGER,
        episode INTEGER,
        part INTEGER,
        start_ms INTEGER,
        end_ms INTEGER,
        title TEXT,
        source TEXT NOT NULL,
        srt_path TEXT,
        created_at TEXT NOT NULL
    );
    INSERT INTO english_episodes_v3
        (id, title_id, season, episode, part, start_ms, end_ms, title, source, srt_path, created_at)
        SELECT id, series_id, season, episode, NULL, NULL, NULL, title, source, srt_path, created_at
        FROM english_episodes;
    DROP TABLE english_episodes;
    ALTER TABLE english_episodes_v3 RENAME TO english_episodes;
    DROP TABLE english_series;
    CREATE UNIQUE INDEX english_episodes_slot ON english_episodes
        (title_id, IFNULL(season, -1), IFNULL(episode, -1), IFNULL(part, -1));

    ALTER TABLE english_episode_words ADD COLUMN kind TEXT NOT NULL DEFAULT 'word';
    ALTER TABLE english_episode_words ADD COLUMN examples TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE english_episode_words ADD COLUMN cefr_source TEXT;
    ALTER TABLE english_episode_words ADD COLUMN confidence REAL;
    ALTER TABLE english_episode_words ADD COLUMN details TEXT;

    ALTER TABLE english_cards ADD COLUMN kind TEXT NOT NULL DEFAULT 'word';
    ALTER TABLE english_cards ADD COLUMN surface_form TEXT;
    ALTER TABLE english_cards ADD COLUMN sense_label TEXT;
    ALTER TABLE english_cards ADD COLUMN literal_translation TEXT;
    ALTER TABLE english_cards ADD COLUMN cefr_source TEXT;
    ALTER TABLE english_cards ADD COLUMN confidence REAL;
    ALTER TABLE english_cards ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
    UPDATE english_cards SET cefr_source = 'list' WHERE cefr IS NOT NULL;

    CREATE TABLE english_mwe_lexicon (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expression TEXT NOT NULL,
        normalized TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        cefr TEXT,
        source TEXT NOT NULL
    );
    CREATE TABLE english_ai_expressions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER NOT NULL REFERENCES english_episodes(id) ON DELETE CASCADE,
        cue_index INTEGER NOT NULL,
        surface_form TEXT NOT NULL,
        normalized TEXT NOT NULL,
        kind TEXT NOT NULL,
        meaning_en TEXT NOT NULL,
        translations_ru TEXT NOT NULL,
        literal_translation TEXT,
        cefr_estimate TEXT,
        confidence REAL NOT NULL
    );
    CREATE INDEX english_ai_expressions_episode ON english_ai_expressions(episode_id);
    CREATE TABLE english_episode_stats (
        episode_id INTEGER PRIMARY KEY REFERENCES english_episodes(id) ON DELETE CASCADE,
        data TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE english_filter_settings (
        scope TEXT NOT NULL,
        scope_id INTEGER NOT NULL DEFAULT 0,
        levels TEXT NOT NULL,
        include_unleveled INTEGER NOT NULL,
        mwe_mode TEXT NOT NULL,
        PRIMARY KEY (scope, scope_id)
    );
    CREATE TABLE english_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE ui_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE assistant_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module TEXT NOT NULL,
        scope TEXT NOT NULL,
        scope_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX assistant_threads_scope ON assistant_threads(module, scope, scope_id);
    CREATE TABLE assistant_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL REFERENCES assistant_threads(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        meta TEXT,
        ts TEXT NOT NULL
    );
    CREATE INDEX assistant_messages_thread ON assistant_messages(thread_id);
    """,
)


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_VERSION_TABLE} (version INTEGER NOT NULL)")
    row = conn.execute(f"SELECT MAX(version) FROM {_VERSION_TABLE}").fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def migrate(conn: sqlite3.Connection) -> int:
    version = current_version(conn)
    if version >= len(MIGRATIONS):
        return len(MIGRATIONS)
    foreign_keys = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.executescript(f"BEGIN;\n{script}\nINSERT INTO {_VERSION_TABLE} (version) VALUES ({number});\nCOMMIT;")
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            logger.warning("English DB has %d rows with dangling references after migration", len(broken))
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return len(MIGRATIONS)
