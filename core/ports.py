from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Protocol, TypeVar, runtime_checkable

DomainT = TypeVar("DomainT")
KeyT = TypeVar("KeyT")


@runtime_checkable
class PromptProviderPort(Protocol):
    """Anything that can answer a free-text prompt: browser-automated cloud
    providers (modules.ai_bridge.provider_manager.ProviderManager) and the
    local on-device model (modules.hardware_adaptive.local_ai.LocalEngineAdapter)
    both already exposed this exact shape by convention; this Protocol makes
    it an explicit, structurally-checked contract so core/voice/ai_router.py
    can depend on the abstraction instead of either concrete class, and
    tests can supply a fake without touching Playwright or llama-cpp."""

    name: str

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str: ...


class AbstractRepository(ABC, Generic[DomainT, KeyT]):
    """Common shape for the modules that persist an aggregate. `add`/`get`
    cover the base case; each module's repository adds whatever
    domain-specific query methods it actually needs (e.g. `list_upcoming`,
    `list_due`) — this isn't meant to be a one-size-fits-all interface, just
    a shared convention. See
    https://www.cosmicpython.com/book/chapter_02_repository.html."""

    @abstractmethod
    def add(self, item: DomainT) -> KeyT:
        raise NotImplementedError

    @abstractmethod
    def get(self, key: KeyT) -> DomainT | None:
        raise NotImplementedError
