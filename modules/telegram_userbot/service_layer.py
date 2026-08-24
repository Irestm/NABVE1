from __future__ import annotations

from core.secret_store import delete_secret, store_secret
from modules.messaging import service_layer as messaging_service_layer
from modules.messaging.domain import WatchedContact
from modules.messaging.uow import MessagingUnitOfWork
from modules.telegram_userbot import client_manager, login
from modules.telegram_userbot.domain import MAX_ACCOUNTS, TelegramAccount
from modules.telegram_userbot.uow import TelegramUserbotUnitOfWork

# Not per-account — see modules/telegram_userbot/client_manager.py's design
# note on SOURCE: whichever account they message you on, a favorite
# contact is a favorite contact. The 5-contact cap is therefore shared
# across every connected account, not 5 each.
MAX_WATCHED_CONTACTS = 5


class TelegramAccountLimitError(RuntimeError):
    pass


class WatchedContactLimitError(RuntimeError):
    pass


def list_accounts() -> list[TelegramAccount]:
    with TelegramUserbotUnitOfWork() as uow:
        return uow.accounts.list_all()


def add_account(label: str, phone_number: str) -> TelegramAccount:
    with TelegramUserbotUnitOfWork() as uow:
        if len(uow.accounts.list_all()) >= MAX_ACCOUNTS:
            raise TelegramAccountLimitError(f"Можно подключить не больше {MAX_ACCOUNTS} аккаунтов.")
        account = TelegramAccount(label=label, phone_number=phone_number)
        account_id = uow.accounts.add(account)
        account.id = account_id
        uow.commit()
        return account


def _account_count() -> int:
    with TelegramUserbotUnitOfWork() as uow:
        return len(uow.accounts.list_all())


async def start_account_login(label: str, phone_number: str) -> str:
    if _account_count() >= MAX_ACCOUNTS:
        raise TelegramAccountLimitError(f"Можно подключить не больше {MAX_ACCOUNTS} аккаунтов.")
    return await login.start_login(label, phone_number)


async def _finish_login(account_label: str, phone_number: str, session_string: str) -> TelegramAccount:
    account = add_account(account_label, phone_number)
    store_secret(account.session_secret_name, session_string)
    await client_manager.connect_account(account)
    return account


async def submit_login_code(token: str, code: str) -> tuple[bool, TelegramAccount | None]:
    """Returns (needs_password, account). needs_password=True means a 2FA
    password must be submitted next (see submit_login_password) — account
    is None in that case, since nothing is persisted until the login
    actually finishes either way. Reads label/phone_number BEFORE calling
    login.submit_code, since a successful call cleans up the pending entry
    those live on (see login.pending_login_info's own docstring)."""
    info = login.pending_login_info(token)
    account_label, phone_number = info if info is not None else ("", "")
    done, session_string = await login.submit_code(token, code)
    if not done:
        return True, None
    account = await _finish_login(account_label, phone_number, session_string)
    return False, account


async def submit_login_password(token: str, password: str) -> TelegramAccount:
    info = login.pending_login_info(token)
    account_label, phone_number = info if info is not None else ("", "")
    session_string = await login.submit_password(token, password)
    return await _finish_login(account_label, phone_number, session_string)


async def remove_account(account_id: int) -> bool:
    with TelegramUserbotUnitOfWork() as uow:
        account = uow.accounts.get(account_id)
    await client_manager.disconnect_account(account_id)
    if account is not None:
        delete_secret(account.session_secret_name)
    with TelegramUserbotUnitOfWork() as uow:
        removed = uow.accounts.delete(account_id)
        uow.commit()
        return removed


def is_account_connected(account_id: int) -> bool:
    return account_id in client_manager.connected_account_ids()


def list_watched_contacts() -> list[WatchedContact]:
    # messaging_service_layer's functions each own their own `with uow:`
    # lifecycle (open/commit-or-rollback/close) — pass a fresh, not-yet-
    # entered MessagingUnitOfWork() into each call, never wrap one of our
    # own around them, or the inner call's __exit__ closes the connection
    # out from under an outer `with` block still expecting it open.
    contacts = messaging_service_layer.list_watched_contacts(MessagingUnitOfWork())
    return [c for c in contacts if c.source == client_manager.SOURCE]


def add_watched_contact(identifier: str, note: str = "") -> int:
    if len(list_watched_contacts()) >= MAX_WATCHED_CONTACTS:
        raise WatchedContactLimitError(f"Можно отслеживать не больше {MAX_WATCHED_CONTACTS} контактов.")
    return messaging_service_layer.add_watched_contact(
        MessagingUnitOfWork(), client_manager.SOURCE, identifier, note
    )
