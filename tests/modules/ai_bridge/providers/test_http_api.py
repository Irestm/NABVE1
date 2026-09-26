from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.main import app
from modules.ai_bridge.providers import config as config_module
from modules.ai_bridge.providers import http_api
from modules.ai_bridge.providers.base import ProviderHealth
from modules.ai_bridge.providers.config import load_config
from modules.ai_bridge.providers.router import ProviderRouter

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


class _Provider:
    def __init__(self, name: str, experimental: bool = False) -> None:
        self.name = name
        self.experimental = experimental

    def is_ready(self) -> bool:
        return True

    async def complete(self, messages: Any, *, json_schema: Any = None, max_tokens: int) -> Any:
        raise NotImplementedError

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, "ok", "fine", 5)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    user_path = tmp_path / "providers.yaml"
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", user_path)
    providers = {"ollama": _Provider("ollama"), "gemini_api": _Provider("gemini_api"), "browser_chain": _Provider("browser_chain", True)}
    router = ProviderRouter(
        config_loader=lambda: load_config(user_path),
        factories={name: (lambda model, provider=provider: provider) for name, provider in providers.items()},
    )
    monkeypatch.setattr(http_api, "get_router", lambda: router)
    stored: dict[str, str] = {}
    monkeypatch.setattr(http_api, "read_key", lambda name: stored.get(name))
    monkeypatch.setattr(http_api, "save_key", lambda name, value: stored.__setitem__(name, value))
    monkeypatch.setattr(http_api, "remove_key", lambda name: stored.pop(name, None))
    return stored


def test_overview_lists_providers_with_flags() -> None:
    response = client.get("/api/providers", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    by_name = {item["name"]: item for item in body["providers"]}
    assert by_name["browser_chain"]["experimental"] is True
    assert by_name["browser_chain"]["enabled"] is False
    assert by_name["ollama"]["needs_key"] is False
    assert by_name["gemini_api"]["needs_key"] is True
    assert by_name["gemini_api"]["key_configured"] is False
    assert body["subscription_available"] is False
    assert "свой риск" in body["experimental_warning"]


def test_health_endpoint_reports_disabled_and_ok() -> None:
    response = client.get("/api/providers/health", headers=AUTH)

    statuses = {item["name"]: item["status"] for item in response.json()}
    assert statuses == {"ollama": "ok", "gemini_api": "ok", "browser_chain": "disabled"}


def test_put_config_persists_changes() -> None:
    response = client.put(
        "/api/providers/config",
        json={"enabled": {"browser_chain": True}, "chains": {"default": ["ollama", "gemini_api"]}},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["chains"]["default"] == ["ollama", "gemini_api"]
    assert load_config(config_module.USER_CONFIG_PATH).is_enabled("browser_chain") is True


def test_put_config_rejects_unknown_providers() -> None:
    response = client.put("/api/providers/config", json={"enabled": {"skynet": True}}, headers=AUTH)

    assert response.status_code == 422


def test_put_config_accepts_the_subscription_connection() -> None:
    response = client.put("/api/providers/config", json={"claude_connection": "subscription"}, headers=AUTH)

    assert response.json()["claude_connection"] == "subscription"


def test_key_round_trip(_isolated: dict[str, str]) -> None:
    saved = client.post("/api/providers/gemini_api/key", json={"api_key": "  secret  "}, headers=AUTH)

    assert saved.status_code == 200
    assert _isolated["gemini_api"] == "secret"

    removed = client.delete("/api/providers/gemini_api/key", headers=AUTH)

    assert removed.status_code == 200
    assert "gemini_api" not in _isolated


def test_key_endpoints_reject_keyless_providers() -> None:
    assert client.post("/api/providers/ollama/key", json={"api_key": "x"}, headers=AUTH).status_code == 404


def test_providers_api_requires_the_token() -> None:
    assert client.get("/api/providers").status_code in (401, 403)
