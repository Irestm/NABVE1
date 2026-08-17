from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from core.os_adapter.base import ActiveWindow
from modules.figma_control import screen_fallback


class _FakePyautogui:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def press(self, key):
        self.calls.append(("press", key))

    def click(self, x=None, y=None, button="left"):
        self.calls.append(("click", x, y, button))

    def moveTo(self, x, y, duration=0):
        self.calls.append(("moveTo", x, y))

    def mouseDown(self):
        self.calls.append(("mouseDown",))

    def mouseUp(self):
        self.calls.append(("mouseUp",))

    def typewrite(self, text):
        self.calls.append(("typewrite", text))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def size(self):
        return (1920, 1080)


def _figma_window(title: str = "Untitled — Figma") -> ActiveWindow:
    return ActiveWindow(title=title, pid=123, bbox=(0, 0, 1000, 800))


@pytest.fixture(autouse=True)
def _no_real_gui(monkeypatch):
    # Guard rail: if a test forgets to stub out ensure_figma_focused's
    # adapter lookup, fail loudly instead of silently hitting a real
    # display/pyautogui.
    fake_pyautogui = _FakePyautogui()
    monkeypatch.setattr(screen_fallback, "_require_pyautogui", lambda: fake_pyautogui)
    return fake_pyautogui


def test_ensure_figma_focused_passes_when_figma_is_active(monkeypatch):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    screen_fallback.ensure_figma_focused()  # must not raise


def test_ensure_figma_focused_refuses_other_window(monkeypatch):
    other = ActiveWindow(title="Inbox — Gmail — Google Chrome", pid=1, bbox=None)
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: other})()
    )
    with pytest.raises(screen_fallback.FigmaNotFocusedError):
        screen_fallback.ensure_figma_focused()


def test_ensure_figma_focused_refuses_when_no_active_window(monkeypatch):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: None})()
    )
    with pytest.raises(screen_fallback.FigmaNotFocusedError):
        screen_fallback.ensure_figma_focused()


def test_create_rectangle_drags_from_viewport_center(monkeypatch, _no_real_gui):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    message = screen_fallback.create_rectangle({"width": 50, "height": 30})
    assert message == "Прямоугольник создан через управление экраном."
    kinds = [call[0] for call in _no_real_gui.calls]
    assert kinds == ["press", "moveTo", "mouseDown", "moveTo", "mouseUp", "press"]
    assert _no_real_gui.calls[0] == ("press", "r")


def test_create_rectangle_refuses_when_not_focused(monkeypatch):
    other = ActiveWindow(title="Slack", pid=1, bbox=None)
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: other})()
    )
    with pytest.raises(screen_fallback.FigmaNotFocusedError):
        screen_fallback.create_rectangle({"width": 50, "height": 30})


def test_select_layer_clicks_located_text(monkeypatch, _no_real_gui):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    monkeypatch.setattr(screen_fallback, "_find_text_on_screen", lambda word: (123, 456))

    message = screen_fallback.select_layer({"layer_name": "Кнопка"})

    assert "Кнопка" in message
    assert ("click", 123, 456, "left") in _no_real_gui.calls


def test_select_layer_unsupported_when_text_not_found(monkeypatch):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    monkeypatch.setattr(screen_fallback, "_find_text_on_screen", lambda word: None)

    with pytest.raises(screen_fallback.FallbackActionUnsupportedError):
        screen_fallback.select_layer({"layer_name": "Кнопка"})


def test_align_unknown_alignment_is_unsupported(monkeypatch):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    with pytest.raises(screen_fallback.FallbackActionUnsupportedError):
        screen_fallback.align({"alignment": "diagonally"})


def test_align_clicks_located_icon(monkeypatch, _no_real_gui):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    monkeypatch.setattr(screen_fallback, "find_icon_on_screen", lambda name, confidence=0.85: (10, 20))

    message = screen_fallback.align({"alignment": "left"})

    assert message == "Выравнивание выполнено через управление экраном."
    assert ("click", 10, 20, "left") in _no_real_gui.calls


def test_execute_dispatches_known_action(monkeypatch, _no_real_gui):
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    assert screen_fallback.execute("undo", {}) == "Отменено через управление экраном."
    assert ("hotkey", ("ctrl", "z")) in _no_real_gui.calls


def test_execute_reports_unsupported_for_unknown_action():
    with pytest.raises(screen_fallback.FallbackActionUnsupportedError):
        screen_fallback.execute("move_layer", {"layer_name": "x", "x": 1, "y": 1})


class _FakeCv2:
    COLOR_RGB2GRAY = "rgb2gray"
    TM_CCOEFF_NORMED = "ccoeff_normed"
    IMREAD_GRAYSCALE = 0

    def __init__(self, match_value: float, match_loc: tuple[int, int]) -> None:
        self._match_value = match_value
        self._match_loc = match_loc

    def cvtColor(self, array, _code):
        return array

    def imread(self, _path, _flag):
        return np.zeros((10, 10), dtype=np.uint8)

    def matchTemplate(self, _haystack, _needle, _method):
        return np.zeros((1, 1), dtype=np.float32)

    def minMaxLoc(self, _result):
        return (0.0, self._match_value, (0, 0), self._match_loc)


def test_find_icon_on_screen_returns_none_when_template_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(screen_fallback, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(screen_fallback, "_require_cv2", lambda: _FakeCv2(0.99, (0, 0)))
    assert screen_fallback.find_icon_on_screen("align_left.png") is None


def test_find_icon_on_screen_returns_none_below_confidence(monkeypatch, tmp_path):
    (tmp_path / "align_left.png").write_bytes(b"fake-png")
    monkeypatch.setattr(screen_fallback, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(screen_fallback, "_require_cv2", lambda: _FakeCv2(0.10, (0, 0)))
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    monkeypatch.setattr(screen_fallback, "capture_window", lambda active: (Image.new("RGB", (10, 10)), (0, 0)))

    assert screen_fallback.find_icon_on_screen("align_left.png") is None


def test_find_icon_on_screen_returns_absolute_center_above_confidence(monkeypatch, tmp_path):
    (tmp_path / "align_left.png").write_bytes(b"fake-png")
    monkeypatch.setattr(screen_fallback, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(screen_fallback, "_require_cv2", lambda: _FakeCv2(0.95, (5, 5)))
    monkeypatch.setattr(
        screen_fallback, "get_os_adapter", lambda: type("A", (), {"get_active_window": lambda self: _figma_window()})()
    )
    monkeypatch.setattr(screen_fallback, "capture_window", lambda active: (Image.new("RGB", (10, 10)), (100, 200)))

    location = screen_fallback.find_icon_on_screen("align_left.png")

    # offset (100, 200) + match_loc (5, 5) + needle_size (10, 10) // 2
    assert location == (100 + 5 + 5, 200 + 5 + 5)
