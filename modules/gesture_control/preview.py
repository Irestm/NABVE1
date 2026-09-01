from __future__ import annotations

from core.logger import get_logger
from modules.gesture_control.gesture_recognizer import finger_straightness, thumb_gap
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

# fingertip landmark -> (label, BGR colour). Each finger gets its own colour
# so the user can see which tips MediaPipe is actually holding.
_TIPS = {
    4: ("T", (0, 165, 255)),   # thumb  — orange
    8: ("1", (0, 235, 0)),     # index  — green
    12: ("2", (255, 235, 0)),  # middle — cyan
    16: ("3", (255, 0, 235)),  # ring   — magenta
    20: ("4", (40, 40, 255)),  # pinky  — red
}

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
                    cv2.line(img, pts[a], pts[b], (0, 150, 0), 2)
            # non-tip joints: small grey dots
            for i, p in enumerate(pts):
                if i not in _TIPS:
                    cv2.circle(img, p, 3, (150, 150, 150), -1)
            # fingertips: big filled dot + outline + label, one colour each
            for idx, (label, colour) in _TIPS.items():
                if idx >= len(pts):
                    continue
                p = pts[idx]
                cv2.circle(img, p, 8, colour, -1)
                cv2.circle(img, p, 8, (255, 255, 255), 1)
                cv2.putText(
                    img, label, (p[0] + 10, p[1] + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2, cv2.LINE_AA
                )

            # per-finger straightness readout + thumb gap, top-left
            if len(hand) >= 21:
                s_idx, s_mid, s_ring, s_pnk = finger_straightness(hand)
                tg = thumb_gap(hand)
                text = (
                    f"idx {s_idx:.2f}  mid {s_mid:.2f}  ring {s_ring:.2f}  "
                    f"pnk {s_pnk:.2f}  tgap {tg:.2f}"
                )
                cv2.putText(
                    img, text, (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA
                )
                cv2.putText(
                    img, text, (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA
                )

        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
        if not ok:
            return None
        return buf.tobytes()
    except Exception:
        logger.debug("Gesture preview render failed", exc_info=True)
        return None
