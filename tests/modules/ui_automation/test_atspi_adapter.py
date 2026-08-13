from __future__ import annotations

import logging

import modules.ui_automation.atspi_adapter as atspi_adapter_module
from core.os_adapter.base import ActiveWindow
from modules.ui_automation.atspi_adapter import AtspiElementInspector


class _FakeCoordType:
    SCREEN = "screen"


class _FakeStateType:
    SHOWING = "showing"
    VISIBLE = "visible"


class _FakeAtspi:
    CoordType = _FakeCoordType
    StateType = _FakeStateType


class _Extents:
    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.x, self.y, self.width, self.height = x, y, width, height


class _FakeComponent:
    def __init__(self, extents: tuple[int, int, int, int]) -> None:
        self._extents = _Extents(*extents)

    def get_extents(self, coord_type: str) -> _Extents:
        return self._extents


class _FakeStateSet:
    def contains(self, state: str) -> bool:
        return state in (_FakeStateType.SHOWING, _FakeStateType.VISIBLE)


class _FakeNode:
    def __init__(
        self,
        role: str = "panel",
        name: str = "",
        children: list["_FakeNode"] | None = None,
        bbox: tuple[int, int, int, int] | None = None,
        role_raises: bool = False,
        children_raise: bool = False,
    ) -> None:
        self.role = role
        self.name = name
        self.children = children or []
        self.bbox = bbox
        self.role_raises = role_raises
        self.children_raise = children_raise

    def get_role_name(self) -> str:
        if self.role_raises:
            raise RuntimeError("dead AT-SPI object")
        return self.role

    def get_name(self) -> str:
        return self.name

    def get_state_set(self) -> _FakeStateSet:
        return _FakeStateSet()

    def get_component_iface(self) -> _FakeComponent | None:
        return None if self.bbox is None else _FakeComponent(self.bbox)

    def get_child_count(self) -> int:
        if self.children_raise:
            raise RuntimeError("cannot enumerate children")
        return len(self.children)

    def get_child_at_index(self, index: int) -> "_FakeNode":
        return self.children[index]


def _inspector(monkeypatch, root: _FakeNode | None) -> AtspiElementInspector:
    monkeypatch.setattr(atspi_adapter_module, "_require_atspi", lambda: _FakeAtspi)
    monkeypatch.setattr(atspi_adapter_module, "_find_app_by_pid", lambda atspi, pid: root)
    return AtspiElementInspector()


def test_list_elements_returns_none_for_missing_pid() -> None:
    inspector = AtspiElementInspector()
    assert inspector.list_elements(ActiveWindow(title="x", pid=None)) == []


def test_list_elements_collects_interactive_named_elements(monkeypatch) -> None:
    button = _FakeNode(role="push button", name="Отправить", bbox=(10, 20, 30, 40))
    root = _FakeNode(role="frame", name="", children=[button])
    inspector = _inspector(monkeypatch, root)

    elements = inspector.list_elements(ActiveWindow(title="x", pid=123))

    assert len(elements) == 1
    assert elements[0].role == "push button"
    assert elements[0].name == "Отправить"
    assert elements[0].bbox == (10, 20, 30, 40)


def test_list_elements_skips_a_broken_node_without_losing_its_siblings(monkeypatch, caplog) -> None:
    good = _FakeNode(role="push button", name="ОК", bbox=(0, 0, 10, 10))
    broken = _FakeNode(role_raises=True)
    root = _FakeNode(role="frame", children=[good, broken])
    inspector = _inspector(monkeypatch, root)

    with caplog.at_level(logging.DEBUG, logger=atspi_adapter_module.logger.name):
        elements = inspector.list_elements(ActiveWindow(title="x", pid=123))

    assert [e.name for e in elements] == ["ОК"]
    # One node failed out of several visited — the per-walk debug summary,
    # not the "everything failed" warning.
    assert any("node accesses failed" in record.message for record in caplog.records)
    assert not any("likely a systemic AT-SPI problem" in record.message for record in caplog.records)


def test_list_elements_warns_when_every_node_fails(monkeypatch, caplog) -> None:
    root = _FakeNode(role_raises=True)
    inspector = _inspector(monkeypatch, root)

    with caplog.at_level(logging.DEBUG, logger=atspi_adapter_module.logger.name):
        elements = inspector.list_elements(ActiveWindow(title="x", pid=123))

    assert elements == []
    assert any("likely a systemic AT-SPI problem" in record.message for record in caplog.records)


def test_list_elements_returns_empty_when_app_not_found(monkeypatch) -> None:
    inspector = _inspector(monkeypatch, None)
    assert inspector.list_elements(ActiveWindow(title="x", pid=123)) == []
