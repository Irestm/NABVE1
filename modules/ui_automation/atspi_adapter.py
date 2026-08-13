from __future__ import annotations

from typing import Any

from core.logger import get_logger
from core.os_adapter.base import ActiveWindow
from modules.ui_automation.domain import UIElement

logger = get_logger(__name__)

# Container/structural roles (panel, frame, scroll pane, ...) are
# deliberately excluded — only roles a voice command could plausibly target
# are collected, everything else is just noise in the grounding prompt.
_INTERACTIVE_ROLES = {
    "push button",
    "toggle button",
    "menu item",
    "check menu item",
    "text",
    "entry",
    "check box",
    "radio button",
    "combo box",
    "list item",
    "page tab",
    "link",
}

# Guards against a pathological/very deep tree (some Electron/canvas-based
# apps, or a genuinely broken accessibility bridge) — this is a safety cap,
# not a tuned value; see the plan's Этап 0 validation checkpoint for whether
# real-world trees (PyCharm's Swing UI in particular) come anywhere near it.
_MAX_DEPTH = 25
_MAX_ELEMENTS = 200


def _require_atspi() -> Any:
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "UI automation requires AT-SPI accessibility bindings. Install them with: "
            "sudo apt-get install python3-gi gir1.2-atspi-2.0 (and enable accessibility "
            "support in your desktop environment — see scripts/atspi_smoke_test.py's "
            "docstring for the exact steps, including a JetBrains-specific IDE setting)."
        ) from exc
    return Atspi


def _extents(atspi: Any, node: Any, stats: dict[str, int]) -> tuple[int, int, int, int] | None:
    try:
        component = node.get_component_iface()
    except Exception:
        stats["failed_nodes"] += 1
        logger.debug("AT-SPI get_component_iface() failed for a node", exc_info=True)
        return None
    if component is None:
        return None
    try:
        extents = component.get_extents(atspi.CoordType.SCREEN)
        return (extents.x, extents.y, extents.width, extents.height)
    except Exception:
        stats["failed_nodes"] += 1
        logger.debug("AT-SPI get_extents() failed for a node", exc_info=True)
        return None


def _is_visible(atspi: Any, node: Any, stats: dict[str, int]) -> bool:
    try:
        states = node.get_state_set()
        return states.contains(atspi.StateType.SHOWING) and states.contains(atspi.StateType.VISIBLE)
    except Exception:
        # If state can't be read at all, err on the side of including the
        # node rather than silently dropping a possibly-real target — the
        # bbox/role checks downstream are stricter filters anyway. Still
        # counted/logged, though: a node that can't even report its state is
        # exactly the kind of failure that should show up in the
        # end-of-walk summary (see list_elements) rather than vanish
        # silently — an app whose AT-SPI tree is 100%-failing this way
        # would otherwise look identical to one that simply has no
        # elements.
        stats["failed_nodes"] += 1
        logger.debug("AT-SPI get_state_set() failed for a node", exc_info=True)
        return True


def _find_app_by_pid(atspi: Any, pid: int) -> Any | None:
    desktop = atspi.get_desktop(0)
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if app is None:
            continue
        try:
            if app.get_process_id() == pid:
                return app
        except Exception:
            # A dead/defunct DBus entry among the desktop's other apps —
            # expected background noise, not this lookup's own failure, so
            # only debug-logged rather than counted toward the target
            # app's own walk stats below.
            logger.debug("AT-SPI get_process_id() failed for a desktop entry", exc_info=True)
            continue
    return None


def _collect(atspi: Any, node: Any, depth: int, candidates: list[tuple[str, str, tuple]], stats: dict[str, int]) -> None:
    if depth > _MAX_DEPTH or len(candidates) >= _MAX_ELEMENTS * 3:
        # Collect generously (3x the final cap) before the caller prunes
        # and prioritizes by name below — cheaper than re-walking the tree
        # if the first _MAX_ELEMENTS unnamed nodes happened to come first.
        return
    stats["visited_nodes"] += 1
    try:
        role = node.get_role_name()
        name = node.get_name()
    except Exception:
        stats["failed_nodes"] += 1
        logger.debug("AT-SPI get_role_name()/get_name() failed for a node", exc_info=True)
        return

    if role in _INTERACTIVE_ROLES and _is_visible(atspi, node, stats):
        bbox = _extents(atspi, node, stats)
        if bbox is not None and bbox[2] > 0 and bbox[3] > 0:
            candidates.append((role, name, bbox))

    try:
        child_count = node.get_child_count()
    except Exception:
        stats["failed_nodes"] += 1
        logger.debug("AT-SPI get_child_count() failed for a node", exc_info=True)
        return
    for index in range(child_count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            stats["failed_nodes"] += 1
            logger.debug("AT-SPI get_child_at_index() failed for a node", exc_info=True)
            continue
        if child is not None:
            _collect(atspi, child, depth + 1, candidates, stats)


class AtspiElementInspector:
    """Adapter satisfying modules.ui_automation.ports.ElementInspectorPort
    over Linux AT-SPI. `gi`/Atspi are imported lazily inside list_elements
    (never at module import time) so importing this module — and therefore
    modules.ui_automation as a whole — never hard-fails on a machine
    without the GI bindings installed; the failure only surfaces when this
    method is actually called, exactly like core/os_adapter/screen.py's
    _require_pyautogui() defers `import pyautogui`."""

    def list_elements(self, active: ActiveWindow) -> list[UIElement]:
        pid = active.pid
        if pid is None:
            return []

        atspi = _require_atspi()
        app = _find_app_by_pid(atspi, pid)
        if app is None:
            logger.info("No AT-SPI application entry found for pid=%s", pid)
            return []

        candidates: list[tuple[str, str, tuple]] = []
        stats = {"visited_nodes": 0, "failed_nodes": 0}
        _collect(atspi, app, 0, candidates, stats)

        # Node-level failures are individually expected (dead DBus objects
        # mid-walk) and only debug-logged as they happen — but if EVERY
        # visited node failed, that's a systemic AT-SPI problem (wrong bus,
        # permissions, version mismatch), not "this app just has no
        # elements", and deserves its own visible line rather than reading
        # identical to a genuinely empty result.
        if stats["visited_nodes"] and stats["failed_nodes"] == stats["visited_nodes"]:
            logger.warning(
                "AT-SPI walk for pid=%s failed on all %d visited nodes; found 0 elements — "
                "likely a systemic AT-SPI problem, not an empty window",
                pid,
                stats["visited_nodes"],
            )
        elif stats["failed_nodes"]:
            logger.debug(
                "AT-SPI walk for pid=%s: %d/%d node accesses failed",
                pid,
                stats["failed_nodes"],
                stats["visited_nodes"],
            )

        # Named elements are far more useful to a voice command ("нажми на
        # тренды" needs a name to match against) than unlabeled ones, so
        # they're prioritized when trimming down to _MAX_ELEMENTS — an
        # unlabeled button is dropped first if the tree is too big.
        candidates.sort(key=lambda item: item[1] == "")
        trimmed = candidates[:_MAX_ELEMENTS]

        return [
            UIElement(index=i, role=role, name=name, bbox=bbox)
            for i, (role, name, bbox) in enumerate(trimmed)
        ]
