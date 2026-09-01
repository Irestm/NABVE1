from __future__ import annotations

import os

from core.config import DATA_DIR

# Set NABVE_GESTURE_DEBUG=1 to log raw MediaPipe landmarks every frame plus
# a periodic processing-FPS line — the diagnostic pass for "распознавание
# работает плохо". Off by default (per-frame logging is noisy).
GESTURE_DEBUG = os.environ.get("NABVE_GESTURE_DEBUG", "").strip() not in ("", "0", "false", "no")

# The periodic (every ~2s) diagnostic INFO line: camera-reader fps, duplicate-
# frame fraction, per-gate rejection counts, cursor jump-per-tick and
# fist/open-palm score ranges. On by default — this is the "почему жесты
# работают плохо" instrumentation; set NABVE_GESTURE_DIAG=0 to silence it
# once the numbers are understood.
GESTURE_DIAG = os.environ.get("NABVE_GESTURE_DIAG", "1").strip() not in ("0", "false", "no")

# Try the MediaPipe GPU delegate for inference first (RTX 4050), fall back to
# CPU/XNNPACK if the wheel/driver can't provide it — the worker logs which
# one it ended up on.
GESTURE_TRY_GPU = os.environ.get("NABVE_GESTURE_GPU", "1").strip() not in ("0", "false", "no")

# MediaPipe HandLandmarker running mode. "video" (default) carries the
# previous frame forward as a tracking prior — smoother, but it can coast on
# a wrong pose once it locks onto one. "image" treats every frame fully
# independently (no prior), our own One-Euro does the smoothing.
GESTURE_MP_MODE = os.environ.get("NABVE_GESTURE_MP_MODE", "video").strip().lower()

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

# Click = three INDEPENDENT signals OR'd together (any one down = button
# down). Each is catch-fast / release-slow with its own median + debounce,
# plus a tap timeout and a hard max-hold so the OS button can never stick.
#
# 1. HULL (primary) — gesture_recognizer.hull_compactness: convex-hull area
#    of all 21 landmarks over hand_size^2. Uses every point, so one bad
#    fingertip is averaged out — steadier than a 2-point distance. A fist or
#    pinch collapses the hull; an open/pointing hand does not. Thresholds
#    are first guesses, the diagnostics log the per-user range.
HULL_ENGAGE = 0.16
HULL_RELEASE = 0.28
HULL_SCORE_MAX = 5.0

# 2. PINCH — gesture_recognizer.pinch2_gap: thumb-tip to index-tip distance,
#    hand-size normalised. Measured for this user: pinch 0.03-0.15, open
#    0.7-2.5. Clamped first (a degenerate set once sent it to ~4.9).
PINCH_ENGAGE = 0.28
PINCH_RELEASE = 0.55
PINCH_SCORE_MAX = 3.0

# 3. FIST (fallback) — only a DEEP, unambiguous fist, so it can't false-fire
#    on this user's low-reading open hand. Clamp the raw ratio first.
DEFAULT_FIST_RATIO = 0.85        # calibration / swipe still use this
FIST_FALLBACK_RATIO = 0.72       # fallback click engage — deep only
FIST_RELEASE_GAP = 0.17
FIST_SCORE_MIN = 0.3
FIST_SCORE_MAX = 3.0

# A click is a TAP by default: after CLICK_TAP_SECONDS held it auto-releases
# unless a signal is still actively squeezed (a drag). The absolute release
# bars sit inside this user's relaxed-hand noise, so without this clicks
# stayed stuck for seconds.
CLICK_TAP_SECONDS = 0.7

# Shared smoothing + debounce for both click state machines.
CLICK_MEDIAN_WINDOW = 3
CLICK_ENGAGE_FRAMES = 2
CLICK_RELEASE_FRAMES = 2
CLICK_MAX_HOLD_SECONDS = 4.0
DEFAULT_TRACKING_ZONE = 0.70  # central fraction of the camera frame that maps to the whole screen

