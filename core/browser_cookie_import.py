from __future__ import annotations

import configparser
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

# Chrome/Chromium's cookie timestamps are microseconds since 1601-01-01
# (Windows FILETIME epoch) — this is the offset (in seconds) to Unix epoch.
_CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600

_FIREFOX_COOKIE_COLUMNS = (
    "originAttributes", "name", "value", "host", "path", "expiry",
    "lastAccessed", "creationTime", "isSecure", "isHttpOnly",
    "inBrowserElement", "sameSite", "schemeMap", "isPartitionedAttributeSet", "updateTime",
)


@dataclass
class CookieRow:
    """Browser-agnostic cookie, normalized enough to write into a Firefox
    automation profile's moz_cookies table regardless of which real browser
    it was read from."""

    host: str
    name: str
    value: str
    path: str
    expiry_unix: int
    is_secure: bool
    is_http_only: bool
    same_site: int  # 0=None, 1=Lax, 2=Strict — matches both Firefox's and Chrome's encoding


@dataclass
class ImportResult:
    source: str  # e.g. "Firefox (snap)" or "Google Chrome" — for the UI/log message
    cookies_written: int
    warnings: list[str]


class NoBrowserSessionFoundError(RuntimeError):
    pass


# --- Firefox: source discovery + plain-text cookies.sqlite -----------------

_FIREFOX_PROFILES_INI_CANDIDATES = (
    "~/.mozilla/firefox/profiles.ini",
    "~/snap/firefox/common/.mozilla/firefox/profiles.ini",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox/profiles.ini",
)


def _firefox_default_profile_dirs() -> list[Path]:
    dirs: list[Path] = []
    for candidate in _FIREFOX_PROFILES_INI_CANDIDATES:
        ini_path = Path(candidate).expanduser()
        if not ini_path.is_file():
            continue
        config = configparser.ConfigParser()
        try:
            config.read(ini_path)
        except configparser.Error:
            logger.debug("Could not parse Firefox profiles.ini at %s", ini_path, exc_info=True)
            continue
        sections = [s for s in config.sections() if s.startswith("Profile")]
        # Prefer the profile explicitly marked Default=1; fall back to the
        # first one found rather than skipping this install entirely.
        chosen = next((s for s in sections if config.get(s, "Default", fallback="0") == "1"), None)
        chosen = chosen or (sections[0] if sections else None)
        if chosen is None:
            continue
        path_value = config.get(chosen, "Path", fallback=None)
        if not path_value:
            continue
        is_relative = config.get(chosen, "IsRelative", fallback="1") == "1"
        profile_dir = (ini_path.parent / path_value) if is_relative else Path(path_value)
        if profile_dir.is_dir():
            dirs.append(profile_dir)
    return dirs


