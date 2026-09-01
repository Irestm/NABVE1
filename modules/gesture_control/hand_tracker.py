from __future__ import annotations

import math
import threading
import time
import urllib.request
from dataclasses import dataclass
from types import ModuleType

from core.logger import get_logger
from modules.gesture_control.config import (
    CAMERA_ADAPT_BAD_WINDOWS,
    CAMERA_ADAPT_CHECK_SECONDS,
    CAMERA_ADAPTIVE_EXPOSURE,
    CAMERA_EXPOSURE_STEPS,
    CAMERA_FORCE_EXPOSURE,
    CAMERA_FOURCC,
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_MANUAL_BRIGHTNESS,
    CAMERA_MIN_ACCEPTABLE_FPS,
    CAMERA_STALL_REOPEN_SECONDS,
    CAMERA_WIDTH,
    GESTURE_DEBUG,
    GESTURE_DIAG,
    GESTURE_MP_MODE,
    GESTURE_TRY_GPU,
    HAND_BBOX_MAX,
    HAND_BBOX_MIN,
    HAND_DETECTION_CONFIDENCE,
    HAND_KNUCKLE_RADIUS_TOLERANCE,
    HAND_LANDMARKER_TASK_PATH,
    HAND_LANDMARKER_TASK_URL,
    HAND_MIN_SCALE,
    HAND_NUM_HANDS,
    HAND_PRESENCE_CONFIDENCE,
    LANDMARK_BOUND,
    HAND_TRACKING_CONFIDENCE,
    MODELS_DIR,
)

logger = get_logger(__name__)

# A hand is (x, y) pairs in normalized [0, 1] camera-frame coordinates —
# index i is MediaPipe landmark i (0 wrist, 4 thumb tip, 8 index tip, ...).
Landmarks = list[tuple[float, float]]


@dataclass(frozen=True)
class FrameResult:
    frame: object  # mirrored BGR frame from cv2 (for the optional preview)
    hands: list[Landmarks]  # 0-2 raw hands, left-to-right by wrist x
    brightness: float = -1.0  # mean pixel value 0-255 of this frame, -1 if unknown
    capture_t: float = 0.0  # time.monotonic() when the reader grabbed this frame


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
        self._frame_id = 0  # bumped on every successful read — lets HandTracker spot re-used frames
        self._frame_t = time.monotonic()  # capture time of _frame, for a real One-Euro dt
        self._reads = 0  # successful reads since start, for the reader-fps diagnostic
        self._stop = threading.Event()
        self._last_ok = time.monotonic()
        self._ever_ok = False
        # Exposure control. _manual_exposure None = the camera's own auto
        # exposure (fine in bright light); an int = a forced short shutter,
        # either set once from NABVE_GESTURE_EXPOSURE (_exposure_forced) or
        # reached by the adaptive ramp stepping through CAMERA_EXPOSURE_STEPS
        # when the delivered fps stays too low.
        self._exposure_forced = CAMERA_FORCE_EXPOSURE is not None
        self._manual_exposure: int | None = CAMERA_FORCE_EXPOSURE
        self._exposure_step_idx = -1
        self._adapt_since = time.monotonic()
        self._adapt_reads_mark = 0
        self._adapt_bad = 0
        self._adapt_exhausted = False
        if self._manual_exposure is not None:
            self._apply_exposure(self._cap)
        self._thread = threading.Thread(target=self._loop, name="gesture-camera", daemon=True)
        self._thread.start()

    def exposure_mode(self) -> str:
        if self._manual_exposure is None:
            return "auto"
        return f"manual {self._manual_exposure}" + (" forced" if self._exposure_forced else "")

    def _apply_exposure(self, cap) -> None:
        """Force manual exposure at _manual_exposure + lift brightness so the
        shorter shutter still yields a usable frame. No-op while on auto."""
        if self._manual_exposure is None:
            return
        try:
            cap.set(self._cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 1 = manual on V4L2 UVC
            cap.set(self._cv2.CAP_PROP_EXPOSURE, self._manual_exposure)
            cap.set(self._cv2.CAP_PROP_BRIGHTNESS, CAMERA_MANUAL_BRIGHTNESS)
        except Exception:
            logger.debug("Camera exposure set failed", exc_info=True)

    def _adapt_exposure(self) -> None:
        """Called from the reader loop: if the feed is delivering under
        CAMERA_MIN_ACCEPTABLE_FPS, step the shutter down one notch."""
        if self._exposure_forced or not CAMERA_ADAPTIVE_EXPOSURE or self._adapt_exhausted:
            return
        now = time.monotonic()
        elapsed = now - self._adapt_since
        if elapsed < CAMERA_ADAPT_CHECK_SECONDS:
            return
        fps = (self._reads - self._adapt_reads_mark) / elapsed
        self._adapt_since = now
        self._adapt_reads_mark = self._reads
        if fps >= CAMERA_MIN_ACCEPTABLE_FPS:
            self._adapt_bad = 0
            return
        self._adapt_bad += 1
        if self._adapt_bad < CAMERA_ADAPT_BAD_WINDOWS:
            return
        self._adapt_bad = 0
        if self._exposure_step_idx + 1 >= len(CAMERA_EXPOSURE_STEPS):
            self._adapt_exhausted = True
            logger.warning(
                "Gesture camera still %.1f fps at the shortest exposure — add light on the hand",
                fps,
            )
            return
        self._exposure_step_idx += 1
        self._manual_exposure = CAMERA_EXPOSURE_STEPS[self._exposure_step_idx]
        self._apply_exposure(self._cap)
        logger.info(
            "Gesture camera: %.1f fps delivered — switching to manual exposure %d",
            fps,
            self._manual_exposure,
        )

    def _reopen(self):
        try:
            self._cap.release()
        except Exception:
            pass
        cap = self._cv2.VideoCapture(self._camera_index)
        if cap.isOpened():
            self._configure(cap)
            self._apply_exposure(cap)  # keep the chosen shutter across a reopen
        self._cap = cap
        self._last_ok = time.monotonic()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                ok = False
                frame = None
                try:
                    ok, frame = self._cap.read()
                except Exception:
                    ok = False
                if ok and frame is not None:
                    grabbed = time.monotonic()
                    with self._lock:
                        self._frame = frame
                        self._frame_id += 1
                        self._frame_t = grabbed
                        self._reads += 1
                    self._last_ok = grabbed
                    self._ever_ok = True
                    self._adapt_exposure()
                else:
                    self._stop.wait(0.03)
                    # Only treat a gap as a stall if frames were flowing
                    # before — a merely slow (few-fps) feed must not trigger
                    # a reopen loop.
                    if (
                        self._ever_ok
                        and time.monotonic() - self._last_ok > CAMERA_STALL_REOPEN_SECONDS
                    ):
                        logger.warning("Gesture camera stalled — reopening")
                        self._reopen()
        finally:
            # Release the camera from *this* thread once the loop is done —
            # calling cap.release() from another thread while this one is
            # blocked in cap.read() used to hang gesture_stop.
            try:
                self._cap.release()
            except Exception:
                pass

    def latest(self) -> tuple[object, int, float]:
        with self._lock:
            return self._frame, self._frame_id, self._frame_t

    def reads_since(self, previous: int) -> tuple[int, int]:
        """(new successful reads since `previous`, current total) — the raw
        camera delivery rate, separate from the worker's processing fps."""
        with self._lock:
            return self._reads - previous, self._reads

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)


