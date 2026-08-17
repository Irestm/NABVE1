from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ai_bridge import system_prompt
from modules.user_profile.domain import ASSISTANT_NAME_KEY


@pytest.fixture(autouse=True)
def _fake_style(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        system_prompt, "get_current_style", lambda: SimpleNamespace(prompt_fragment="общайся нейтрально")
    )


def test_apply_system_prompt_includes_base_prefix_and_original_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_prompt.service_layer, "get_fact", lambda uow, key: None)

    result = system_prompt.apply_system_prompt("hello world")

    assert result.startswith(system_prompt.SYSTEM_PROMPT_PREFIX)
    assert result.endswith("hello world")
    assert "общайся нейтрально" in result


def test_apply_system_prompt_includes_assistant_name_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        system_prompt.service_layer,
        "get_fact",
        lambda uow, key: "Джарвис" if key == ASSISTANT_NAME_KEY else None,
    )

    result = system_prompt.apply_system_prompt("hello")

    assert "Тебя зовут Джарвис." in result


def test_apply_system_prompt_omits_name_sentence_when_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_prompt.service_layer, "get_fact", lambda uow, key: None)

    result = system_prompt.apply_system_prompt("hello")

    assert "Тебя зовут" not in result
