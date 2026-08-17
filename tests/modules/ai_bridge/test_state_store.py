from __future__ import annotations

from modules.ai_bridge.state_store import StateStore


def test_get_returns_none_for_unknown_key(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")

    assert store.get("missing") is None


def test_set_then_get_round_trips(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")

    store.set("active_provider", "gemini")

    assert store.get("active_provider") == "gemini"


def test_set_overwrites_existing_value(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.set("active_provider", "gemini")

    store.set("active_provider", "chatgpt")

    assert store.get("active_provider") == "chatgpt"


def test_repeated_calls_do_not_leak_connections(tmp_path) -> None:
    # Regression test: get()/set()/__init__ used to open a sqlite3.Connection
    # per call via `with self._connect() as conn: ...` — that context manager
    # only commits/rolls back, it never calls conn.close(), so every call
    # leaked a connection relying on GC to eventually clean it up. A high
    # call count finishing without error is the practical signal that
    # connections are now actually being closed rather than accumulating.
    store = StateStore(tmp_path / "state.db")
    for i in range(500):
        store.set("key", str(i))
        assert store.get("key") == str(i)
