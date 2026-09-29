from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.power_management import http_api
from modules.power_management.domain import (
    InvalidPowerSettingsError,
    PowerPolicy,
    PowerSettings,
    compute_policy,
)
from modules.power_management.service import PowerService, WorkerStatus, on_battery_from_env
from modules.power_management.settings_store import PowerSettingsStore


def _service(tmp_path: Path, on_battery: bool = False) -> PowerService:
    return PowerService(PowerSettingsStore(tmp_path / "power_settings.json"), on_battery=on_battery)


@pytest.mark.parametrize(
    ("mode", "on_battery", "gpu_on_battery", "expected"),
    [
        ("auto", False, False, PowerPolicy(saving_active=False, gpu_allowed=True, idle_timeout_s=900)),
        ("auto", True, False, PowerPolicy(saving_active=True, gpu_allowed=False, idle_timeout_s=60)),
        ("auto", True, True, PowerPolicy(saving_active=True, gpu_allowed=True, idle_timeout_s=60)),
        ("always", False, False, PowerPolicy(saving_active=True, gpu_allowed=False, idle_timeout_s=60)),
        ("off", True, False, PowerPolicy(saving_active=False, gpu_allowed=True, idle_timeout_s=900)),
    ],
)
def test_policy_follows_the_contract(mode: str, on_battery: bool, gpu_on_battery: bool, expected: PowerPolicy) -> None:
    settings = PowerSettings(mode=mode, gpu_on_battery=gpu_on_battery)  # type: ignore[arg-type]

    assert compute_policy(settings, on_battery) == expected


@pytest.mark.parametrize(
    "overrides",
    [{"mode": "turbo"}, {"idle_timeout_battery_s": 9}, {"idle_timeout_ac_s": 86401}, {"idle_timeout_ac_s": True}],
)
def test_settings_reject_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidPowerSettingsError):
        PowerSettings(**overrides)  # type: ignore[arg-type]


def test_store_round_trips_and_survives_a_corrupt_file(tmp_path: Path) -> None:
    store = PowerSettingsStore(tmp_path / "power_settings.json")
    assert store.load() == PowerSettings()

    store.save(PowerSettings(mode="always", idle_timeout_battery_s=30))
    assert store.load() == PowerSettings(mode="always", idle_timeout_battery_s=30)

    store.path.write_text("{not json", encoding="utf-8")
    assert store.load() == PowerSettings()

    store.path.write_text(json.dumps({"mode": "auto", "idle_timeout_ac_s": 5}), encoding="utf-8")
    assert store.load() == PowerSettings()


def test_listeners_hear_only_real_policy_changes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    heard: list[PowerPolicy] = []
    unsubscribe = service.subscribe(heard.append)

    service.set_on_battery(False)
    service.set_on_battery(True)
    service.update_settings({"idle_timeout_ac_s": 1200})
    service.update_settings({"idle_timeout_battery_s": 120})
    unsubscribe()
    service.set_on_battery(False)

    assert heard == [
        PowerPolicy(saving_active=True, gpu_allowed=False, idle_timeout_s=60),
        PowerPolicy(saving_active=True, gpu_allowed=False, idle_timeout_s=120),
    ]


def test_settings_persist_between_service_instances(tmp_path: Path) -> None:
    _service(tmp_path).update_settings({"mode": "off", "gpu_on_battery": True})

    assert _service(tmp_path).snapshot().settings == PowerSettings(mode="off", gpu_on_battery=True)


@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("0", False), ("", False), ("true", True)])
def test_initial_power_source_comes_from_env(monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
    monkeypatch.setenv("ASSISTANT_ON_BATTERY", raw)

    assert on_battery_from_env() is expected


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, PowerService]:
    service = _service(tmp_path)
    service.bind_worker_status(lambda: WorkerStatus(running=True, device="cuda"))
    monkeypatch.setattr(http_api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(http_api.router)
    return TestClient(app), service


def test_get_power_returns_the_contract_shape(client: tuple[TestClient, PowerService]) -> None:
    test_client, _service_instance = client

    response = test_client.get("/api/power")

    assert response.status_code == 200
    assert response.json() == {
        "on_battery": False,
        "mode": "auto",
        "saving_active": False,
        "idle_timeout_battery_s": 60,
        "idle_timeout_ac_s": 900,
        "gpu_on_battery": False,
        "worker_running": True,
        "worker_device": "cuda",
    }


def test_put_source_switches_to_saving(client: tuple[TestClient, PowerService]) -> None:
    test_client, service = client

    response = test_client.put("/api/power/source", json={"on_battery": True})

    assert response.status_code == 200
    assert response.json()["saving_active"] is True
    assert service.policy().gpu_allowed is False


def test_put_settings_validates_and_persists(client: tuple[TestClient, PowerService]) -> None:
    test_client, service = client

    rejected = test_client.put("/api/power/settings", json={"idle_timeout_battery_s": 5})
    unknown = test_client.put("/api/power/settings", json={"turbo": True, "worker_running": False})
    accepted = test_client.put("/api/power/settings", json={"mode": "always", "idle_timeout_battery_s": 45})

    assert rejected.status_code == 422
    assert unknown.status_code == 200
    assert accepted.status_code == 200
    assert accepted.json()["saving_active"] is True
    assert accepted.json()["idle_timeout_battery_s"] == 45
    assert service.policy().idle_timeout_s == 45
