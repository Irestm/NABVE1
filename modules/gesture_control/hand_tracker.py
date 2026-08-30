from __future__ import annotations

import math
import urllib.request
from dataclasses import dataclass
from types import ModuleType

from core.logger import get_logger
from modules.gesture_control.config import (
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    EMA_MAX_ALPHA,
    EMA_MIN_ALPHA,
    EMA_SPEED_FULL,
    HAND_BBOX_MAX,
    HAND_BBOX_MIN,
    HAND_DETECTION_CONFIDENCE,
    HAND_LANDMARKER_TASK_PATH,
    HAND_LANDMARKER_TASK_URL,
    HAND_MIN_HANDEDNESS_SCORE,
    HAND_PRESENCE_CONFIDENCE,
    HAND_TRACKING_CONFIDENCE,
    MODELS_DIR,
)

logger = get_logger(__name__)

# A hand is (x, y) pairs in normalized [0, 1] camera-frame coordinates —
# index i is MediaPipe landmark i (0 wrist, 4 thumb tip, 8 index tip, ...).
Landmarks = list[tuple[float, float]]


@dataclass(frozen=True)
class FrameResult:
    frame: object  # BGR frame from cv2 (unused now that the preview is gone; kept for shape)
    hands: list[Landmarks]  # 0-2 hands, left-to-right by wrist x; index tip is smoothed
    raw_index_tips: list[tuple[float, float]]  # unsmoothed landmark 8 per hand, same order

    @property
    def raw_primary_tip(self) -> tuple[float, float] | None:
        return self.raw_index_tips[0] if self.raw_index_tips else None


