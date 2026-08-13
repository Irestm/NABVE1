from __future__ import annotations

from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

_KEYRING_SERVICE = "assistant-profile"
_KEYRING_USERNAME = "encryption-key"


def get_or_create_fernet_key() -> bytes:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "keyring is not installed. Install it with: pip install keyring"
        ) from exc

    existing = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    if existing is not None:
        return existing.encode()

    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is not installed. Install it with: pip install cryptography"
        ) from exc

    key = Fernet.generate_key()
    keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key.decode())
    logger.info("Generated new profile encryption key and stored it in the system keyring")
    return key


def get_fernet() -> Any:
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is not installed. Install it with: pip install cryptography"
        ) from exc
    return Fernet(get_or_create_fernet_key())
