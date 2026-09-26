from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.secret_store import SecretStoreUnavailableError
from modules.ai_bridge.providers.config import ProvidersConfig, update_config
from modules.ai_bridge.providers.experimental.browser_chain import RISK_WARNING
from modules.ai_bridge.providers.keys import KEY_SPECS, read_key, remove_key, save_key
from modules.ai_bridge.providers.router import get_router

router = APIRouter(prefix="/api/providers", tags=["providers"])

SUBSCRIPTION_PROVIDER_NAME = "anthropic_subscription"


class ProviderInfo(BaseModel):
    name: str
    enabled: bool
    experimental: bool
    needs_key: bool
    key_configured: bool
    model: str | None = None


class ProvidersOverview(BaseModel):
    claude_connection: Literal["api_key", "subscription"]
    subscription_available: bool
    chains: dict[str, list[str]]
    providers: list[ProviderInfo]
    experimental_warning: str


class ProviderHealthModel(BaseModel):
    name: str
    status: str
    detail: str | None = None
    latency_ms: int | None = None
    experimental: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class ProvidersConfigUpdate(BaseModel):
    claude_connection: Literal["api_key", "subscription"] | None = None
    chains: dict[Literal["default", "complex"], list[str]] | None = None
    enabled: dict[str, bool] | None = None
    models: dict[str, str] | None = None


class ProviderKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1)


def _overview(config: ProvidersConfig) -> ProvidersOverview:
    ai_router = get_router()
    providers: list[ProviderInfo] = []
    for name in ai_router.known_providers():
        provider = ai_router.provider(name, config)
        needs_key = name in KEY_SPECS
        providers.append(
            ProviderInfo(
                name=name,
                enabled=config.is_enabled(name),
                experimental=bool(provider is not None and provider.experimental),
                needs_key=needs_key,
                key_configured=needs_key and read_key(name) is not None,
                model=config.models.get(name),
            )
        )
    return ProvidersOverview(
        claude_connection=config.claude_connection,
        subscription_available=SUBSCRIPTION_PROVIDER_NAME in ai_router.known_providers(),
        chains={kind: list(names) for kind, names in config.chains.items()},
        providers=providers,
        experimental_warning=RISK_WARNING,
    )


@router.get("", response_model=ProvidersOverview)
async def get_providers() -> ProvidersOverview:
    config = await asyncio.to_thread(get_router().config)
    return await asyncio.to_thread(_overview, config)


@router.get("/health", response_model=list[ProviderHealthModel])
async def get_providers_health() -> list[ProviderHealthModel]:
    return [
        ProviderHealthModel(
            name=health.name,
            status=health.status,
            detail=health.detail,
            latency_ms=health.latency_ms,
            experimental=health.experimental,
            extra=health.extra,
        )
        for health in await get_router().health_all()
    ]


@router.put("/config", response_model=ProvidersOverview)
async def put_providers_config(update: ProvidersConfigUpdate) -> ProvidersOverview:
    known = set(get_router().known_providers()) | {SUBSCRIPTION_PROVIDER_NAME}
    changes = update.model_dump(exclude_none=True)
    for field_name in ("enabled", "models"):
        unknown = set(changes.get(field_name, {})) - known
        if unknown:
            raise HTTPException(status_code=422, detail=f"Неизвестные провайдеры: {', '.join(sorted(unknown))}")
    for names in changes.get("chains", {}).values():
        unknown = set(names) - known
        if unknown:
            raise HTTPException(status_code=422, detail=f"Неизвестные провайдеры: {', '.join(sorted(unknown))}")
    config = await asyncio.to_thread(update_config, changes)
    return await asyncio.to_thread(_overview, config)


def _require_key_provider(name: str) -> None:
    if name not in KEY_SPECS:
        raise HTTPException(status_code=404, detail=f"Провайдер «{name}» не использует API-ключ")


@router.post("/{name}/key", response_model=ProvidersOverview)
async def save_provider_key(name: str, request: ProviderKeyRequest) -> ProvidersOverview:
    _require_key_provider(name)
    try:
        await asyncio.to_thread(save_key, name, request.api_key.strip())
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await get_providers()


@router.delete("/{name}/key", response_model=ProvidersOverview)
async def delete_provider_key(name: str) -> ProvidersOverview:
    _require_key_provider(name)
    try:
        await asyncio.to_thread(remove_key, name)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await get_providers()
