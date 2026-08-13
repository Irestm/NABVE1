from __future__ import annotations

import asyncio

import modules.ui_automation.service_layer as service_layer
from core.os_adapter.base import ActiveWindow
from modules.ui_automation.domain import UIElement, UIStep

# --- to_command_params (pure) --------------------------------------------


def test_to_command_params_click_uses_bbox_center() -> None:
    element = UIElement(index=0, role="push button", name="Сохранить", bbox=(10, 20, 40, 10))
    params = service_layer.to_command_params([UIStep(action="click", element=element)])
    assert params == [{"action": "click", "x": 30, "y": 25, "button": "left"}]


def test_to_command_params_type_text() -> None:
    params = service_layer.to_command_params([UIStep(action="type_text", text="привет")])
    assert params == [{"action": "type_text", "text": "привет"}]


def test_to_command_params_press_key() -> None:
    params = service_layer.to_command_params([UIStep(action="press_key", key="Enter")])
    assert params == [{"action": "press_key", "key": "Enter"}]


def test_to_command_params_multiple_steps_preserve_order() -> None:
    steps = [
        UIStep(action="click", element=UIElement(0, "entry", "Поиск", (0, 0, 20, 10))),
        UIStep(action="type_text", text="котики"),
    ]
    params = service_layer.to_command_params(steps)
    assert params == [
        {"action": "click", "x": 10, "y": 5, "button": "left"},
        {"action": "type_text", "text": "котики"},
    ]


# --- ground_instruction (async orchestration) -----------------------------


class _FakeOsAdapter:
    def __init__(self, active: ActiveWindow | None) -> None:
        self._active = active

    def get_active_window(self) -> ActiveWindow | None:
        return self._active


class _FakeInspector:
    def __init__(self, elements: list[UIElement]) -> None:
        self._elements = elements
        self.requested_active: ActiveWindow | None = None
        self.call_count = 0

    def list_elements(self, active: ActiveWindow) -> list[UIElement]:
        self.requested_active = active
        self.call_count += 1
        return self._elements


def test_ground_instruction_returns_none_for_empty_text() -> None:
    assert asyncio.run(service_layer.ground_instruction("   ")) is None


