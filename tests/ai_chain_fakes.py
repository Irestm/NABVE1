from __future__ import annotations

from typing import Any

import pytest

import core.ai_adapter_chain as ai_adapter_chain
from modules.ai_bridge.providers.config import ProvidersConfig


class FakeRouter:
    def __init__(self, default: list[Any], complex_chain: list[Any] | None = None) -> None:
        self._chains: dict[str, list[Any]] = {
            "default": default,
            "complex": complex_chain if complex_chain is not None else list(reversed(default)),
        }
        self.requests = 0

    def chain(self, kind: str = "default") -> list[Any]:
        self.requests += 1
        return list(self._chains[kind])

    def ports(self, kind: str = "default") -> list[Any]:
        return self.chain(kind)

    def ports_of(self, providers: list[Any]) -> list[Any]:
        return list(providers)

    def config(self) -> ProvidersConfig:
        return ProvidersConfig(chains={"default": [], "complex": []}, enabled={})


def use_ai_chain(monkeypatch: pytest.MonkeyPatch, *adapters: Any, complex_chain: list[Any] | None = None) -> FakeRouter:
    fake = FakeRouter([adapter for adapter in adapters if adapter is not None], complex_chain)
    monkeypatch.setattr(ai_adapter_chain, "_router", lambda: fake)
    return fake