# --- What the cursor follows ---------------------------------------------
# "index" (default, per user request): the index fingertip — natural to aim
# with. A pre-click freeze (see PRECLICK_* below) locks the cursor delta the
# instant a click signal starts closing, so the arc the tip sweeps into a
# fist / pinch doesn't drag the pointer off target. "palm": the wrist <->
# middle-knuckle midpoint (the hand's rigid base, unaffected by finger curl)
# — steadier but not where the user wants to point.
GESTURE_TRACK_POINT = os.environ.get("NABVE_GESTURE_TRACK_POINT", "index").strip().lower()

# Pre-click freeze: when the smoothed hull / pinch / fist signal drops by
# more than PRECLICK_DELTA between frames (i.e. the hand is closing), the
# cursor delta is frozen for PRECLICK_FREEZE_FRAMES ticks so the fingertip's
# closing arc can't move the pointer. Directional (only a drop, = closing)
# and sized well above normal jitter, so plain aiming never trips it.
PRECLICK_DELTA = 0.06
PRECLICK_FREEZE_FRAMES = 5

# --- Cursor mode -----------------------------------------------------------
# "relative" (default): the cursor moves by the hand's frame-to-frame delta,
# mouse-style — so you reach any screen edge without your arm ending up in a
# bad spot, and you lift/recenter via the clutch. "absolute": the old
# hand-position -> screen-position mapping (kept as a fallback).
GESTURE_CURSOR_MODE = os.environ.get("NABVE_GESTURE_CURSOR_MODE", "relative").strip().lower()

# Relative-mode gain, base pixels per 1.0 of normalised hand travel.
# Override live with NABVE_GESTURE_REL_GAIN. Higher amplified landmark
# jitter more than it helped, so 3000.
try:
    REL_GAIN_PX = float(os.environ.get("NABVE_GESTURE_REL_GAIN", "3000") or "3000")
except ValueError:
    REL_GAIN_PX = 3000.0
# Speed-shaped gain (the cursor never force-stops — a dwell freeze locked it
# mid-aim; this replaces it). Below REL_SPEED_REF the effective gain scales
# from REL_PRECISION_GAIN (slow, careful aiming = fine steps) up to 1.0;
# above it a flick term multiplies further so a fast sweep crosses a wide
# multi-monitor desktop in one motion (was too weak — the per-tick clamp
# alone throttled fast sweeps to a crawl on a 3840-wide desktop).
REL_PRECISION_GAIN = 0.35
REL_SPEED_REF = 0.5          # hand speed (norm/s) = "moving normally"
REL_ACCEL = 4.0

# Clutch: while the filtered hand point is OUTSIDE this centred frame box
# the cursor is frozen but the hand keeps tracking, so you can drop /
# recenter your arm and carry on from the same cursor spot. Kept close to
# the frame edge — the old (0.12, 0.88) box was so tight that just reaching
# toward the far monitor froze the cursor.
CLUTCH_BOX = (0.03, 0.97, 0.03, 0.97)  # x0, x1, y0, y1 in frame coords

# A landmark set that blew up (a fingertip/wrist point flew off, distances
# exploded, every derived signal spiked to its clamp) is rejected as a
# frame: a real hand can't be this small, and no landmark sits this far
# outside the frame.
HAND_MIN_SCALE = 0.04        # wrist -> middle-knuckle distance, normalised
LANDMARK_BOUND = 1.15        # |coord| beyond this (0/1 +/- 0.15) = blowup

# Per-user rigid-bone fit (bone_fit.py). The first BONE_SCAN_FRAMES frames
# with a hand present are used to learn this hand's bone lengths (median);
# after that every frame's raw 21 points are snapped so each bone matches
# its learned length along the raw direction — a fingertip that jumps can no
# longer stretch its segment 3x, so the derived click signals stay stable.
BONE_SCAN_FRAMES = 90
BONE_FIT_BLEND = 0.85  # how far to pull raw toward the rigid fit (1 = fully rigid)
BONE_FIT_ENABLED = os.environ.get("NABVE_GESTURE_BONE_FIT", "1").strip() not in ("0", "false", "no")

