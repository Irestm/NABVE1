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
DEFAULT_PINCH_RATIO = 0.5
DEFAULT_TRACKING_ZONE = 0.70  # central fraction of the camera frame that maps to the whole screen

# Ignore final on-screen cursor moves smaller than this — kills the last of
# the landmark shimmer so a resting hand doesn't twitch the pointer. This is
# the fallback; "калибровка дрожания" measures the user's own tremor and
# stores a personal value under GESTURE_DEADZONE_PX_KEY.
CURSOR_DEADZONE_PX = 5
DEADZONE_PX_MIN = 2
DEADZONE_PX_MAX = 40

# Fixed cursor magnification while gesture mode is on — a locked constant,
# not a setting. Was 2x, dialled back to 1.5 ("меньше ещё курсор сделай").
CURSOR_SCALE = 1.5

# Processing rate — enough for a responsive cursor without pinning a core.
PROCESSING_FPS = 24
CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# Adaptive (one-euro-style) smoothing: alpha rises with hand speed, so a
# fast move barely lags while a still hand is heavily smoothed. A median-of-3
# prefilter (_AdaptiveSmoother) drops single-frame spikes before this runs.
# EMA_MIN_ALPHA is the fallback resting blend; "калибровка дрожания" replaces
# it with a personal value between MIN_ALPHA_FLOOR (heavy tremor) and
# MIN_ALPHA_CEIL (steady hand), stored under GESTURE_MIN_ALPHA_KEY. Values
# kept deliberately low — repeated request for "меньше трясётся".
EMA_MIN_ALPHA = 0.045
EMA_MAX_ALPHA = 0.90
EMA_SPEED_FULL = 0.07  # normalized units/frame at which smoothing is fully "off"
MIN_ALPHA_FLOOR = 0.025
MIN_ALPHA_CEIL = 0.10

# "Калибровка дрожания": hold the hand still for this many frames, measure
# the RMS tremor of the fingertip, and map it (in screen px) across this
# band to a personal deadzone + resting alpha.
STEADY_CALIBRATION_SAMPLES = 45
JITTER_LOW_PX = 1.5
JITTER_HIGH_PX = 9.0

# Pinch = click. The pinch ratio is median-filtered over PINCH_RATIO_MEDIAN
# frames first (landmark noise made a raw ratio flicker past the debounce and
# never engage — "щипок вообще не работает"). Engage is near-instant;
# release is debounced and uses hysteresis (ratio must climb to
# PINCH_RELEASE_MULT x the threshold) so a drag never drops on one bad frame.
PINCH_RATIO_MEDIAN = 3
PINCH_RELEASE_MULT = 1.6
PINCH_ENGAGE_DEBOUNCE_FRAMES = 1
PINCH_RELEASE_DEBOUNCE_FRAMES = 3

# Precision hover: the cursor eases toward the mapped hand position with a
# gain that scales with hand speed. Fast hand -> gain 1.0 (1:1, cross the
# screen). Nearly still hand -> PRECISION_GAIN_MIN, so tremor barely nudges
# the pointer and small targets ("маленький крестик") are reachable.
PRECISION_SPEED_LOW = 0.006   # norm units/frame at/below which gain = PRECISION_GAIN_MIN
PRECISION_SPEED_HIGH = 0.055  # norm units/frame at/above which gain = 1.0
PRECISION_GAIN_MIN = 0.35

# Dwell freeze: once the cursor has stayed within DWELL_RADIUS_PX for
# DWELL_FRAMES it locks in place (ignores sub-DWELL_BREAK_PX hand motion)
# until the hand moves clearly away or a pinch happens — so a hovered small
# target stays under the pointer while you pinch to click it.
DWELL_RADIUS_PX = 14
DWELL_FRAMES = 7
DWELL_BREAK_PX = 45

# The physical mouse always wins: the instant the real cursor moves by
# more than this (px) from where the worker last put it, gesture control
# yields for this many seconds (refreshed on every further physical move).
PHYSICAL_MOUSE_THRESHOLD_PX = 14
PHYSICAL_MOUSE_OVERRIDE_SECONDS = 1.2

# Two-hand zoom: minimum spread change per frame and cooldown between nudges.
ZOOM_DELTA_THRESHOLD = 0.04
ZOOM_COOLDOWN_FRAMES = 8

# Open-palm horizontal swipe = switch windows (Alt+Tab / Alt+Shift+Tab).
# A whole open palm (gesture_recognizer.is_open_palm — 3+ fingers extended,
# not pinching) held for SWIPE_OPEN_STREAK_FRAMES puts the worker in "swipe
# mode": the cursor is frozen and only a horizontal palm-centre travel of at
# least SWIPE_MIN_DX across SWIPE_HISTORY_FRAMES (mostly horizontal) fires a
# switch. A pointing hand never enters this mode, so it can't swipe by
# accident. Cooldown blocks everything briefly after a switch.
SWIPE_HISTORY_FRAMES = 5
SWIPE_MIN_DX = 0.26
SWIPE_MAX_DY_RATIO = 0.55
SWIPE_OPEN_STREAK_FRAMES = 3
SWIPE_COOLDOWN_FRAMES = 12

# Rejecting false hands ("воспринимает любой объект, даже голову") WITHOUT
# starving real recognition (over-tight thresholds broke tracking): keep
# MediaPipe near its own defaults, then sanity-check the *geometry* — the
# four knuckles (5, 9, 13, 17) must sit at a consistent radius from the
# wrist, which a scattered face/torso blob fails but a real hand at any
# angle passes.
HAND_DETECTION_CONFIDENCE = 0.5
HAND_PRESENCE_CONFIDENCE = 0.5
HAND_TRACKING_CONFIDENCE = 0.5
HAND_MIN_HANDEDNESS_SCORE = 0.55
HAND_BBOX_MIN = 0.03  # fraction of the frame — smaller = noise
HAND_BBOX_MAX = 0.85  # larger = fills the frame, not a hand held up to the camera
HAND_KNUCKLE_RADIUS_TOLERANCE = 2.4  # max ratio of any wrist->knuckle distance to their mean
# A hand must be seen this many consecutive frames before it drives the
# cursor, so a one-frame false blip can't jerk the pointer. hand_seen_streak
# decays by 1 on a missed frame rather than resetting, so a brief tracking
# gap doesn't restart the warmup.
HAND_WARMUP_FRAMES = 2

# MediaPipe Tasks HandLandmarker model — fetched once on first use into
# data/models/, same pattern as the Silero TTS weights.
MODELS_DIR = DATA_DIR / "models"
HAND_LANDMARKER_TASK_PATH = MODELS_DIR / "hand_landmarker.task"
HAND_LANDMARKER_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
