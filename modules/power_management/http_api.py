from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modules.power_management.domain import (
    MAX_IDLE_TIMEOUT_SECONDS,
    MIN_IDLE_TIMEOUT_SECONDS,
    InvalidPowerSettingsError,
    PowerMode,
    PowerSnapshot,
)
from modules.power_management.service import PowerService, get_power_service

router = APIRouter(prefix="/api/power", tags=["power"])


class PowerStateModel(BaseModel):
    on_battery: bool
    mode: PowerMode
    saving_active: bool
    idle_timeout_battery_s: int
    idle_timeout_ac_s: int
    gpu_on_battery: bool
    worker_running: bool
    worker_device: Literal["cuda", "cpu"] | None


class PowerSourceRequest(BaseModel):
    on_battery: bool


class PowerSettingsUpdate(BaseModel):
    mode: PowerMode | None = None
    idle_timeout_battery_s: int | None = Field(default=None, ge=MIN_IDLE_TIMEOUT_SECONDS, le=MAX_IDLE_TIMEOUT_SECONDS)
    idle_timeout_ac_s: int | None = Field(default=None, ge=MIN_IDLE_TIMEOUT_SECONDS, le=MAX_IDLE_TIMEOUT_SECONDS)
    gpu_on_battery: bool | None = None


def _service() -> PowerService:
    return get_power_service()


def _state(service: PowerService, snapshot: PowerSnapshot) -> PowerStateModel:
    worker = service.worker_status()
    device = worker.device if worker.device in ("cuda", "cpu") else None
    return PowerStateModel(
        on_battery=snapshot.on_battery,
        mode=snapshot.settings.mode,
        saving_active=snapshot.policy.saving_active,
        idle_timeout_battery_s=snapshot.settings.idle_timeout_battery_s,
        idle_timeout_ac_s=snapshot.settings.idle_timeout_ac_s,
        gpu_on_battery=snapshot.settings.gpu_on_battery,
        worker_running=worker.running,
        worker_device=device if worker.running else None,
    )


@router.get("", response_model=PowerStateModel)
async def get_power_state() -> PowerStateModel:
    service = _service()
    return _state(service, service.snapshot())


@router.put("/source", response_model=PowerStateModel)
async def set_power_source(request: PowerSourceRequest) -> PowerStateModel:
    service = _service()
    snapshot = await asyncio.to_thread(service.set_on_battery, request.on_battery)
    return _state(service, snapshot)


@router.put("/settings", response_model=PowerStateModel)
async def update_power_settings(request: PowerSettingsUpdate) -> PowerStateModel:
    service = _service()
    changes = request.model_dump(exclude_none=True)
    try:
        snapshot = await asyncio.to_thread(service.update_settings, changes)
    except InvalidPowerSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _state(service, snapshot)
