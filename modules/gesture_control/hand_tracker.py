from __future__ import annotations

import math
import threading
import time
import urllib.request
from dataclasses import dataclass
from types import ModuleType

from core.logger import get_logger
from modules.gesture_control.config import (
    CAMERA_FOURCC,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_STALL_REOPEN_SECONDS,
    CAMERA_WIDTH,
    GESTURE_DEBUG,
    GESTURE_TRY_GPU,
    HAND_BBOX_MAX,
    HAND_BBOX_MIN,
    HAND_DETECTION_CONFIDENCE,
    HAND_KNUCKLE_RADIUS_TOLERANCE,
    HAND_LANDMARKER_TASK_PATH,
    HAND_LANDMARKER_TASK_URL,
    HAND_MIN_HANDEDNESS_SCORE,
    HAND_PRESENCE_CONFIDENCE,
    HAND_TRACKING_CONFIDENCE,
    MODELS_DIR,
    ONE_EURO_MIN_CUTOFF,
)
from modules.gesture_control.one_euro_filter import OneEuroFilter

logger = get_logger(__name__)

# A hand is (x, y) pairs in normalized [0, 1] camera-frame coordinates —
# index i is MediaPipe landmark i (0 wrist, 4 thumb tip, 8 index tip, ...).
Landmarks = list[tuple[float, float]]


@dataclass(frozen=True)
class FrameResult:
    frame: object  # mirrored BGR frame from cv2 (for the optional preview)
    hands: list[Landmarks]  # 0-2 hands, left-to-right by wrist x; index tip is smoothed
    raw_index_tips: list[tuple[float, float]]  # unsmoothed landmark 8 per hand, same order
    fresh: bool = True  # False = re-smoothed from the last detection (no new camera frame)
    brightness: float = -1.0  # mean pixel value 0-255 of this frame, -1 if unknown

    @property
    def raw_primary_tip(self) -> tuple[float, float] | None:
        return self.raw_index_tips[0] if self.raw_index_tips else None


class _CameraReader:
    """Owns the VideoCapture on its own daemon thread, continuously reading
    so the newest frame is always ready — the worker loop never blocks
    inside cap.read() (a big part of the choppiness on a slow/dark webcam).
    If reads stop succeeding for CAMERA_STALL_REOPEN_SECONDS (a driver
    stall, typically an abrupt lighting change forcing exposure
    renegotiation) it releases and reopens the camera instead of wedging
    the cursor forever."""

    def __init__(self, cv2, camera_index: int, configure, capture) -> None:
        self._cv2 = cv2
        self._camera_index = camera_index
        self._configure = configure  # (cap) -> None, applies fourcc/res/fps
        self._cap = capture  # already opened + configured by HandTracker.open()
        self._lock = threading.Lock()
        self._frame = None
        self._stop = threading.Event()
        self._last_ok = time.monotonic()
        self._ever_ok = False
        self._thread = threading.Thread(target=self._loop, name="gesture-camera", daemon=True)
        self._thread.start()

    def _reopen(self):
        try:
            self._cap.release()
        except Exception:
            pass
        cap = self._cv2.VideoCapture(self._camera_index)
        if cap.isOpened():
            self._configure(cap)
        self._cap = cap
        self._last_ok = time.monotonic()

    def _loop(self) -> None:
        while not self._stop.is_set():
            ok = False
            frame = None
            try:
                ok, frame = self._cap.read()
            except Exception:
                ok = False
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
                self._last_ok = time.monotonic()
                self._ever_ok = True
            else:
                self._stop.wait(0.03)
                # Only treat a gap as a stall if frames were flowing before —
                # a merely slow (few-fps) feed must not trigger a reopen loop.
                if self._ever_ok and time.monotonic() - self._last_ok > CAMERA_STALL_REOPEN_SECONDS:
                    logger.warning("Gesture camera stalled — reopening")
                    self._reopen()

    def latest(self):
        with self._lock:
            return self._frame

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            self._cap.release()
        except Exception:
            pass


