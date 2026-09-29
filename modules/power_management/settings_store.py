from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from core.logger import get_logger
from modules.power_management.domain import InvalidPowerSettingsError, PowerSettings

logger = get_logger(__name__)

SETTINGS_FILE_NAME = "power_settings.json"


class PowerSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> PowerSettings:
        if not self._path.is_file():
            return PowerSettings()
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Could not read %s; using default power settings", self._path, exc_info=True)
            return PowerSettings()
        if not isinstance(raw, dict):
            logger.warning("%s is not a JSON object; using default power settings", self._path)
            return PowerSettings()
        known = {field.name for field in fields(PowerSettings)}
        try:
            return PowerSettings(**{key: value for key, value in raw.items() if key in known})
        except InvalidPowerSettingsError:
            logger.warning("Invalid values in %s; using default power settings", self._path, exc_info=True)
            return PowerSettings()

    def save(self, settings: PowerSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)
