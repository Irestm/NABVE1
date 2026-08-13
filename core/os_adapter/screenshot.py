from __future__ import annotations

import mss
from PIL import Image

from core.os_adapter.base import ActiveWindow


def capture_window(active: ActiveWindow) -> tuple[Image.Image, tuple[int, int]]:
    """Screenshots just the active window's region when its geometry is
    known (see ActiveWindow.bbox), else falls back to the primary monitor.
    Returns the image together with the (x, y) screen offset of its
    top-left corner, so a caller mapping a pixel found inside the image
    (e.g. an OCR word's bounding box — see
    modules/ui_automation/ocr_adapter.py) back to absolute screen
    coordinates just adds this offset, without needing to know which branch
    was taken or re-derive the primary monitor's own position.

    Used as a vision fallback when the active app exposes no accessibility
    tree at all (Electron/canvas apps) — see
    modules/ui_automation/service_layer.py's _list_elements."""
    with mss.MSS() as sct:
        if active.bbox is not None:
            x, y, width, height = active.bbox
            region = {"left": x, "top": y, "width": max(width, 1), "height": max(height, 1)}
        else:
            region = sct.monitors[1]  # index 0 is the union of all monitors; 1 is the primary
        shot = sct.grab(region)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        return image, (region["left"], region["top"])