def _hand_reject_reason(landmarks: Landmarks) -> str | None:
    """None if the detection is hand-shaped, else a short reason tag
    ("few_points" / "blowup" / "bbox" / "knuckles") — the tag is only for
    the diagnostic counters. "blowup" catches a frame where MediaPipe's
    skeleton came apart (a point flew off, the hand shrank to nothing);
    then a loose bbox check throws out noise dots and frame-filling blobs;
    then the real test — the four knuckles (5, 9, 13, 17) sit at a
    consistent distance from the wrist. Deliberately lenient otherwise: a
    real hand at any angle must pass."""
    if len(landmarks) < 18:
        return "few_points"
    if any(
        not (-(LANDMARK_BOUND - 1.0) <= c <= LANDMARK_BOUND) for p in landmarks for c in p
    ):
        return "blowup"
    scale = math.hypot(landmarks[9][0] - landmarks[0][0], landmarks[9][1] - landmarks[0][1])
    if scale < HAND_MIN_SCALE:
        return "blowup"
    xs = [p[0] for p in landmarks]
    ys = [p[1] for p in landmarks]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span < HAND_BBOX_MIN or span > HAND_BBOX_MAX:
        return "bbox"

    wrist = landmarks[0]
    radii = [
        math.hypot(landmarks[k][0] - wrist[0], landmarks[k][1] - wrist[1])
        for k in (5, 9, 13, 17)
    ]
    mean_radius = sum(radii) / len(radii)
    if mean_radius < 1e-3:
        return "knuckles"
    lo = mean_radius / HAND_KNUCKLE_RADIUS_TOLERANCE
    hi = mean_radius * HAND_KNUCKLE_RADIUS_TOLERANCE
    return None if all(lo <= r <= hi for r in radii) else "knuckles"


