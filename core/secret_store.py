from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_ATTRIBUTE = "application"
_SCHEMA_VALUE = "nabve"


class SecretStoreUnavailableError(RuntimeError):
    pass


def _attributes(name: str) -> dict[str, str]:
    return {_SCHEMA_ATTRIBUTE: _SCHEMA_VALUE, "name": name}


def _unlocked_collection():
    try:
        import secretstorage
    except ImportError as exc:
        raise SecretStoreUnavailableError(
            "Модуль secretstorage не установлен — системное хранилище секретов недоступно."
        ) from exc
    try:
        connection = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(connection)
        if collection.is_locked():
            collection.unlock()
        return collection
    except Exception as exc:
        raise SecretStoreUnavailableError(
            "Не удалось открыть системное хранилище секретов — нет запущенного keyring/D-Bus."
        ) from exc


def store_secret(name: str, value: str) -> None:
    collection = _unlocked_collection()
    attributes = _attributes(name)
    for item in collection.get_all_items():
        if item.get_attributes() == attributes:
            item.delete()
    collection.create_item(f"NABVE secret: {name}", attributes, value)


def get_secret(name: str) -> str | None:
    try:
        collection = _unlocked_collection()
    except SecretStoreUnavailableError:
        logger.exception("Secret store unavailable while reading %r", name)
        return None
    attributes = _attributes(name)
    for item in collection.get_all_items():
        if item.get_attributes() == attributes:
            return item.get_secret().decode("utf-8")
    return None


def delete_secret(name: str) -> None:
    collection = _unlocked_collection()
    attributes = _attributes(name)
    for item in collection.get_all_items():
        if item.get_attributes() == attributes:
            item.delete()
