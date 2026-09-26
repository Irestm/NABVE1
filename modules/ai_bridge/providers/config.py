from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from core.config import DATA_DIR
from core.logger import get_logger
from modules.ai_bridge.providers.base import ChainKind

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH: Path = Path(__file__).with_name("providers.default.yaml")
USER_CONFIG_PATH: Path = DATA_DIR / "providers.yaml"

ClaudeConnection = Literal["api_key", "subscription"]
CHAIN_KINDS: tuple[ChainKind, ...] = ("default", "complex")
CLAUDE_CONNECTIONS: tuple[ClaudeConnection, ...] = ("api_key", "subscription")


@dataclass(frozen=True)
class ProvidersConfig:
    chains: dict[ChainKind, list[str]]
    enabled: dict[str, bool]
    models: dict[str, str] = field(default_factory=dict)
    claude_connection: ClaudeConnection = "api_key"

    def is_enabled(self, name: str) -> bool:
        return self.enabled.get(name, False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claude_connection": self.claude_connection,
            "chains": {kind: list(names) for kind, names in self.chains.items()},
            "enabled": dict(self.enabled),
            "models": dict(self.models),
        }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        logger.exception("Could not read provider config %s; ignoring it", path)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _string_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _merge(base: ProvidersConfig, override: dict[str, Any]) -> ProvidersConfig:
    chains = dict(base.chains)
    raw_chains = override.get("chains")
    if isinstance(raw_chains, dict):
        for kind in CHAIN_KINDS:
            names = _string_list(raw_chains.get(kind))
            if names is not None:
                chains[kind] = names
    enabled = dict(base.enabled)
    raw_enabled = override.get("enabled")
    if isinstance(raw_enabled, dict):
        enabled.update({str(name): bool(flag) for name, flag in raw_enabled.items()})
    models = dict(base.models)
    raw_models = override.get("models")
    if isinstance(raw_models, dict):
        models.update({str(name): str(model) for name, model in raw_models.items() if model})
    connection = override.get("claude_connection", base.claude_connection)
    claude_connection = (
        cast(ClaudeConnection, connection) if connection in CLAUDE_CONNECTIONS else base.claude_connection
    )
    return ProvidersConfig(chains=chains, enabled=enabled, models=models, claude_connection=claude_connection)


def _defaults() -> ProvidersConfig:
    empty = ProvidersConfig(chains={kind: [] for kind in CHAIN_KINDS}, enabled={})
    return _merge(empty, _read_yaml(DEFAULT_CONFIG_PATH))


_lock = threading.Lock()


def load_config(user_path: Path | None = None) -> ProvidersConfig:
    return _merge(_defaults(), _read_yaml(user_path or USER_CONFIG_PATH))


def save_config(config: ProvidersConfig, user_path: Path | None = None) -> None:
    path = user_path or USER_CONFIG_PATH
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(config.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8")


def update_config(changes: dict[str, Any], user_path: Path | None = None) -> ProvidersConfig:
    updated = _merge(load_config(user_path), changes)
    save_config(updated, user_path)
    return updated

