from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_ATTRIBUTE = "application"
_SCHEMA_VALUE = "nabve"


class SecretStoreUnavailableError(RuntimeError):
    pass


def _attributes(name: str) -> dict[str, str]:
    return {_SCHEMA_ATTRIBUTE: _SCHEMA_VALUE, "name": name}


def _matches(item, attributes: dict[str, str]) -> bool:
    """libsecret/secretstorage silently adds its own 'xdg:schema' attribute
    to every item's attribute dict on creation, on top of whatever we pass
    to create_item - comparing item.get_attributes() == attributes (exact
    dict equality) then NEVER matches, since the item always carries that
    one extra key we never put there ourselves. The practical effect: every
    secret this module ever stored (Gemini/Claude API keys, YouTube/GitHub
    tokens, ...) saved successfully but could never be read back or
    overwritten - each "save" silently piled up a new duplicate item
    instead. A subset check (our known attributes all present and matching,
    extra attributes on the item's side ignored) is what "is this our
    item" actually means here."""
    item_attributes = item.get_attributes()
    return attributes.items() <= item_attributes.items()


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
        if _matches(item, attributes):
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
        if _matches(item, attributes):
            return item.get_secret().decode("utf-8")
    return None


def delete_secret(name: str) -> None:
    collection = _unlocked_collection()
    attributes = _attributes(name)
    for item in collection.get_all_items():
        if _matches(item, attributes):
            item.delete()
