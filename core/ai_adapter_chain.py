from __future__ import annotations

from core.ports import PromptProviderPort
from modules.ai_bridge.providers.base import ChainKind
from modules.ai_bridge.providers.keys import KEY_SPECS, read_key
from modules.ai_bridge.providers.router import ProviderRouter, get_router
from modules.hardware_adaptive import local_ai

LOCAL_PROVIDER_NAMES: frozenset[str] = frozenset({"ollama"})


def chain_kind_for(text: str) -> ChainKind:
    return "complex" if local_ai.is_complex_query(text) else "default"


def _router() -> ProviderRouter:
    return get_router()


def candidate_chain(text: str) -> list[PromptProviderPort]:
    return list(_router().ports(chain_kind_for(text)))


def free_api_first_chain() -> list[PromptProviderPort]:
    return list(_router().ports("default"))


def cloud_api_chain(kind: ChainKind = "default") -> list[PromptProviderPort]:
    router = _router()
    cloud = [
        provider
        for provider in router.chain(kind)
        if provider.name not in LOCAL_PROVIDER_NAMES and not provider.experimental
    ]
    return list(router.ports_of(cloud))


def has_cloud_api_key() -> bool:
    config = _router().config()
    return any(config.is_enabled(name) and read_key(name) for name in KEY_SPECS)
