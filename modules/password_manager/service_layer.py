from __future__ import annotations

from modules.password_manager.domain import Credential
from modules.password_manager.ports import CredentialStorePort


def store(store: CredentialStorePort, service: str, username: str, password: str) -> None:
    credential = Credential(service=service, username=username, password=password)
    store.store_password(credential.service, credential.username, credential.password)


def get(store: CredentialStorePort, service: str | None, username: str | None) -> str | None:
    if not service:
        raise ValueError("Не указан сервис.")
    if not username:
        raise ValueError("Не указано имя пользователя.")
    return store.get_password(service, username)


def delete(store: CredentialStorePort, service: str | None, username: str | None) -> bool:
    if not service:
        raise ValueError("Не указан сервис.")
    if not username:
        raise ValueError("Не указано имя пользователя.")
    return store.delete_password(service, username)