def _copy_sqlite_for_reading(db_path: Path) -> Path:
    """Copies a live browser's cookie DB (plus its -wal file, if any) to a
    throwaway temp location before opening it — the real browser may hold it
    open with an exclusive-ish lock, and this is read-only diagnostics, never
    a write against the user's actual browser profile."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="assistant_cookie_import_"))
    tmp_db = tmp_dir / db_path.name
    shutil.copy2(db_path, tmp_db)
    wal_path = db_path.with_name(db_path.name + "-wal")
    if wal_path.is_file():
        shutil.copy2(wal_path, tmp_db.with_name(tmp_db.name + "-wal"))
    return tmp_db


def _read_firefox_cookies(profile_dir: Path, domain_suffixes: list[str]) -> list[CookieRow]:
    db_path = profile_dir / "cookies.sqlite"
    if not db_path.is_file():
        return []
    tmp_db = _copy_sqlite_for_reading(db_path)
    try:
        con = sqlite3.connect(str(tmp_db))
        try:
            cur = con.cursor()
            clause = " OR ".join("host LIKE ?" for _ in domain_suffixes)
            params = [f"%{d}" for d in domain_suffixes]
            cur.execute(
                f"SELECT host, name, value, path, expiry, isSecure, isHttpOnly, sameSite "
                f"FROM moz_cookies WHERE {clause}",
                params,
            )
            rows = cur.fetchall()
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)

    return [
        CookieRow(
            host=host, name=name, value=value, path=path, expiry_unix=expiry,
            is_secure=bool(is_secure), is_http_only=bool(is_http_only), same_site=same_site or 0,
        )
        for host, name, value, path, expiry, is_secure, is_http_only, same_site in rows
    ]


# --- Chrome/Chromium: source discovery + encrypted Cookies db --------------

_CHROME_PROFILE_ROOTS = (
    "~/.config/google-chrome",
    "~/.config/chromium",
    "~/snap/chromium/common/chromium",
    "~/.var/app/com.google.Chrome/config/google-chrome",
    "~/.var/app/org.chromium.Chromium/config/chromium",
)
_CHROME_PROFILE_SUBDIRS = ("Default", "Profile 1", "Profile 2", "Profile 3")
# The libsecret/keyring item Chrome stores its cookie-encryption password
# under — varies by which of these it is.
_CHROME_KEYRING_LABELS = ("Chrome Safe Storage", "Chromium Safe Storage")
# Chrome's own documented fallback when no keyring backend is reachable at
# all (e.g. a minimal Linux setup with neither GNOME Keyring nor KWallet) —
# not a secret, this is Chrome's literal hardcoded fallback password.
_CHROME_FALLBACK_PASSWORD = "peanuts"


def _chrome_cookie_dbs() -> list[Path]:
    dbs: list[Path] = []
    for root in _CHROME_PROFILE_ROOTS:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        for sub in _CHROME_PROFILE_SUBDIRS:
            db_path = root_path / sub / "Cookies"
            if db_path.is_file():
                dbs.append(db_path)
    return dbs


def _chrome_safe_storage_password() -> str:
    try:
        import secretstorage
    except ImportError:
        logger.debug("secretstorage not available; using Chrome's no-keyring fallback password")
        return _CHROME_FALLBACK_PASSWORD
    try:
        conn = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(conn)
        if collection.is_locked():
            collection.unlock()
        for item in collection.get_all_items():
            if item.get_label() in _CHROME_KEYRING_LABELS:
                return item.get_secret().decode("utf-8")
    except Exception:
        logger.debug("Could not read Chrome's Safe Storage password from the keyring", exc_info=True)
    return _CHROME_FALLBACK_PASSWORD


def _chrome_decrypt(encrypted_value: bytes, key: bytes) -> str | None:
    if not encrypted_value:
        return None
    prefix = encrypted_value[:3]
    if prefix not in (b"v10", b"v11"):
        # Unencrypted (rare, old Chrome) or an unrecognized future scheme —
        # treat as opaque rather than guessing.
        return None
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        iv = b" " * 16
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(encrypted_value[3:]) + decryptor.finalize()
        pad_len = padded[-1]
        return padded[:-pad_len].decode("utf-8")
    except Exception:
        logger.debug("Could not decrypt a Chrome cookie value", exc_info=True)
        return None


def _read_chrome_cookies(db_path: Path, domain_suffixes: list[str]) -> tuple[list[CookieRow], int]:
    """Returns (decrypted rows, count of cookies that matched the domain but
    couldn't be decrypted — surfaced as a warning, never silently dropped)."""
    tmp_db = _copy_sqlite_for_reading(db_path)
    try:
        con = sqlite3.connect(str(tmp_db))
        try:
            cur = con.cursor()
            clause = " OR ".join("host_key LIKE ?" for _ in domain_suffixes)
            params = [f"%{d}" for d in domain_suffixes]
            cur.execute(
                f"SELECT host_key, name, encrypted_value, path, expires_utc, is_secure, "
                f"is_httponly, samesite FROM cookies WHERE {clause}",
                params,
            )
            raw_rows = cur.fetchall()
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)

    if not raw_rows:
        return [], 0

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    password = _chrome_safe_storage_password()
    key = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1).derive(
        password.encode("utf-8")
    )

    rows: list[CookieRow] = []
    undecryptable = 0
    for host, name, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite in raw_rows:
        value = _chrome_decrypt(encrypted_value, key)
        if value is None:
            undecryptable += 1
            continue
        expiry_unix = int(expires_utc / 1_000_000 - _CHROME_EPOCH_OFFSET_SECONDS) if expires_utc else 0
        rows.append(
            CookieRow(
                host=host, name=name, value=value, path=path, expiry_unix=expiry_unix,
                is_secure=bool(is_secure), is_http_only=bool(is_httponly),
                same_site=max(0, samesite or 0),
            )
        )
    return rows, undecryptable


