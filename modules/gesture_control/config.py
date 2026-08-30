from __future__ import annotations

from core.config import DATA_DIR

# Per-user profile facts written by calibration.CalibrationSession: the
# pinch threshold, plus the jitter-derived deadzone and resting smoothing.
# The tracking-zone override is optional and set by hand, not calibrated.
GESTURE_PINCH_THRESHOLD_KEY = "gesture_pinch_threshold"
GESTURE_DEADZONE_PX_KEY = "gesture_deadzone_px"
GESTURE_MIN_ALPHA_KEY = "gesture_min_alpha"
GESTURE_TRACKING_ZONE_KEY = "gesture_tracking_zone"

# Pinch detection is scale-invariant: dist(thumb_tip, index_tip) divided by
# hand span dist(wrist, index_mcp). ~0.35 when the fingers touch, ~1.0+ when
# the hand is open — so it doesn't drift with camera distance / hand size.
# Calibration tunes this per user; this default works without calibrating.
DEFAULT_PINCH_RATIO = 0.45
DEFAULT_TRACKING_ZONE = 0.55  # central fraction of the camera frame that maps to the whole screen

# Ignore final on-screen cursor moves smaller than this — kills the last of
# the landmark shimmer so a resting hand doesn't twitch the pointer. This is
# the fallback; "калибровка дрожания" measures the user's own tremor and
# stores a personal value under GESTURE_DEADZONE_PX_KEY.
CURSOR_DEADZONE_PX = 3
DEADZONE_PX_MIN = 2
DEADZONE_PX_MAX = 40

# Fixed 2x cursor magnification while gesture mode is on — a locked
# constant, not a setting ("не на 10% а на 2").
CURSOR_SCALE = 2.0

# Processing rate — enough for a responsive cursor without pinning a core.
PROCESSING_FPS = 24
CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# Adaptive (one-euro-style) smoothing: alpha rises with hand speed, so a
# fast move barely lags while a still hand is heavily smoothed. EMA_MIN_ALPHA
# is the fallback resting blend; "калибровка дрожания" replaces it with a
# personal value between MIN_ALPHA_FLOOR (heavy tremor) and MIN_ALPHA_CEIL
# (steady hand), stored under GESTURE_MIN_ALPHA_KEY.
EMA_MIN_ALPHA = 0.06
EMA_MAX_ALPHA = 0.90
EMA_SPEED_FULL = 0.05  # normalized units/frame at which smoothing is fully "off"
MIN_ALPHA_FLOOR = 0.03
MIN_ALPHA_CEIL = 0.12

# "Калибровка дрожания": hold the hand still for this many frames, measure
# the RMS tremor of the fingertip, and map it (in screen px) across this
# band to a personal deadzone + resting alpha.
STEADY_CALIBRATION_SAMPLES = 45
JITTER_LOW_PX = 1.5
JITTER_HIGH_PX = 9.0

# Pinch = click. Hysteresis (release once the ratio climbs to 1.5x the
# entry threshold) + a 2-frame debounce so a click never flickers.
PINCH_RELEASE_MULT = 1.5
PINCH_DEBOUNCE_FRAMES = 2

# The physical mouse always wins: the instant the real cursor moves by
# more than this (px) from where the worker last put it, gesture control
# yields for this many seconds (refreshed on every further physical move).
PHYSICAL_MOUSE_THRESHOLD_PX = 14
PHYSICAL_MOUSE_OVERRIDE_SECONDS = 1.2

# Two-hand zoom: minimum spread change per frame and cooldown between nudges.
ZOOM_DELTA_THRESHOLD = 0.04
ZOOM_COOLDOWN_FRAMES = 8

# Rejecting false hands ("воспринимает любой объект, даже голову"):
# MediaPipe's own thresholds are raised, and every detection is then
# sanity-checked — its Left/Right classification must be confident, and its
# bounding box must be a plausible hand size (not a face-sized blob).
HAND_DETECTION_CONFIDENCE = 0.75
HAND_PRESENCE_CONFIDENCE = 0.7
HAND_TRACKING_CONFIDENCE = 0.65
HAND_MIN_HANDEDNESS_SCORE = 0.75
HAND_BBOX_MIN = 0.04  # fraction of the frame — smaller = noise
HAND_BBOX_MAX = 0.55  # larger = a face / torso, not a hand
# A hand must be seen this many consecutive frames before it drives the
# cursor, so a one-frame false blip can't jerk the pointer.
HAND_WARMUP_FRAMES = 3

# MediaPipe Tasks HandLandmarker model — fetched once on first use into
# data/models/, same pattern as the Silero TTS weights.
MODELS_DIR = DATA_DIR / "models"
HAND_LANDMARKER_TASK_PATH = MODELS_DIR / "hand_landmarker.task"
HAND_LANDMARKER_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