# MediaPipe num_hands. 1 by default — a second (often phantom) hand was a
# source of primary-hand flips and blowups; two-hand zoom needs 2, set
# NABVE_GESTURE_NUM_HANDS=2 for it.
try:
    HAND_NUM_HANDS = int(os.environ.get("NABVE_GESTURE_NUM_HANDS", "1") or "1")
except ValueError:
    HAND_NUM_HANDS = 1
HAND_NUM_HANDS = max(1, min(2, HAND_NUM_HANDS))

# Ignore final on-screen cursor moves smaller than this — kills the last of
# the landmark shimmer so a resting hand doesn't twitch the pointer. This is
# the fallback; "калибровка дрожания" measures the user's own tremor and
# stores a personal value under GESTURE_DEADZONE_PX_KEY.
CURSOR_DEADZONE_PX = 8
DEADZONE_PX_MIN = 2
DEADZONE_PX_MAX = 40

# Hard cap on cursor travel in one worker tick: the smaller of
# MAX_CURSOR_STEP_FRAC * min(screen_w, screen_h) and MAX_CURSOR_STEP_PX.
# Only there to stop a single glitched frame flinging the pointer across the
# display; a real fast sweep must still be able to cross a wide desktop in a
# few ticks, so the cap is generous now (the old 324 px throttled every
# sweep on a 3840-wide desktop to a crawl).
MAX_CURSOR_STEP_FRAC = 0.9
MAX_CURSOR_STEP_PX = 1400

# Mapping "sensitivity": the personal / default tracking rectangle is
# scaled about its centre by 1 / sensitivity, so <1 widens it (gentler,
# needs a bigger hand move per screen distance) and >1 narrows it
# (twitchier). Default 1.0 — the palm centre sweeps a smaller arc than a
# fingertip, so it needs more gain than the fingertip did to feel 1:1.
# Tune live with NABVE_GESTURE_SENSITIVITY (lower = slower / bigger move).
try:
    CURSOR_SENSITIVITY = float(os.environ.get("NABVE_GESTURE_SENSITIVITY", "0.45") or "0.45")
except ValueError:
    CURSOR_SENSITIVITY = 0.45
if CURSOR_SENSITIVITY <= 0:
    CURSOR_SENSITIVITY = 0.45

# Fixed cursor magnification while gesture mode is on — a locked constant,
# not a setting. Was 2x, dialled back to 1.5 ("меньше ещё курсор сделай").
CURSOR_SCALE = 1.5

# Worker tick rate — a bit above the camera fps so the One-Euro filter takes
# extra sub-steps toward the last known point and the cursor glides smoothly
# between (often sparse) camera frames. Not too high: a faster tick just
# starves the camera-reader thread of the GIL and lowers real fps.
PROCESSING_FPS = 30
CAMERA_INDEX = 0
# 1280x720 MJPG. The webcam is exposure/lighting-bound, not resolution-bound
# (same fps at 480p and 720p once the shutter is fixed manually), so 720p is
# taken now for the extra pixels on the hand at arm's length — sharper
# fingertip landmarks, which the pinch signal depends on. A dedicated reader
# thread keeps the newest frame so MediaPipe never blocks on the camera.
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
CAMERA_FOURCC = "MJPG"

