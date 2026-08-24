from __future__ import annotations

from modules.telegram_userbot.domain import TelegramAccount
from modules.telegram_userbot.uow import TelegramUserbotUnitOfWork


def test_add_then_get_round_trips(tmp_path) -> None:
    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        account_id = uow.accounts.add(TelegramAccount(label="Личный", phone_number="+1000"))
        uow.commit()

    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        fetched = uow.accounts.get(account_id)

    assert fetched is not None
    assert fetched.label == "Личный"
    assert fetched.phone_number == "+1000"
    assert fetched.session_secret_name == f"telegram_userbot_session_{account_id}"


def test_list_all_returns_every_account_oldest_first(tmp_path) -> None:
    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        uow.accounts.add(TelegramAccount(label="Первый", phone_number="+1"))
        uow.accounts.add(TelegramAccount(label="Второй", phone_number="+2"))
        uow.commit()

    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        accounts = uow.accounts.list_all()

    assert [a.label for a in accounts] == ["Первый", "Второй"]


def test_delete_removes_the_row(tmp_path) -> None:
    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        account_id = uow.accounts.add(TelegramAccount(label="X", phone_number="+1"))
        uow.commit()

    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        deleted = uow.accounts.delete(account_id)
        uow.commit()

    assert deleted is True
    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert uow.accounts.get(account_id) is None


def test_delete_returns_false_for_unknown_id(tmp_path) -> None:
    with TelegramUserbotUnitOfWork(db_path=tmp_path / "state.db") as uow:
        assert uow.accounts.delete(999) is False