def _median(values: list[float]) -> float:
    return sorted(values)[len(values) // 2]


class _AdaptiveSmoother:
    """Per-point cursor filter: a median-of-3 on the raw landmark drops
    single-frame spikes, then a one-euro-lite EMA whose blend factor scales
    with hand speed — a quick motion barely lags (alpha -> EMA_MAX_ALPHA)
    while a still hand barely trembles (alpha -> min_alpha, which
    "калибровка дрожания" tunes per user)."""

    def __init__(self, min_alpha: float = EMA_MIN_ALPHA) -> None:
        self._min_alpha = max(0.01, min(EMA_MAX_ALPHA, min_alpha))
        self._value: tuple[float, float] | None = None
        self._prev_raw: tuple[float, float] | None = None
        self._window: list[tuple[float, float]] = []

    def set_min_alpha(self, min_alpha: float) -> None:
        self._min_alpha = max(0.01, min(EMA_MAX_ALPHA, min_alpha))

    def update(self, point: tuple[float, float]) -> tuple[float, float]:
        self._window.append(point)
        if len(self._window) > 3:
            self._window.pop(0)
        point = (
            _median([p[0] for p in self._window]),
            _median([p[1] for p in self._window]),
        )

        if self._value is None or self._prev_raw is None:
            self._value = point
            self._prev_raw = point
            return point

        speed = math.hypot(point[0] - self._prev_raw[0], point[1] - self._prev_raw[1])
        self._prev_raw = point
        ratio = min(1.0, speed / EMA_SPEED_FULL) if EMA_SPEED_FULL > 0 else 1.0
        alpha = self._min_alpha + (EMA_MAX_ALPHA - self._min_alpha) * ratio

        self._value = (
            alpha * point[0] + (1 - alpha) * self._value[0],
            alpha * point[1] + (1 - alpha) * self._value[1],
        )
        return self._value

    def reset(self) -> None:
        self._value = None
        self._prev_raw = None
        self._window.clear()


def _looks_like_hand(landmarks: Landmarks) -> bool:
    """Reject a detection whose bounding box is not a plausible hand size —
    MediaPipe occasionally locks onto a face or the torso ("воспринимает
    любой объект, даже голову"); such a blob fills far more of the frame
    than a hand held up to the camera, or is vanishing-small noise."""
    xs = [p[0] for p in landmarks]
    ys = [p[1] for p in landmarks]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    span = max(width, height)
    if span < HAND_BBOX_MIN or span > HAND_BBOX_MAX:
        return False
    thinner, wider = sorted((max(width, 1e-4), max(height, 1e-4)))
    return wider / thinner <= 3.5


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
        raise RuntimeError("Gesture control needs mediapipe. Install: pip install mediapipe") from exc
    return mediapipe


def ensure_model() -> None:
    if HAND_LANDMARKER_TASK_PATH.is_file():
        return
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading MediaPipe HandLandmarker model to %s", HAND_LANDMARKER_TASK_PATH)
    tmp = HAND_LANDMARKER_TASK_PATH.with_suffix(".task.part")
    urllib.request.urlretrieve(HAND_LANDMARKER_TASK_URL, tmp)  # noqa: S310 - fixed HTTPS Google URL
    tmp.replace(HAND_LANDMARKER_TASK_PATH)


class HandTracker:
    """Owns the camera and the MediaPipe HandLandmarker (Tasks API). Each
    read() grabs the latest frame, runs detection, and returns up to two
    hands with the tracked point (index fingertip) already adaptively
    smoothed per hand."""

    def __init__(
        self, camera_index: int = CAMERA_INDEX, min_alpha: float = EMA_MIN_ALPHA
    ) -> None:
        self._camera_index = camera_index
        self._cv2 = _require_cv2()
        self._capture = None
        self._landmarker = None
        self._smoothers: list[_AdaptiveSmoother] = [
            _AdaptiveSmoother(min_alpha),
            _AdaptiveSmoother(min_alpha),
        ]

    def open(self) -> None:
        ensure_model()
        mp = _require_mediapipe()
        from mediapipe.tasks import python as mp_python  # type: ignore[import-untyped]
        from mediapipe.tasks.python import vision as mp_vision  # type: ignore[import-untyped]

        cap = self._cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            raise RuntimeError(
                f"Не удалось открыть камеру {self._camera_index} — занята другим приложением или недоступна."
            )
        # Small frame + tiny buffer = lower latency and less CPU per frame.
        cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(self._cv2.CAP_PROP_FPS, 30)
        try:
            cap.set(self._cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self._capture = cap

        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(HAND_LANDMARKER_TASK_PATH)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=HAND_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=HAND_PRESENCE_CONFIDENCE,
            min_tracking_confidence=HAND_TRACKING_CONFIDENCE,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self._mp_image_cls = mp.Image
        self._mp_image_format = mp.ImageFormat.SRGB
        self._frame_index = 0

    def set_min_alpha(self, min_alpha: float) -> None:
        for smoother in self._smoothers:
            smoother.set_min_alpha(min_alpha)

    def read(self) -> FrameResult | None:
        if self._capture is None or self._landmarker is None:
            return None
        # Drain any queued frame so we always act on the freshest one.
        self._capture.grab()
        ok, frame = self._capture.retrieve()
        if not ok or frame is None:
            ok, frame = self._capture.read()
            if not ok or frame is None:
                return None

        # Mirror horizontally so moving your hand right moves the cursor
        # right — a raw webcam frame is un-mirrored, which the user reported
        # as "право и лево перепутаны".
        frame = self._cv2.flip(frame, 1)
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        mp_image = self._mp_image_cls(image_format=self._mp_image_format, data=rgb)
        self._frame_index += 1
        result = self._landmarker.detect_for_video(mp_image, self._frame_index)

        landmark_sets = getattr(result, "hand_landmarks", []) or []
        handedness_sets = getattr(result, "handedness", []) or []
        hands: list[Landmarks] = []
        for i, hand in enumerate(landmark_sets):
            score = 1.0
            if i < len(handedness_sets) and handedness_sets[i]:
                score = getattr(handedness_sets[i][0], "score", 1.0)
            if score < HAND_MIN_HANDEDNESS_SCORE:
                continue
            points: Landmarks = [(lm.x, lm.y) for lm in hand]
            if not _looks_like_hand(points):
                continue
            hands.append(points)
        hands.sort(key=lambda h: h[0][0])

        raw_index_tips = [hand[8] for hand in hands[:2]]
        for i, hand in enumerate(hands[:2]):
            hand[8] = self._smoothers[i].update(hand[8])
        for i in range(len(hands), 2):
            self._smoothers[i].reset()

        return FrameResult(frame=frame, hands=hands, raw_index_tips=raw_index_tips)

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
