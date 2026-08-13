from __future__ import annotations

import asyncio

import pytest

import core.ai_adapter_chain as ai_adapter_chain
import modules.app_catalog.resolver as resolver
from modules.app_catalog.domain import InstalledApp
from modules.app_catalog.resolver import ResolvedApp, _parse_resolution


def _apps() -> list[InstalledApp]:
    return [
        InstalledApp("Dead Cells", "steam://rungameid/588650", "steam"),
        InstalledApp("Stardew Valley", "steam://rungameid/413150", "steam"),
    ]


class _FakeAdapter:
    def __init__(self, name: str, reply: str) -> None:
        self.name = name
        self._reply = reply

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        return self._reply


class _FailingAdapter:
    name = "failing"

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        raise RuntimeError("boom")


# --- _parse_resolution -------------------------------------------------


def test_parse_resolution_valid_json() -> None:
    apps = _apps()
    resolved = _parse_resolution('{"index": 0, "confidence": 87}', apps)
    assert resolved == ResolvedApp(app=apps[0], confidence=87)


def test_parse_resolution_extracts_json_from_surrounding_text() -> None:
    apps = _apps()
    resolved = _parse_resolution('Конечно! Вот ответ: {"index": 1, "confidence": 72} спасибо', apps)
    assert resolved is not None
    assert resolved.app.display_name == "Stardew Valley"


def test_parse_resolution_null_index_is_none() -> None:
    assert _parse_resolution('{"index": null, "confidence": 0}', _apps()) is None


def test_parse_resolution_out_of_range_index_is_none() -> None:
    assert _parse_resolution('{"index": 5, "confidence": 90}', _apps()) is None


def test_parse_resolution_invalid_json_is_none() -> None:
    assert _parse_resolution("not json at all", _apps()) is None


def test_parse_resolution_clamps_confidence_to_0_100() -> None:
    resolved = _parse_resolution('{"index": 0, "confidence": 150}', _apps())
    assert resolved is not None
    assert resolved.confidence == 100


def test_resolved_app_is_confident_threshold() -> None:
    app = _apps()[0]
    assert ResolvedApp(app=app, confidence=60).is_confident
    assert not ResolvedApp(app=app, confidence=59).is_confident


# --- resolve() -----------------------------------------------------------


def test_resolve_returns_none_when_no_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: [])
    assert asyncio.run(resolver.resolve("что угодно")) is None


def test_resolve_returns_none_for_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: _apps())
    assert asyncio.run(resolver.resolve("   ")) is None


def test_resolve_uses_confident_local_answer_without_trying_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: _apps())
    local = _FakeAdapter("local", '{"index": 0, "confidence": 90}')
    cloud = _FakeAdapter("ai_bridge", '{"index": 1, "confidence": 95}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    resolved = asyncio.run(resolver.resolve("дед селс"))

    assert resolved is not None
    assert resolved.app.display_name == "Dead Cells"
    assert resolved.confidence == 90


def test_resolve_escalates_to_cloud_when_local_confidence_is_low(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: _apps())
    local = _FakeAdapter("local", '{"index": 0, "confidence": 20}')
    cloud = _FakeAdapter("ai_bridge", '{"index": 1, "confidence": 95}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    resolved = asyncio.run(resolver.resolve("что-то невнятное"))

    assert resolved is not None
    assert resolved.app.display_name == "Stardew Valley"
    assert resolved.confidence == 95


def test_resolve_returns_best_low_confidence_guess_when_nobody_is_sure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: _apps())
    local = _FakeAdapter("local", '{"index": 0, "confidence": 20}')
    cloud = _FakeAdapter("ai_bridge", '{"index": 1, "confidence": 40}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: local)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    resolved = asyncio.run(resolver.resolve("непонятно что"))

    assert resolved is not None
    assert not resolved.is_confident
    assert resolved.app.display_name == "Stardew Valley"


def test_resolve_falls_through_a_failing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: _apps())
    cloud = _FakeAdapter("ai_bridge", '{"index": 0, "confidence": 80}')
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: _FailingAdapter())
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: cloud)

    resolved = asyncio.run(resolver.resolve("дед селс"))

    assert resolved is not None
    assert resolved.app.display_name == "Dead Cells"


def test_resolve_returns_none_when_every_adapter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver.catalog, "list_installed_apps", lambda: _apps())
    monkeypatch.setattr(ai_adapter_chain.local_ai, "get_adapter", lambda: None)
    monkeypatch.setattr(ai_adapter_chain, "get_provider_manager", lambda: _FailingAdapter())

    assert asyncio.run(resolver.resolve("дед селс")) is None
