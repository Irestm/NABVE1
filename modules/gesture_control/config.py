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
GESTURE_FIST_THRESHOLD_KEY = "gesture_fist_threshold"
GESTURE_DEADZONE_PX_KEY = "gesture_deadzone_px"
GESTURE_MIN_CUTOFF_KEY = "gesture_min_cutoff"
GESTURE_OPEN_PALM_RATIO_KEY = "gesture_open_palm_ratio"
GESTURE_SWIPE_MIN_DX_KEY = "gesture_swipe_min_dx"
GESTURE_TRACKING_ZONE_KEY = "gesture_tracking_zone"
# Personal tracking rectangle in normalized frame coords "x0,x1,y0,y1",
# from the "обведите углы экрана" calibration phase. Overrides the symmetric
# DEFAULT_TRACKING_ZONE when present.
GESTURE_ZONE_KEY = "gesture_zone_bounds"

# Fist = click/drag. gesture_recognizer.fist_score is the largest of the
# four finger tip/PIP ratios (scale-invariant) — a tight fist is ~0.8 or
# below, a relaxed/pointing hand ~1.4+. fist_score <= threshold means
# "closed". Calibration personalises it; this default works without.
DEFAULT_FIST_RATIO = 1.0
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

# Worker tick rate — a bit above the camera fps so the One-Euro filter takes
# extra sub-steps toward the last known point and the cursor glides smoothly
# between (often sparse) camera frames. Not too high: a faster tick just
# starves the camera-reader thread of the GIL and lowers real fps.
PROCESSING_FPS = 30
CAMERA_INDEX = 0
# 640x480 MJPG. Measured: this webcam delivers the same fps at 720p and
# 480p (it's exposure/lighting-bound, not resolution-bound), so the smaller
# frame is chosen for cheaper decode/copy per frame. A dedicated reader
# thread keeps the newest frame so MediaPipe never blocks on the camera;
# the worker logs resolution, fps and mean brightness — a dark/slow feed is
# the usual reason tracking "работает плохо".
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_FOURCC = "MJPG"

# Cursor smoothing: a genuine 1€ (One-Euro) filter on the tracked point,
# fed by a median-of-3 prefilter that drops single-frame spikes. ONE_EURO_
# MIN_CUTOFF is the low-pass cutoff (Hz) when the hand is still — lower =
# steadier, more lag; ONE_EURO_BETA raises the cutoff with hand speed so a
# deliberate move barely lags. The correct MediaPipe timestamp (fixed) is
# what makes a real 1€ filter possible now.
ONE_EURO_MIN_CUTOFF = 0.9
ONE_EURO_BETA = 1.6
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

# Calibration refuses to store a threshold learned from a bad feed: a frame
# darker than this (mean 0-255) can't be trusted, and if more than
# CALIBRATION_MAX_DARK_FRACTION of a phase's frames are dark the wizard
# aborts instead of persisting garbage (a dark session once wrote the
# deadzone/pinch clamps to their extremes and broke everything).
CALIBRATION_MIN_BRIGHTNESS = 45.0
CALIBRATION_MAX_DARK_FRACTION = 0.4

# If the reader had frames flowing and then gets nothing for this long (a
# real driver stall, e.g. an abrupt lighting change forcing an exposure
# renegotiation), it reopens the camera rather than wedging the cursor.
# Generous so a merely slow (a few fps) feed is never mistaken for a stall.
CAMERA_STALL_REOPEN_SECONDS = 8.0

# Corner-tracing phase: sweep the hand around the four screen corners for
# this many frames; the min/max x/y (padded inward) become the personal
# tracking rectangle. Guardrail: each axis span must be at least this wide.
CORNER_CALIBRATION_SAMPLES = 90
CORNER_ZONE_PAD = 0.04
CORNER_ZONE_MIN_SPAN = 0.18

# Fist = click / drag. "Catch fast, release slow": engage when the *best*
# (min) of the last FIST_RATIO_MEDIAN raw scores dips under the threshold
# for FIST_ENGAGE_DEBOUNCE_FRAMES frames; release only when the *median*
# climbs past FIST_RELEASE_MULT x threshold and holds for
# FIST_RELEASE_DEBOUNCE_FRAMES. If MediaPipe drops the hand for a frame or
# two, FIST_LOST_GRACE_FRAMES keeps the click held through the gap.
FIST_RATIO_MEDIAN = 3
FIST_RELEASE_MULT = 1.4
FIST_ENGAGE_DEBOUNCE_FRAMES = 2
FIST_RELEASE_DEBOUNCE_FRAMES = 3
FIST_LOST_GRACE_FRAMES = 4

# Precision hover: the cursor eases toward the mapped hand position with a
# gain that scales with hand speed. Fast hand -> gain 1.0 (1:1, cross the
# screen). Nearly still hand -> PRECISION_GAIN_MIN, so tremor barely nudges
# the pointer and small targets ("маленький крестик") are reachable.
PRECISION_SPEED_LOW = 0.006   # norm units/frame at/below which gain = PRECISION_GAIN_MIN
PRECISION_SPEED_HIGH = 0.055  # norm units/frame at/above which gain = 1.0
PRECISION_GAIN_MIN = 0.35

# Dwell freeze: once the cursor has stayed within DWELL_RADIUS_PX for
# DWELL_FRAMES it locks in place (ignores sub-DWELL_BREAK_PX hand motion)
# until the hand moves clearly away or a fist happens — so a hovered small
# target stays under the pointer while you close your hand to click it.
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
