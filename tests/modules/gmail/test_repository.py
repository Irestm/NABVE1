from __future__ import annotations

from modules.gmail.uow import GmailUnitOfWork


def test_get_last_history_id_returns_none_when_never_set(tmp_path) -> None:
    with GmailUnitOfWork(tmp_path / "assistant.db") as uow:
        assert uow.sync_state.get_last_history_id() is None


def test_set_then_get_last_history_id_round_trips(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.set_last_history_id("12345")
        uow.commit()

    with GmailUnitOfWork(db_path) as uow:
        assert uow.sync_state.get_last_history_id() == "12345"


def test_set_last_history_id_overwrites_previous_value(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.set_last_history_id("111")
        uow.commit()

    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.set_last_history_id("222")
        uow.commit()

    with GmailUnitOfWork(db_path) as uow:
        assert uow.sync_state.get_last_history_id() == "222"


def test_processed_message_ids_starts_empty(tmp_path) -> None:
    with GmailUnitOfWork(tmp_path / "assistant.db") as uow:
        assert uow.sync_state.get_processed_message_ids() == set()


def test_add_processed_message_id_accumulates(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.add_processed_message_id("m1")
        uow.commit()
    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.add_processed_message_id("m2")
        uow.commit()

    with GmailUnitOfWork(db_path) as uow:
        assert uow.sync_state.get_processed_message_ids() == {"m1", "m2"}


def test_set_last_history_id_and_clear_processed_clears_the_set(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.add_processed_message_id("m1")
        uow.commit()

    with GmailUnitOfWork(db_path) as uow:
        uow.sync_state.set_last_history_id_and_clear_processed("500")
        uow.commit()

    with GmailUnitOfWork(db_path) as uow:
        assert uow.sync_state.get_last_history_id() == "500"
        assert uow.sync_state.get_processed_message_ids() == set()
