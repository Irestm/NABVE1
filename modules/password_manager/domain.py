from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Credential:
    service: str
    username: str
    password: str

    def __post_init__(self) -> None:
        if not self.service:
            raise ValueError("Missing required parameter 'service'")
        if not self.username:
            raise ValueError("Missing required parameter 'username'")
        if not self.password:
            raise ValueError("Missing required parameter 'password'")