def test_ground_instruction_returns_none_when_no_active_window(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_os_adapter", lambda: _FakeOsAdapter(None))
    assert asyncio.run(service_layer.ground_instruction("нажми на тренды")) is None


def test_ground_instruction_returns_none_when_get_active_window_raises(monkeypatch) -> None:
    class _RaisingAdapter:
        def get_active_window(self) -> ActiveWindow:
            raise RuntimeError("boom")

    monkeypatch.setattr(service_layer, "get_os_adapter", lambda: _RaisingAdapter())
    assert asyncio.run(service_layer.ground_instruction("нажми на тренды")) is None


def test_ground_instruction_returns_none_when_no_elements(monkeypatch) -> None:
    monkeypatch.setattr(
        service_layer, "get_os_adapter", lambda: _FakeOsAdapter(ActiveWindow(title="PyCharm", pid=123))
    )
    monkeypatch.setattr(service_layer, "_atspi_inspector", _FakeInspector([]))
    # Also faked (rather than left to fall through to the real OCR
    # inspector): this test is about the "nothing found anywhere" outcome,
    # not about OCR/screenshot behavior, and letting a unit test touch a
    # real screen capture would make it slow and environment-dependent.
    monkeypatch.setattr(service_layer, "_ocr_inspector", _FakeInspector([]))
    assert asyncio.run(service_layer.ground_instruction("нажми на тренды")) is None


def test_ground_instruction_returns_none_when_inspector_raises(monkeypatch) -> None:
    class _RaisingInspector:
        def list_elements(self, active: ActiveWindow) -> list[UIElement]:
            raise RuntimeError("no AT-SPI")

    monkeypatch.setattr(
        service_layer, "get_os_adapter", lambda: _FakeOsAdapter(ActiveWindow(title="PyCharm", pid=123))
    )
    monkeypatch.setattr(service_layer, "_atspi_inspector", _RaisingInspector())
    assert asyncio.run(service_layer.ground_instruction("нажми на тренды")) is None


def test_ground_instruction_delegates_to_grounding_with_active_window_context(monkeypatch) -> None:
    element = UIElement(index=0, role="link", name="Тренды", bbox=(0, 0, 10, 10))
    monkeypatch.setattr(
        service_layer, "get_os_adapter", lambda: _FakeOsAdapter(ActiveWindow(title="Chrome", pid=456))
    )
    inspector = _FakeInspector([element])
    monkeypatch.setattr(service_layer, "_atspi_inspector", inspector)

    captured: dict[str, object] = {}

    async def fake_ground(window_title, elements, raw_instruction):
        captured["window_title"] = window_title
        captured["elements"] = elements
        captured["raw_instruction"] = raw_instruction
        return [UIStep(action="click", element=element)]

    monkeypatch.setattr(service_layer.grounding, "ground", fake_ground)

    steps = asyncio.run(service_layer.ground_instruction("нажми на тренды"))

    assert steps == [UIStep(action="click", element=element)]
    assert captured == {
        "window_title": "Chrome",
        "elements": [element],
        "raw_instruction": "нажми на тренды",
    }
    assert inspector.requested_active is not None
    assert inspector.requested_active.pid == 456


# --- _list_elements routing (AT-SPI vs CDP) --------------------------------


def test_list_elements_non_chromium_window_uses_atspi_only(monkeypatch) -> None:
    atspi = _FakeInspector([UIElement(0, "push button", "OK", (0, 0, 10, 10))])
    cdp = _FakeInspector([UIElement(0, "link", "Should not be used", (0, 0, 10, 10))])
    monkeypatch.setattr(service_layer, "_atspi_inspector", atspi)
    monkeypatch.setattr(service_layer, "_cdp_inspector", cdp)

    active = ActiveWindow(title="PyCharm", pid=1, wm_class="jetbrains-pycharm")
    elements = asyncio.run(service_layer._list_elements(active))

    assert [e.name for e in elements] == ["OK"]
    assert cdp.call_count == 0
    assert atspi.call_count == 1


def test_list_elements_chromium_window_prefers_cdp_when_it_finds_elements(monkeypatch) -> None:
    atspi = _FakeInspector([UIElement(0, "push button", "Should not be used", (0, 0, 10, 10))])
    cdp = _FakeInspector([UIElement(0, "link", "Тренды", (0, 0, 10, 10))])
    monkeypatch.setattr(service_layer, "_atspi_inspector", atspi)
    monkeypatch.setattr(service_layer, "_cdp_inspector", cdp)

    active = ActiveWindow(title="YouTube - Google Chrome", pid=1, wm_class="google-chrome")
    elements = asyncio.run(service_layer._list_elements(active))

    assert [e.name for e in elements] == ["Тренды"]
    assert cdp.call_count == 1
    assert atspi.call_count == 0


def test_list_elements_chromium_window_falls_back_to_atspi_when_cdp_finds_nothing(monkeypatch) -> None:
    # Covers both "Chrome isn't launched with --remote-debugging-port"
    # (ChromeCdpElementInspector already swallows that into an empty list
    # itself, per cdp_adapter.py) and "connected fine but no tab/element
    # matched" — from this function's point of view, both look like an
    # empty result and both should fall back the same way.
    atspi = _FakeInspector([UIElement(0, "push button", "Хотя бы тулбар", (0, 0, 10, 10))])
    cdp = _FakeInspector([])
    monkeypatch.setattr(service_layer, "_atspi_inspector", atspi)
    monkeypatch.setattr(service_layer, "_cdp_inspector", cdp)

    active = ActiveWindow(title="YouTube - Google Chrome", pid=1, wm_class="google-chrome")
    elements = asyncio.run(service_layer._list_elements(active))

    assert [e.name for e in elements] == ["Хотя бы тулбар"]
    assert cdp.call_count == 1
    assert atspi.call_count == 1


def test_list_elements_falls_back_to_ocr_when_atspi_finds_nothing(monkeypatch) -> None:
    atspi = _FakeInspector([])
    ocr = _FakeInspector([UIElement(0, "text", "Сохранить", (0, 0, 10, 10))])
    monkeypatch.setattr(service_layer, "_atspi_inspector", atspi)
    monkeypatch.setattr(service_layer, "_ocr_inspector", ocr)

    active = ActiveWindow(title="Electron App", pid=1, wm_class=None)
    elements = asyncio.run(service_layer._list_elements(active))

    assert [e.name for e in elements] == ["Сохранить"]
    assert atspi.call_count == 1
    assert ocr.call_count == 1


def test_list_elements_skips_ocr_when_atspi_finds_elements(monkeypatch) -> None:
    atspi = _FakeInspector([UIElement(0, "push button", "OK", (0, 0, 10, 10))])
    ocr = _FakeInspector([UIElement(0, "text", "Should not be used", (0, 0, 10, 10))])
    monkeypatch.setattr(service_layer, "_atspi_inspector", atspi)
    monkeypatch.setattr(service_layer, "_ocr_inspector", ocr)

    active = ActiveWindow(title="PyCharm", pid=1, wm_class="jetbrains-pycharm")
    elements = asyncio.run(service_layer._list_elements(active))

    assert [e.name for e in elements] == ["OK"]
    assert ocr.call_count == 0


def test_list_elements_wm_class_is_case_insensitive() -> None:
    assert service_layer._looks_like_chromium(ActiveWindow(title="x", pid=1, wm_class="Google-Chrome"))
    assert not service_layer._looks_like_chromium(ActiveWindow(title="x", pid=1, wm_class=None))
    assert not service_layer._looks_like_chromium(ActiveWindow(title="x", pid=1, wm_class="jetbrains-pycharm"))