# --- Writing into the destination Firefox automation profile ---------------


def _write_cookies_into_firefox_profile(profile_dir: Path, domain_suffixes: list[str], rows: list[CookieRow]) -> int:
    db_path = profile_dir / "cookies.sqlite"
    if not db_path.is_file():
        raise NoBrowserSessionFoundError(
            f"Профиль автоматизации ещё не инициализирован ({db_path} не найден) — "
            "сначала откройте вход хотя бы один раз, затем повторите импорт."
        )
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        clause = " OR ".join("host LIKE ?" for _ in domain_suffixes)
        params = [f"%{d}" for d in domain_suffixes]
        cur.execute(f"DELETE FROM moz_cookies WHERE {clause}", params)

        now_us = int(time.time() * 1_000_000)
        values = [
            (
                "",  # originAttributes — default container
                row.name, row.value, row.host, row.path, row.expiry_unix,
                now_us, now_us,  # lastAccessed, creationTime
                int(row.is_secure), int(row.is_http_only),
                0, row.same_site, 0, 0,  # inBrowserElement, sameSite, schemeMap, isPartitionedAttributeSet
                now_us,  # updateTime
            )
            for row in rows
        ]
        placeholders = ", ".join("?" for _ in _FIREFOX_COOKIE_COLUMNS)
        cur.executemany(
            f"INSERT INTO moz_cookies ({', '.join(_FIREFOX_COOKIE_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
        con.commit()
        return len(values)
    finally:
        con.close()


# --- Top-level orchestrator --------------------------------------------


def import_session_cookies(automation_profile_dir: Path, domain_suffixes: list[str]) -> ImportResult:
    """Copies session cookies for `domain_suffixes` (e.g. ["quizlet.com"])
    from whichever of the user's real, everyday browsers (Firefox first,
    then Chrome/Chromium) has a matching, already-logged-in session, into
    the given Playwright automation profile — so the automated browser
    reuses a session the user established themselves with an ordinary,
    non-automated login, rather than attempting a fresh one that sites like
    Google/Cloudflare are prone to flag.

    Only ever reads the source browser's cookie DB (via a throwaway copy,
    never the live file) and writes into `automation_profile_dir` — never
    touches the source browser's own profile.
    """
    warnings: list[str] = []

    for profile_dir in _firefox_default_profile_dirs():
        rows = _read_firefox_cookies(profile_dir, domain_suffixes)
        if rows:
            written = _write_cookies_into_firefox_profile(automation_profile_dir, domain_suffixes, rows)
            return ImportResult(source="Firefox", cookies_written=written, warnings=warnings)

    for db_path in _chrome_cookie_dbs():
        rows, undecryptable = _read_chrome_cookies(db_path, domain_suffixes)
        if undecryptable:
            warnings.append(f"Не удалось расшифровать {undecryptable} куки из {db_path}.")
        if rows:
            written = _write_cookies_into_firefox_profile(automation_profile_dir, domain_suffixes, rows)
            browser_label = "Google Chrome" if "chrome" in str(db_path).lower() else "Chromium"
            return ImportResult(source=browser_label, cookies_written=written, warnings=warnings)

    raise NoBrowserSessionFoundError(
        "Не нашёл активную сессию ни в одном браузере на этой машине — сначала войдите "
        "на сайт в своём обычном браузере (Firefox или Chrome), затем повторите импорт."
    )
