from __future__ import annotations

import pytest

from modules.text_editing import service_layer


class _FakeAdapter:
    def __init__(self, name: str, reply: str | None = None, should_raise: bool = False) -> None:
        self.name = name
        self._reply = reply
        self._should_raise = should_raise

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        if self._should_raise:
            raise RuntimeError("adapter down")
        return self._reply or ""


async def test_edit_text_returns_the_first_adapters_reply(monkeypatch) -> None:
    adapter = _FakeAdapter("gemini_api", reply="Отредактированный текст.")
    monkeypatch.setattr(service_layer, "candidate_chain", lambda text: [adapter])

    result = await service_layer.edit_text("исходный текст", "сделай короче")

    assert result == "Отредактированный текст."


async def test_edit_text_falls_through_to_the_next_adapter_on_failure(monkeypatch) -> None:
    failing = _FakeAdapter("groq_api", should_raise=True)
    working = _FakeAdapter("local", reply="Готово.")
    monkeypatch.setattr(service_layer, "candidate_chain", lambda text: [failing, working])

    result = await service_layer.edit_text("текст", "исправь")

    assert result == "Готово."


async def test_edit_text_skips_an_empty_reply(monkeypatch) -> None:
    empty = _FakeAdapter("groq_api", reply="   ")
    working = _FakeAdapter("local", reply="Настоящий ответ.")
    monkeypatch.setattr(service_layer, "candidate_chain", lambda text: [empty, working])

    result = await service_layer.edit_text("текст", "исправь")

    assert result == "Настоящий ответ."


async def test_edit_text_raises_when_every_adapter_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        service_layer, "candidate_chain", lambda text: [_FakeAdapter("a", should_raise=True)]
    )

    with pytest.raises(service_layer.TextEditingError):
        await service_layer.edit_text("текст", "исправь")


async def test_edit_text_passes_both_text_and_instruction_in_the_prompt(monkeypatch) -> None:
    captured: dict = {}

    class _CapturingAdapter:
        name = "gemini_api"

        async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
            captured["prompt"] = text
            return "ok"

    monkeypatch.setattr(service_layer, "candidate_chain", lambda text: [_CapturingAdapter()])

    await service_layer.edit_text("привет мир", "переведи на английский")

    assert "привет мир" in captured["prompt"]
    assert "переведи на английский" in captured["prompt"]
