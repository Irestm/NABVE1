from __future__ import annotations

import os

from core.config import DATA_DIR

# Set NABVE_GESTURE_DEBUG=1 to log raw MediaPipe landmarks every frame plus
# a periodic processing-FPS line — the diagnostic pass for "распознавание
# работает плохо". Off by default (per-frame logging is noisy).
GESTURE_DEBUG = os.environ.get("NABVE_GESTURE_DEBUG", "").strip() not in ("", "0", "false", "no")

# Try the MediaPipe GPU delegate for inference first (RTX 4050), fall back to
# CPU/XNNPACK if the wheel/driver can't provide it — the worker logs which
# one it ended up on.
GESTURE_TRY_GPU = os.environ.get("NABVE_GESTURE_GPU", "1").strip() not in ("0", "false", "no")

# Per-user profile facts written by the calibration wizard
# (calibration.CalibrationSession): one phase per gesture, each done 3x, each
# deriving its own threshold. The tracking-zone override is optional and set
# by hand, not calibrated.
GESTURE_PINCH_THRESHOLD_KEY = "gesture_pinch_threshold"
GESTURE_DEADZONE_PX_KEY = "gesture_deadzone_px"
GESTURE_MIN_CUTOFF_KEY = "gesture_min_cutoff"
GESTURE_OPEN_PALM_RATIO_KEY = "gesture_open_palm_ratio"
GESTURE_SWIPE_MIN_DX_KEY = "gesture_swipe_min_dx"
GESTURE_TRACKING_ZONE_KEY = "gesture_tracking_zone"
# Personal tracking rectangle in normalized frame coords "x0,x1,y0,y1",
# from the "обведите углы экрана" calibration phase. Overrides the symmetric
# DEFAULT_TRACKING_ZONE when present.
GESTURE_ZONE_KEY = "gesture_zone_bounds"

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
# 720p capture: MediaPipe downsamples internally, but a higher-res source
# keeps finger detail crisper when the hand is small / far from the camera.
# The worker logs the resolution the driver actually granted.
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30

# Cursor smoothing: a genuine 1€ (One-Euro) filter on the tracked point,
# fed by a median-of-3 prefilter that drops single-frame spikes. ONE_EURO_
# MIN_CUTOFF is the low-pass cutoff (Hz) when the hand is still — lower =
# steadier, more lag; ONE_EURO_BETA raises the cutoff with hand speed so a
# deliberate move barely lags. The correct MediaPipe timestamp (fixed) is
# what makes a real 1€ filter possible now.
ONE_EURO_MIN_CUTOFF = 1.2
ONE_EURO_BETA = 2.5
ONE_EURO_D_CUTOFF = 1.0

# "Калибровка дрожания" personalises the resting cutoff: it measures the
# fingertip tremor (px) and maps it across [JITTER_LOW_PX, JITTER_HIGH_PX]
# to a min-cutoff between MIN_CUTOFF_CEIL (steady hand, lighter) and
# MIN_CUTOFF_FLOOR (shaky hand, heavier), stored under GESTURE_MIN_CUTOFF_KEY.
MIN_CUTOFF_FLOOR = 0.45
MIN_CUTOFF_CEIL = 1.6

# "Калибровка дрожания": hold the hand still for this many frames, measure
# the RMS tremor of the fingertip, and map it (in screen px) across this
# band to a personal deadzone + resting cutoff.
STEADY_CALIBRATION_SAMPLES = 60
JITTER_LOW_PX = 1.5
JITTER_HIGH_PX = 9.0

# Corner-tracing phase: sweep the hand around the four screen corners for
# this many frames; the min/max x/y (padded inward) become the personal
# tracking rectangle. Guardrail: each axis span must be at least this wide.
CORNER_CALIBRATION_SAMPLES = 90
CORNER_ZONE_PAD = 0.04
CORNER_ZONE_MIN_SPAN = 0.18

# Pinch = click. "Catch fast, release slow": engage when the *best* (min) of
# the last PINCH_RATIO_MEDIAN raw ratios dips under the threshold for
# PINCH_ENGAGE_DEBOUNCE_FRAMES frames; release only when the *median* climbs
# past PINCH_RELEASE_MULT x threshold and holds for PINCH_RELEASE_DEBOUNCE_
# FRAMES. And when the thumb and index tips touch, MediaPipe often loses the
# whole hand for a frame or two — PINCH_LOST_GRACE_FRAMES keeps the click
# held through that gap instead of dropping it ("щипок на раз пятый").
PINCH_RATIO_MEDIAN = 3
PINCH_RELEASE_MULT = 1.6
PINCH_ENGAGE_DEBOUNCE_FRAMES = 2
PINCH_RELEASE_DEBOUNCE_FRAMES = 3
PINCH_LOST_GRACE_FRAMES = 4

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
# A whole open palm (gesture_recognizer.is_open_palm) held for
# SWIPE_OPEN_STREAK_FRAMES puts the worker in "swipe mode": the cursor is
# frozen and only a horizontal palm-centre travel of at least the swipe
# distance across SWIPE_HISTORY_FRAMES (mostly horizontal) fires a switch. A
# pointing hand never enters this mode. SWIPE_MIN_DX is the fallback travel;
# the wizard measures the user's actual swing (theirs was shorter than this,
# which is why "ладонь так и не сработала") into GESTURE_SWIPE_MIN_DX_KEY.
SWIPE_HISTORY_FRAMES = 5
SWIPE_MIN_DX = 0.20
SWIPE_MIN_DX_FLOOR = 0.10
SWIPE_MIN_DX_CEIL = 0.40
SWIPE_MAX_DY_RATIO = 0.6
SWIPE_OPEN_STREAK_FRAMES = 3
SWIPE_COOLDOWN_FRAMES = 12

# Open-palm detection: is_open_palm compares each non-thumb fingertip's
# distance-from-wrist to that finger's PIP joint's; open_palm_score is the
# 3rd-largest of those ratios ("at least 3 fingers this extended"). The
# fallback threshold; the wizard stores a personal one in
# GESTURE_OPEN_PALM_RATIO_KEY between these bounds.
DEFAULT_OPEN_PALM_RATIO = 1.12
OPEN_PALM_RATIO_MIN = 1.04
OPEN_PALM_RATIO_MAX = 1.7

# Rejecting false hands ("воспринимает любой объект, даже голову") WITHOUT
# starving real recognition (over-tight thresholds broke tracking): keep
# MediaPipe near its own defaults, then sanity-check the *geometry* — the
# four knuckles (5, 9, 13, 17) must sit at a consistent radius from the
# wrist, which a scattered face/torso blob fails but a real hand at any
# angle passes.
# Raised back up now that One-Euro + the geometry check absorb the extra
# rejections: a low-confidence landmark set reads as "дёрганье", so it's
# better to drop it and let the filter coast than to steer the cursor with it.
HAND_DETECTION_CONFIDENCE = 0.6
HAND_PRESENCE_CONFIDENCE = 0.6
HAND_TRACKING_CONFIDENCE = 0.55
HAND_MIN_HANDEDNESS_SCORE = 0.6
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