def _looks_like_hand(landmarks: Landmarks) -> bool:
    return _hand_reject_reason(landmarks) is None


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
    """Owns the camera (via a reader thread) and the MediaPipe HandLandmarker
    (Tasks API). Each read() takes the latest frame, runs detection and
    returns up to two raw hands — all smoothing/interpretation is the
    worker's job now."""

    def __init__(self, camera_index: int = CAMERA_INDEX) -> None:
        self._camera_index = camera_index
        self._cv2 = _require_cv2()
        self._capture = None
        self._reader: _CameraReader | None = None
        self._landmarker = None
        # Diagnostics: rolling processing FPS + last detect latency, plus (when
        # GESTURE_DIAG) camera-reader rate, re-used-frame count and per-gate
        # rejection tally — all reset every time _log_diagnostics() emits.
        self._diag_frames = 0
        self._diag_since = time.monotonic()
        self._diag_detect_ms = 0.0
        self.delegate = "cpu"
        self._last_frame_id = -1
        self._diag_reads_mark = 0
        self._diag_ticks = 0
        self._diag_dup = 0
        self._diag_raw_hands = 0
        self._diag_accepted = 0
        self._diag_rej_bbox = 0
        self._diag_rej_knuckles = 0
        self._diag_rej_blowup = 0

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

        self._image_mode = GESTURE_MP_MODE == "image"
        run_mode = (
            mp_vision.RunningMode.IMAGE if self._image_mode else mp_vision.RunningMode.VIDEO
        )

        def _make_options(delegate):
            return mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(
                    model_asset_path=str(HAND_LANDMARKER_TASK_PATH), delegate=delegate
                ),
                running_mode=run_mode,
                num_hands=HAND_NUM_HANDS,
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

        logger.info("Gesture HandLandmarker: running mode %s", "IMAGE" if self._image_mode else "VIDEO")
        self._mp_image_cls = mp.Image
        self._mp_image_format = mp.ImageFormat.SRGB
        # VIDEO mode wants a real, monotonically increasing millisecond
        # timestamp — a frame counter (1, 2, 3, ...) made the model treat
        # frames as 1 ms apart and its temporal tracking fell apart.
        self._epoch = time.monotonic()
        self._last_timestamp_ms = -1

    def read(self) -> FrameResult | None:
        if self._reader is None or self._landmarker is None:
            return None
        self._diag_ticks += 1
        raw, frame_id, frame_t = self._reader.latest()
        if raw is None:
            return None
        if frame_id == self._last_frame_id:
            # Same pixels as last tick — skip detection entirely so we neither
            # burn GPU nor advance MediaPipe's VIDEO timestamp on a frame it
            # already saw. The worker reads None as "hold position".
            self._diag_dup += 1
            return None
        self._last_frame_id = frame_id

        # Mirror horizontally so moving your hand right moves the cursor
        # right — a raw webcam frame is un-mirrored.
        frame = self._cv2.flip(raw, 1)
        try:
            brightness = float(frame.mean())
        except Exception:
            brightness = -1.0
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        mp_image = self._mp_image_cls(image_format=self._mp_image_format, data=rgb)
        # Timestamp from the frame's capture time, not "now" — the reader
        # thread runs ahead of this loop, and a wall-clock stamp made the
        # One-Euro dt (and MediaPipe's tracking) lie whenever the two drifted.
        timestamp_ms = int((frame_t - self._epoch) * 1000)
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        detect_start = time.perf_counter()
        if self._image_mode:
            result = self._landmarker.detect(mp_image)
        else:
            result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
        self._diag_detect_ms = (time.perf_counter() - detect_start) * 1000.0

        landmark_sets = getattr(result, "hand_landmarks", []) or []
        self._diag_raw_hands += len(landmark_sets)
        hands: list[Landmarks] = []
        for i, hand in enumerate(landmark_sets):
            points: Landmarks = [(lm.x, lm.y) for lm in hand]
            reason = _hand_reject_reason(points)
            if reason is not None:
                if reason == "bbox":
                    self._diag_rej_bbox += 1
                elif reason == "blowup":
                    self._diag_rej_blowup += 1
                else:
                    self._diag_rej_knuckles += 1
                if GESTURE_DEBUG:
                    logger.debug("hand %d rejected: geometry (%s)", i, reason)
                continue
            self._diag_accepted += 1
            hands.append(points)
        hands.sort(key=lambda h: h[0][0])
        self._log_diagnostics(len(landmark_sets), hands, frame)

        return FrameResult(frame=frame, hands=hands, brightness=brightness, capture_t=frame_t)

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
            if GESTURE_DIAG:
                new_reads, self._diag_reads_mark = (
                    self._reader.reads_since(self._diag_reads_mark)
                    if self._reader is not None
                    else (0, self._diag_reads_mark)
                )
                cam_fps = new_reads / elapsed
                dup_pct = 100.0 * self._diag_dup / max(self._diag_ticks, 1)
                exposure = self._reader.exposure_mode() if self._reader is not None else "?"
                logger.info(
                    "Gesture camera: %.1f fps delivered (exposure %s), %.0f%% ticks skipped a "
                    "stale frame | raw hands %d, accepted %d, rejected bbox %d / knuckles %d "
                    "/ blowup %d",
                    cam_fps, exposure, dup_pct, self._diag_raw_hands, self._diag_accepted,
                    self._diag_rej_bbox, self._diag_rej_knuckles, self._diag_rej_blowup,
                )
                self._diag_ticks = 0
                self._diag_dup = 0
                self._diag_raw_hands = 0
                self._diag_accepted = 0
                self._diag_rej_bbox = 0
                self._diag_rej_knuckles = 0
                self._diag_rej_blowup = 0
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