def _looks_like_hand(landmarks: Landmarks) -> bool:
    """Reject a detection that isn't hand-shaped. A loose bbox check throws
    out noise dots and frame-filling blobs; then the real test — the four
    knuckles (5, 9, 13, 17) of a genuine hand sit at a consistent distance
    from the wrist, whereas a face/torso false positive has them scattered.
    Deliberately lenient: a real hand at any angle must pass."""
    if len(landmarks) < 18:
        return False
    xs = [p[0] for p in landmarks]
    ys = [p[1] for p in landmarks]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span < HAND_BBOX_MIN or span > HAND_BBOX_MAX:
        return False

    wrist = landmarks[0]
    radii = [
        math.hypot(landmarks[k][0] - wrist[0], landmarks[k][1] - wrist[1])
        for k in (5, 9, 13, 17)
    ]
    mean_radius = sum(radii) / len(radii)
    if mean_radius < 1e-3:
        return False
    lo = mean_radius / HAND_KNUCKLE_RADIUS_TOLERANCE
    hi = mean_radius * HAND_KNUCKLE_RADIUS_TOLERANCE
    return all(lo <= r <= hi for r in radii)


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
        self, camera_index: int = CAMERA_INDEX, min_cutoff: float = ONE_EURO_MIN_CUTOFF
    ) -> None:
        self._camera_index = camera_index
        self._cv2 = _require_cv2()
        self._capture = None
        self._reader: _CameraReader | None = None
        self._landmarker = None
        self._smoothers: list[OneEuroFilter] = [
            OneEuroFilter(min_cutoff),
            OneEuroFilter(min_cutoff),
        ]
        self._last_seen_frame = None
        self._last_frame = None
        self._last_full_hands: list[Landmarks] | None = None
        self._last_raw_tips: list[tuple[float, float]] = []
        self._last_brightness = -1.0
        # Diagnostics (§1): rolling processing FPS + last detect latency.
        self._diag_frames = 0
        self._diag_since = time.monotonic()
        self._diag_detect_ms = 0.0
        self.delegate = "cpu"

    def open(self) -> None:
        ensure_model()
        mp = _require_mediapipe()
        from mediapipe.tasks import python as mp_python  # type: ignore[import-untyped]
        from mediapipe.tasks.python import vision as mp_vision  # type: ignore[import-untyped]

        def _configure(cap) -> None:
            try:
                cap.set(self._cv2.CAP_PROP_FOURCC, self._cv2.VideoWriter_fourcc(*CAMERA_FOURCC))
            except Exception:
                logger.debug("Camera FOURCC set failed", exc_info=True)
            cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            cap.set(self._cv2.CAP_PROP_FPS, CAMERA_FPS)
            try:
                cap.set(self._cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

        cap = self._cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(
                f"Не удалось открыть камеру {self._camera_index} — занята другим приложением или недоступна."
            )
        _configure(cap)
        logger.info(
            "Gesture camera: requested %dx%d@%d %s, driver granted %dx%d@%.0f",
            CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, CAMERA_FOURCC,
            int(cap.get(self._cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(self._cv2.CAP_PROP_FRAME_HEIGHT)),
            cap.get(self._cv2.CAP_PROP_FPS),
        )
        # The reader thread owns this single, already-configured capture —
        # opening the camera twice (probe + reader) left some UVC drivers
        # renegotiating and dropped the real fps to near zero.
        self._reader = _CameraReader(self._cv2, self._camera_index, _configure, cap)
        self._capture = True  # sentinel: camera is owned by the reader thread

        def _make_options(delegate):
            return mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(
                    model_asset_path=str(HAND_LANDMARKER_TASK_PATH), delegate=delegate
                ),
                running_mode=mp_vision.RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=HAND_DETECTION_CONFIDENCE,
                min_hand_presence_confidence=HAND_PRESENCE_CONFIDENCE,
                min_tracking_confidence=HAND_TRACKING_CONFIDENCE,
            )

        cpu = mp_python.BaseOptions.Delegate.CPU
        gpu = mp_python.BaseOptions.Delegate.GPU
        self._landmarker = None
        if GESTURE_TRY_GPU:
            try:
                self._landmarker = mp_vision.HandLandmarker.create_from_options(_make_options(gpu))
                self.delegate = "gpu"
                logger.info("Gesture HandLandmarker: GPU delegate active")
            except Exception:
                logger.info("Gesture HandLandmarker: GPU delegate unavailable, falling back to CPU", exc_info=True)
        if self._landmarker is None:
            self._landmarker = mp_vision.HandLandmarker.create_from_options(_make_options(cpu))
            self.delegate = "cpu"
            logger.info("Gesture HandLandmarker: CPU (XNNPACK) delegate active")

        self._mp_image_cls = mp.Image
        self._mp_image_format = mp.ImageFormat.SRGB
        # VIDEO mode wants a real, monotonically increasing millisecond
        # timestamp — a frame counter (1, 2, 3, ...) made the model treat
        # frames as 1 ms apart and its temporal tracking fell apart.
        self._epoch = time.monotonic()
        self._last_timestamp_ms = -1

    def set_min_cutoff(self, min_cutoff: float) -> None:
        for smoother in self._smoothers:
            smoother.set_min_cutoff(min_cutoff)

    def read(self) -> FrameResult | None:
        if self._reader is None or self._landmarker is None:
            return None
        raw = self._reader.latest()
        if raw is None:
            return None
        new_frame = raw is not self._last_seen_frame
        self._last_seen_frame = raw
        timestamp_s = time.monotonic() - self._epoch

        if new_frame:
            # Mirror horizontally so moving your hand right moves the cursor
            # right — a raw webcam frame is un-mirrored.
            frame = self._cv2.flip(raw, 1)
            try:
                self._last_brightness = float(frame.mean())
            except Exception:
                self._last_brightness = -1.0
            rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
            mp_image = self._mp_image_cls(image_format=self._mp_image_format, data=rgb)
            timestamp_ms = int(timestamp_s * 1000)
            if timestamp_ms <= self._last_timestamp_ms:
                timestamp_ms = self._last_timestamp_ms + 1
            self._last_timestamp_ms = timestamp_ms

            detect_start = time.perf_counter()
            result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
            self._diag_detect_ms = (time.perf_counter() - detect_start) * 1000.0

            landmark_sets = getattr(result, "hand_landmarks", []) or []
            handedness_sets = getattr(result, "handedness", []) or []
            hands = []
            for i, hand in enumerate(landmark_sets):
                score = 1.0
                if i < len(handedness_sets) and handedness_sets[i]:
                    score = getattr(handedness_sets[i][0], "score", 1.0)
                if score < HAND_MIN_HANDEDNESS_SCORE:
                    if GESTURE_DEBUG:
                        logger.debug("hand %d rejected: handedness score %.2f", i, score)
                    continue
                points: Landmarks = [(lm.x, lm.y) for lm in hand]
                if not _looks_like_hand(points):
                    if GESTURE_DEBUG:
                        logger.debug("hand %d rejected: geometry (bbox/knuckles)", i)
                    continue
                hands.append(points)
            hands.sort(key=lambda h: h[0][0])
            self._log_diagnostics(len(landmark_sets), hands, frame)

            self._last_frame = frame
            self._last_full_hands = [list(h) for h in hands]
            self._last_raw_tips = [h[8] for h in hands[:2]]
        elif self._last_full_hands is None:
            return None  # no detection has happened yet
        else:
            # No new camera frame: re-emit the last detection so the worker
            # can keep easing the cursor toward it at the full tick rate
            # instead of hard-stepping at the (possibly low) camera fps.
            frame = self._last_frame
            hands = [list(h) for h in self._last_full_hands]

        raw_index_tips = list(self._last_raw_tips)
        for i in range(min(len(hands), 2)):
            hands[i][8] = self._smoothers[i].update(raw_index_tips[i], timestamp_s)
        for i in range(len(hands), 2):
            self._smoothers[i].reset()

        return FrameResult(
            frame=frame,
            hands=hands,
            raw_index_tips=raw_index_tips,
            fresh=new_frame,
            brightness=self._last_brightness,
        )

    def _log_diagnostics(self, raw_count: int, hands: list[Landmarks], frame) -> None:
        self._diag_frames += 1
        elapsed = time.monotonic() - self._diag_since
        if elapsed >= 2.0:
            fps = self._diag_frames / elapsed
            try:
                brightness = float(frame.mean())
            except Exception:
                brightness = -1.0
            logger.info(
                "Gesture worker: %.1f fps, detect %.1f ms (%s), brightness %.0f/255, %d hand(s)",
                fps, self._diag_detect_ms, self.delegate, brightness, len(hands),
            )
            if fps < 15.0 or (0 <= brightness < 40.0):
                logger.warning(
                    "Gesture input is poor (%.1f fps, brightness %.0f/255) — a slow or dark "
                    "camera feed is the usual cause of shaky/missed tracking; add light on the hand.",
                    fps, brightness,
                )
            self._diag_frames = 0
            self._diag_since = time.monotonic()
        if GESTURE_DEBUG and hands:
            h = hands[0]
            logger.debug(
                "raw landmarks: wrist=(%.3f,%.3f) thumb=(%.3f,%.3f) index=(%.3f,%.3f) "
                "mid_mcp=(%.3f,%.3f) [%d raw hands]",
                h[0][0], h[0][1], h[4][0], h[4][1], h[8][0], h[8][1], h[9][0], h[9][1], raw_count,
            )

    def close(self) -> None:
        if self._reader is not None:
            self._reader.stop()
            self._reader = None
        self._capture = None
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:
                logger.debug("HandLandmarker.close() raised", exc_info=True)
            self._landmarker = None
        for smoother in self._smoothers:
            smoother.reset()
