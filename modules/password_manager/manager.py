from __future__ import annotations

from core.logger import get_logger

logger = get_logger(__name__)


def _service_namespace(service: str) -> str:
    return f"assistant-password:{service}"


def store_password(service: str, username: str, password: str) -> None:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "keyring is not installed. Install it with: pip install keyring"
        ) from exc
    keyring.set_password(_service_namespace(service), username, password)
    logger.info("Stored password for service='%s' username='%s'", service, username)


def get_password(service: str, username: str) -> str | None:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "keyring is not installed. Install it with: pip install keyring"
        ) from exc
    password = keyring.get_password(_service_namespace(service), username)
    logger.info("Retrieved password for service='%s' username='%s'", service, username)
    return password


def delete_password(service: str, username: str) -> bool:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "keyring is not installed. Install it with: pip install keyring"
        ) from exc
    from keyring.errors import PasswordDeleteError

    logger.info("Deleting password for service='%s' username='%s'", service, username)
    try:
        keyring.delete_password(_service_namespace(service), username)
    except PasswordDeleteError:
        return False
    return True


class KeyringCredentialStore:
    """Adapter satisfying modules.password_manager.ports.CredentialStorePort."""

    store_password = staticmethod(store_password)
    get_password = staticmethod(get_password)
    delete_password = staticmethod(delete_password)