# Auto-exposure is the single biggest cause of "жесты работают плохо":
# measured, this webcam's UVC auto-exposure ran the shutter out to 250 ms in
# room light and capped delivery at 3-4 fps, so the cursor was driven by a
# 4 fps hand position. The reader starts on auto (fine in bright light) and,
# only if delivered fps stays under CAMERA_MIN_ACCEPTABLE_FPS for
# CAMERA_ADAPT_BAD_WINDOWS checks, steps the shutter down through
# CAMERA_EXPOSURE_STEPS (V4L2 "exposure_absolute", 100 µs units) with
# CAP_PROP_AUTO_EXPOSURE=1 (manual) and lifts CAP_PROP_BRIGHTNESS so the
# darker short-exposure frame stays usable. This adaptive ramp only runs
# when exposure starts on "auto" (see CAMERA_FORCE_EXPOSURE below); set
# NABVE_GESTURE_ADAPTIVE_EXPOSURE=0 to disable it there too.
CAMERA_ADAPTIVE_EXPOSURE = (
    os.environ.get("NABVE_GESTURE_ADAPTIVE_EXPOSURE", "1").strip() not in ("0", "false", "no")
)
CAMERA_MIN_ACCEPTABLE_FPS = 15.0
CAMERA_EXPOSURE_STEPS = (400, 300, 200, 120)
CAMERA_MANUAL_BRIGHTNESS = 200
CAMERA_ADAPT_CHECK_SECONDS = 2.0
CAMERA_ADAPT_BAD_WINDOWS = 2
# A short manual shutter is the DEFAULT: measured, the webcam's auto
# exposure ran the shutter long enough in room light to both cap fps at
# 3-4 and motion-blur a moving hand so MediaPipe lost it — a fixed ~320
# (100 µs units) keeps ~25 fps and a sharp hand. NABVE_GESTURE_EXPOSURE=<n>
# overrides the value; NABVE_GESTURE_EXPOSURE=auto (or off / 0) starts on
# the camera's auto exposure and lets the adaptive ramp above take over.
_forced_exp = os.environ.get("NABVE_GESTURE_EXPOSURE", "").strip().lower()
if _forced_exp in ("auto", "off", "0", "no", "false"):
    CAMERA_FORCE_EXPOSURE: int | None = None
elif _forced_exp:
    try:
        CAMERA_FORCE_EXPOSURE = int(_forced_exp)
    except ValueError:
        CAMERA_FORCE_EXPOSURE = 320
else:
    CAMERA_FORCE_EXPOSURE = 320

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

# A held click survives this many hand-less frames before it is released —
# MediaPipe drops the hand for a frame or two constantly.
FIST_LOST_GRACE_FRAMES = 3
# Freeze the cursor for this many ticks the instant a click engages, so the
# press lands exactly where it was aimed.
CLICK_FREEZE_FRAMES = 3

# MediaPipe drops the hand for a frame or two constantly (worse on a moving,
# motion-blurred hand). On such a gap the worker keeps driving the cursor
# toward the last known point and keeps the One-Euro history for this many
# ticks instead of resetting it — a reset made the filter return the raw
# point verbatim on re-acquire, which is what threw the cursor hundreds of
# px across the screen (seen in the diagnostics). Only a longer gap does the
# full state reset.
HAND_LOST_COAST_FRAMES = 12

# The physical mouse always wins: the instant the real cursor moves by
# more than this (px) from where the worker last put it, gesture control
# yields for this many seconds (refreshed on every further physical move).
# The worker now re-anchors its reference every tick (including ticks it
# doesn't move the cursor), so this only trips on motion from something
# else — 18 px is a comfortable margin over pointer rounding.
PHYSICAL_MOUSE_THRESHOLD_PX = 18
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
# The handedness-score gate that used to sit here was dropped: diagnostics
# showed it discarding ~5% of otherwise-good frames, and "is this a left or
# right hand" is irrelevant to cursor control — the geometry check below
# rejected nothing real over a full session, so it carries the false-hand
# duty alone.
HAND_DETECTION_CONFIDENCE = 0.6
HAND_PRESENCE_CONFIDENCE = 0.6
HAND_TRACKING_CONFIDENCE = 0.55
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
