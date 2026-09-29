from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

PowerMode = Literal["auto", "always", "off"]
POWER_MODES: tuple[str, ...] = get_args(PowerMode)

MIN_IDLE_TIMEOUT_SECONDS = 10
MAX_IDLE_TIMEOUT_SECONDS = 86400
DEFAULT_IDLE_TIMEOUT_BATTERY_SECONDS = 60
DEFAULT_IDLE_TIMEOUT_AC_SECONDS = 900


class InvalidPowerSettingsError(ValueError):
    pass


@dataclass(frozen=True)
class PowerSettings:
    mode: PowerMode = "auto"
    idle_timeout_battery_s: int = DEFAULT_IDLE_TIMEOUT_BATTERY_SECONDS
    idle_timeout_ac_s: int = DEFAULT_IDLE_TIMEOUT_AC_SECONDS
    gpu_on_battery: bool = False

    def __post_init__(self) -> None:
        if self.mode not in POWER_MODES:
            raise InvalidPowerSettingsError(f"mode must be one of {POWER_MODES}, got {self.mode!r}")
        for name in ("idle_timeout_battery_s", "idle_timeout_ac_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidPowerSettingsError(f"{name} must be an integer, got {value!r}")
            if not MIN_IDLE_TIMEOUT_SECONDS <= value <= MAX_IDLE_TIMEOUT_SECONDS:
                raise InvalidPowerSettingsError(
                    f"{name} must be within {MIN_IDLE_TIMEOUT_SECONDS}..{MAX_IDLE_TIMEOUT_SECONDS}, got {value}"
                )
        if not isinstance(self.gpu_on_battery, bool):
            raise InvalidPowerSettingsError(f"gpu_on_battery must be a boolean, got {self.gpu_on_battery!r}")


@dataclass(frozen=True)
class PowerPolicy:
    saving_active: bool
    gpu_allowed: bool
    idle_timeout_s: int


@dataclass(frozen=True)
class PowerSnapshot:
    on_battery: bool
    settings: PowerSettings
    policy: PowerPolicy


def is_saving_active(settings: PowerSettings, on_battery: bool) -> bool:
    return settings.mode == "always" or (settings.mode == "auto" and on_battery)


def compute_policy(settings: PowerSettings, on_battery: bool) -> PowerPolicy:
    if is_saving_active(settings, on_battery):
        return PowerPolicy(
            saving_active=True,
            gpu_allowed=settings.gpu_on_battery,
            idle_timeout_s=settings.idle_timeout_battery_s,
        )
    return PowerPolicy(saving_active=False, gpu_allowed=True, idle_timeout_s=settings.idle_timeout_ac_s)
