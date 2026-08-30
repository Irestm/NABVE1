from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from types import ModuleType

from core.logger import get_logger
from modules.gesture_control.config import (
    CAMERA_INDEX,
    HAND_LANDMARKER_TASK_PATH,
    HAND_LANDMARKER_TASK_URL,
    MODELS_DIR,
)

logger = get_logger(__name__)

# A hand is (x, y) pairs in normalized [0, 1] camera-frame coordinates —
# index i is MediaPipe landmark i (0 wrist, 4 thumb tip, 8 index tip, ...).
Landmarks = list[tuple[float, float]]


@dataclass(frozen=True)
class FrameResult:
    # BGR frame as returned by cv2 (for the optional preview stream).
    frame: object
    # 0-2 hands, each a full 21-landmark list, left-to-right by wrist x.
    hands: list[Landmarks]


class _EmaSmoother:
    """Exponential moving average on a single (x, y) point. Without this the
    landmark stream jitters a pixel or two every frame and the cursor visibly
    shakes. alpha in (0, 1]: higher follows the hand faster / smooths less."""

    def __init__(self, alpha: float) -> None:
        self._alpha = max(0.05, min(1.0, alpha))
        self._value: tuple[float, float] | None = None

    def update(self, point: tuple[float, float]) -> tuple[float, float]:
        if self._value is None:
            self._value = point
        else:
            a = self._alpha
            self._value = (
                a * point[0] + (1 - a) * self._value[0],
                a * point[1] + (1 - a) * self._value[1],
            )
        return self._value

    def reset(self) -> None:
        self._value = None


def _require_cv2() -> ModuleType:
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Gesture control needs OpenCV. Install: pip install opencv-contrib-python"
        ) from exc
    return cv2


def _require_mediapipe() -> ModuleType:
    try:
        import mediapipe  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Gesture control needs mediapipe. Install: pip install mediapipe"
        ) from exc
    return mediapipe


def ensure_model() -> None:
    """Downloads the HandLandmarker .task file on first use (cached under
    data/models/), same one-off fetch as the Silero TTS weights."""
    if HAND_LANDMARKER_TASK_PATH.is_file():
        return
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading MediaPipe HandLandmarker model to %s", HAND_LANDMARKER_TASK_PATH)
    tmp = HAND_LANDMARKER_TASK_PATH.with_suffix(".task.part")
    urllib.request.urlretrieve(HAND_LANDMARKER_TASK_URL, tmp)  # noqa: S310 - fixed HTTPS Google URL
    tmp.replace(HAND_LANDMARKER_TASK_PATH)


class HandTracker:
    """Owns the camera and the MediaPipe HandLandmarker (Tasks API). Each
    read() grabs one frame, runs detection, and returns up to two hands with
    the tracked point (index fingertip) already EMA-smoothed per hand."""

    def __init__(self, ema_alpha: float, camera_index: int = CAMERA_INDEX) -> None:
        self._camera_index = camera_index
        self._ema_alpha = ema_alpha
        self._cv2 = _require_cv2()
        self._capture = None
        self._landmarker = None
        self._smoothers: list[_EmaSmoother] = [_EmaSmoother(ema_alpha), _EmaSmoother(ema_alpha)]

    def open(self) -> None:
        ensure_model()
        mp = _require_mediapipe()
        from mediapipe.tasks import python as mp_python  # type: ignore[import-untyped]
        from mediapipe.tasks.python import vision as mp_vision  # type: ignore[import-untyped]

        self._capture = self._cv2.VideoCapture(self._camera_index)
        if not self._capture.isOpened():
            self._capture = None
            raise RuntimeError(
                f"Не удалось открыть камеру {self._camera_index} — занята другим приложением или недоступна."
            )
        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(HAND_LANDMARKER_TASK_PATH)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self._mp_image_cls = mp.Image
        self._mp_image_format = mp.ImageFormat.SRGB
        self._frame_index = 0

    def read(self) -> FrameResult | None:
        if self._capture is None or self._landmarker is None:
            return None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            return None

        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        mp_image = self._mp_image_cls(image_format=self._mp_image_format, data=rgb)
        self._frame_index += 1
        result = self._landmarker.detect_for_video(mp_image, self._frame_index)

        hands: list[Landmarks] = []
        for hand in getattr(result, "hand_landmarks", []) or []:
            hands.append([(lm.x, lm.y) for lm in hand])
        # Stable left-to-right order so hand[0]/hand[1] don't swap frame to frame.
        hands.sort(key=lambda h: h[0][0])

        for i, hand in enumerate(hands[:2]):
            smoothed = self._smoothers[i].update(hand[8])
            hand[8] = smoothed
        for i in range(len(hands), 2):
            self._smoothers[i].reset()

        return FrameResult(frame=frame, hands=hands)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:
                logger.debug("HandLandmarker.close() raised", exc_info=True)
            self._landmarker = None
        for smoother in self._smoothers:
            smoother.reset()
