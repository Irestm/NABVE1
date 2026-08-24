from __future__ import annotations

import secrets

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from core.logger import get_logger
from core.secret_store import get_secret, store_secret

logger = get_logger(__name__)

API_ID_SECRET_NAME = "telegram_api_id"
API_HASH_SECRET_NAME = "telegram_api_hash"

# A phone -> code -> [2FA password] login needs one *live, connected*
# TelegramClient held across separate HTTP requests until the flow
# finishes — same in-memory-pending-state idea as
# modules/spotify_control/oauth.py's PKCE login, just holding a live
# connection instead of a code_verifier string. Losing this on a process
# restart just means starting the login over, not a correctness problem.
_PENDING_LOGIN_TTL_SECONDS = 600.0


class TelegramLoginError(RuntimeError):
    pass


def get_app_credentials() -> tuple[int, str] | None:
    api_id = get_secret(API_ID_SECRET_NAME)
    api_hash = get_secret(API_HASH_SECRET_NAME)
    if not api_id or not api_hash:
        return None
    return int(api_id), api_hash


def store_app_credentials(api_id: int, api_hash: str) -> None:
    store_secret(API_ID_SECRET_NAME, str(api_id))
    store_secret(API_HASH_SECRET_NAME, api_hash)


class _PendingLogin:
    def __init__(self, client: TelegramClient, label: str, phone_number: str, phone_code_hash: str) -> None:
        self.client = client
        self.label = label
        self.phone_number = phone_number
        self.phone_code_hash = phone_code_hash


_pending_logins: dict[str, _PendingLogin] = {}


def pending_login_info(token: str) -> tuple[str, str] | None:
    """(label, phone_number) for a still-open login, or None if the token
    is unknown/already finished — read this BEFORE calling submit_code/
    submit_password, since a successful call cleans the pending entry up."""
    pending = _pending_logins.get(token)
    return (pending.label, pending.phone_number) if pending is not None else None


async def start_login(label: str, phone_number: str) -> str:
    credentials = get_app_credentials()
    if credentials is None:
        raise TelegramLoginError(
            "Сначала укажите api_id/api_hash с my.telegram.org/apps в Настройках → Интеграции."
        )
    api_id, api_hash = credentials

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        sent = await client.send_code_request(phone_number)
    except Exception as exc:
        await client.disconnect()
        raise TelegramLoginError(f"Не удалось отправить код: {exc}") from exc

    token = secrets.token_urlsafe(16)
    _pending_logins[token] = _PendingLogin(client, label, phone_number, sent.phone_code_hash)
    return token


async def _cleanup(token: str) -> None:
    pending = _pending_logins.pop(token, None)
    if pending is not None:
        await pending.client.disconnect()


async def submit_code(token: str, code: str) -> tuple[bool, str]:
    """Returns (done, session_string). done=False (with an empty session
    string) means a 2FA password is required next — see submit_password."""
    pending = _pending_logins.get(token)
    if pending is None:
        raise TelegramLoginError("Сессия входа устарела — начните заново.")
    try:
        await pending.client.sign_in(pending.phone_number, code, phone_code_hash=pending.phone_code_hash)
    except SessionPasswordNeededError:
        return False, ""
    except Exception as exc:
        await _cleanup(token)
        raise TelegramLoginError(f"Не удалось подтвердить код: {exc}") from exc

    session_string = pending.client.session.save()
    await _cleanup(token)
    return True, session_string


async def submit_password(token: str, password: str) -> str:
    pending = _pending_logins.get(token)
    if pending is None:
        raise TelegramLoginError("Сессия входа устарела — начните заново.")
    try:
        await pending.client.sign_in(password=password)
    except Exception as exc:
        await _cleanup(token)
        raise TelegramLoginError(f"Не удалось подтвердить пароль: {exc}") from exc

    session_string = pending.client.session.save()
    await _cleanup(token)
    return session_string
