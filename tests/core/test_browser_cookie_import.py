from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from core import browser_cookie_import as bci

_FIREFOX_SCHEMA = """
CREATE TABLE moz_cookies (
    id INTEGER PRIMARY KEY,
    originAttributes TEXT DEFAULT '',
    name TEXT,
    value TEXT,
    host TEXT,
    path TEXT,
    expiry INTEGER,
    lastAccessed INTEGER,
    creationTime INTEGER,
    isSecure INTEGER,
    isHttpOnly INTEGER,
    inBrowserElement INTEGER DEFAULT 0,
    sameSite INTEGER DEFAULT 0,
    schemeMap INTEGER DEFAULT 0,
    isPartitionedAttributeSet INTEGER DEFAULT 0,
    updateTime INTEGER
);
"""

_CHROME_SCHEMA = """
CREATE TABLE cookies (
    creation_utc INTEGER,
    host_key TEXT,
    name TEXT,
    encrypted_value BLOB,
    path TEXT,
    expires_utc INTEGER,
    is_secure INTEGER,
    is_httponly INTEGER,
    samesite INTEGER
);
"""


def _make_firefox_cookies_db(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(str(path))
    con.execute(_FIREFOX_SCHEMA)
    con.executemany(
        "INSERT INTO moz_cookies (originAttributes, name, value, host, path, expiry, "
        "lastAccessed, creationTime, isSecure, isHttpOnly, sameSite) "
        "VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()


def test_firefox_default_profile_dirs_reads_profiles_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_dir = tmp_path / "abcd1234.default-release"
    profile_dir.mkdir()
    ini_path = tmp_path / "profiles.ini"
    ini_path.write_text(
        "[Profile0]\nName=default\nIsRelative=1\nPath=abcd1234.default-release\nDefault=1\n"
    )
    monkeypatch.setattr(bci, "_FIREFOX_PROFILES_INI_CANDIDATES", (str(ini_path),))

    dirs = bci._firefox_default_profile_dirs()

    assert dirs == [profile_dir]


def test_firefox_default_profile_dirs_skips_missing_ini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bci, "_FIREFOX_PROFILES_INI_CANDIDATES", ("/nonexistent/profiles.ini",))

    assert bci._firefox_default_profile_dirs() == []


def test_read_firefox_cookies_filters_by_domain(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    now = int(time.time())
    _make_firefox_cookies_db(
        profile_dir / "cookies.sqlite",
        [
            ("session", "abc123", ".quizlet.com", "/", now + 3600, now, now, 1, 0, 0),
            ("session", "xyz789", ".unrelated.com", "/", now + 3600, now, now, 1, 0, 0),
        ],
    )

    rows = bci._read_firefox_cookies(profile_dir, ["quizlet.com"])

    assert len(rows) == 1
    assert rows[0].host == ".quizlet.com"
    assert rows[0].name == "session"
    assert rows[0].value == "abc123"


def test_read_firefox_cookies_missing_db_returns_empty(tmp_path: Path) -> None:
    assert bci._read_firefox_cookies(tmp_path, ["quizlet.com"]) == []


def test_write_cookies_into_firefox_profile_replaces_existing(tmp_path: Path) -> None:
    profile_dir = tmp_path / "automation_profile"
    profile_dir.mkdir()
    now = int(time.time())
    _make_firefox_cookies_db(
        profile_dir / "cookies.sqlite",
        [("stale", "old-value", ".quizlet.com", "/", now + 3600, now, now, 1, 0, 0)],
    )

    rows = [
        bci.CookieRow(
            host=".quizlet.com", name="cf_clearance", value="fresh-value", path="/",
            expiry_unix=now + 7200, is_secure=True, is_http_only=True, same_site=1,
        )
    ]
    written = bci._write_cookies_into_firefox_profile(profile_dir, ["quizlet.com"], rows)

    assert written == 1
    con = sqlite3.connect(str(profile_dir / "cookies.sqlite"))
    result = con.execute("SELECT name, value FROM moz_cookies").fetchall()
    con.close()
    assert result == [("cf_clearance", "fresh-value")]


def test_write_cookies_into_firefox_profile_raises_without_a_bootstrapped_profile(tmp_path: Path) -> None:
    with pytest.raises(bci.NoBrowserSessionFoundError):
        bci._write_cookies_into_firefox_profile(tmp_path, ["quizlet.com"], [])


def test_chrome_decrypt_round_trip() -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    password = "peanuts"
    key = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1).derive(
        password.encode("utf-8")
    )
    plaintext = b"my-secret-session-cookie"
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([pad_len]) * pad_len
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
    encryptor = cipher.encryptor()
    encrypted = b"v10" + encryptor.update(padded) + encryptor.finalize()

    result = bci._chrome_decrypt(encrypted, key)

    assert result == "my-secret-session-cookie"


def test_chrome_decrypt_returns_none_for_unrecognized_prefix() -> None:
    assert bci._chrome_decrypt(b"v99somejunkvalue", b"\x00" * 16) is None


def test_chrome_decrypt_returns_none_for_empty_value() -> None:
    assert bci._chrome_decrypt(b"", b"\x00" * 16) is None


def test_import_session_cookies_prefers_firefox_over_chrome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    automation_profile = tmp_path / "automation"
    automation_profile.mkdir()
    (automation_profile / "cookies.sqlite").touch()
    _make_firefox_cookies_db(automation_profile / "cookies.sqlite", [])

    firefox_row = bci.CookieRow(
        host=".quizlet.com", name="session", value="ff", path="/",
        expiry_unix=int(time.time()) + 3600, is_secure=True, is_http_only=True, same_site=1,
    )
    monkeypatch.setattr(bci, "_firefox_default_profile_dirs", lambda: [tmp_path / "irrelevant"])
    monkeypatch.setattr(bci, "_read_firefox_cookies", lambda profile_dir, domains: [firefox_row])
    monkeypatch.setattr(bci, "_chrome_cookie_dbs", lambda: (_ for _ in ()).throw(AssertionError("should not reach Chrome")))

    result = bci.import_session_cookies(automation_profile, ["quizlet.com"])

    assert result.source == "Firefox"
    assert result.cookies_written == 1


def test_import_session_cookies_raises_when_nothing_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bci, "_firefox_default_profile_dirs", lambda: [])
    monkeypatch.setattr(bci, "_chrome_cookie_dbs", lambda: [])

    with pytest.raises(bci.NoBrowserSessionFoundError):
        bci.import_session_cookies(tmp_path, ["quizlet.com"])
