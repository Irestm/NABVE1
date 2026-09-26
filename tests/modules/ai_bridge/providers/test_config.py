from __future__ import annotations

from pathlib import Path

from modules.ai_bridge.providers.config import load_config, save_config, update_config


def test_defaults_keep_browser_chain_disabled(tmp_path: Path) -> None:
    config = load_config(tmp_path / "providers.yaml")

    assert config.is_enabled("browser_chain") is False
    assert config.is_enabled("ollama") is True
    assert config.claude_connection == "api_key"
    assert "ollama" in config.chains["default"]


def test_user_file_overrides_only_the_given_fields(tmp_path: Path) -> None:
    user_path = tmp_path / "providers.yaml"
    user_path.write_text(
        "claude_connection: subscription\nchains:\n  default: [ollama]\nenabled:\n  browser_chain: true\n",
        encoding="utf-8",
    )

    config = load_config(user_path)

    assert config.claude_connection == "subscription"
    assert config.chains["default"] == ["ollama"]
    assert config.chains["complex"]
    assert config.is_enabled("browser_chain") is True
    assert config.models["anthropic_api"]


def test_invalid_values_fall_back_to_defaults(tmp_path: Path) -> None:
    user_path = tmp_path / "providers.yaml"
    user_path.write_text("claude_connection: magic\nchains:\n  default: not-a-list\n", encoding="utf-8")

    config = load_config(user_path)

    assert config.claude_connection == "api_key"
    assert "ollama" in config.chains["default"]


def test_broken_yaml_is_ignored(tmp_path: Path) -> None:
    user_path = tmp_path / "providers.yaml"
    user_path.write_text("chains: [unclosed", encoding="utf-8")

    assert load_config(user_path).is_enabled("ollama") is True


def test_update_config_round_trips(tmp_path: Path) -> None:
    user_path = tmp_path / "providers.yaml"

    updated = update_config({"enabled": {"groq_api": False}, "models": {"openai_api": "gpt-x"}}, user_path)
    reloaded = load_config(user_path)

    assert updated == reloaded
    assert reloaded.is_enabled("groq_api") is False
    assert reloaded.models["openai_api"] == "gpt-x"


def test_save_config_creates_parent_directory(tmp_path: Path) -> None:
    user_path = tmp_path / "nested" / "providers.yaml"

    save_config(load_config(user_path), user_path)

    assert user_path.exists()
