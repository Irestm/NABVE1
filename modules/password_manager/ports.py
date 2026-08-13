from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialStorePort(Protocol):
    def store_password(self, service: str, username: str, password: str) -> None: ...
    def get_password(self, service: str, username: str) -> str | None: ...
    def delete_password(self, service: str, username: str) -> bool: ...
