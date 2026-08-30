from __future__ import annotations

from core.logger import get_logger
from modules.gesture_control.hand_tracker import Landmarks, _require_cv2

logger = get_logger(__name__)

# MediaPipe hand skeleton — pairs of landmark indices to connect.
_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),  # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),  # index
    (5, 9), (9, 10), (10, 11), (11, 12),  # middle
    (9, 13), (13, 14), (14, 15), (15, 16),  # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),  # palm base
)

_JPEG_QUALITY = 60
_MAX_WIDTH = 640  # downscale the preview so the poll stays light


def render_jpeg(frame, hands: list[Landmarks]) -> bytes | None:
    """Draws the detected hand skeleton(s) over `frame` (BGR, already
    mirrored) and returns a JPEG. Used only by the optional /api/gesture/
    preview endpoint for the diagnostic overlay — never on the hot path."""
    try:
        cv2 = _require_cv2()
        img = frame
        h, w = img.shape[:2]
        if w > _MAX_WIDTH:
            scale = _MAX_WIDTH / w
            img = cv2.resize(img, (_MAX_WIDTH, int(h * scale)))
            h, w = img.shape[:2]
        else:
            img = img.copy()

        for hand in hands:
            pts = [(int(x * w), int(y * h)) for (x, y) in hand]
            for a, b in _CONNECTIONS:
                if a < len(pts) and b < len(pts):
                    cv2.line(img, pts[a], pts[b], (0, 220, 0), 2)
            for i, p in enumerate(pts):
                colour = (0, 128, 255) if i in (4, 8) else (0, 220, 0)
                cv2.circle(img, p, 4 if i in (4, 8) else 3, colour, -1)

        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
        if not ok:
            return None
        return buf.tobytes()
    except Exception:
        logger.debug("Gesture preview render failed", exc_info=True)
        return None
