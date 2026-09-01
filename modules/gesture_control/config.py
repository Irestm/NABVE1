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

# Try the MediaPipe GPU delegate for inference (RTX 4050), else CPU/XNNPACK.
# OFF by default: on some Linux GL/driver stacks the MediaPipe Tasks GPU
# path doesn't raise a catchable error, it aborts the whole process — and
# CPU/XNNPACK on the float16 model at this resolution is already ~15-30 ms.
# Set NABVE_GESTURE_GPU=1 to try it once you've confirmed it's stable here.
GESTURE_TRY_GPU = os.environ.get("NABVE_GESTURE_GPU", "0").strip() in ("1", "true", "yes")

# MediaPipe HandLandmarker running mode. "video" (default) carries the
# previous frame forward as a tracking prior — smoother, but it can coast on
# a wrong pose once it locks onto one. "image" treats every frame fully
# independently (no prior), our own One-Euro does the smoothing.
GESTURE_MP_MODE = os.environ.get("NABVE_GESTURE_MP_MODE", "video").strip().lower()

# --- Model ----------------------------------------------------------------
# Archand-style: ABSOLUTE mapping (a frame box -> the whole screen) + a
# discrete FINGER-STATE click, on top of our infra (One-Euro, camera
# reader, robustness, calibration).
#   * Cursor follows the index fingertip, but ONLY while the hand is in the
#     "pointing" pose (index + middle both extended). Any other pose (fist,
#     one finger, open palm, hand dropped) => the cursor holds still — that
#     IS the clutch: make a fist / drop your hand to reposition your arm.
#   * Left click / drag = from the pointing pose, bring the index and middle
#     FINGERTIPS together (index_middle_gap small). Both tips are always
#     visible (they don't occlude like thumb-index), so MediaPipe reads this
#     far more reliably than the old pinch. A full fist also clicks.
#   * Right click = from the pointing pose, fold ONLY the ring finger
#     ("peace sign, tuck the ring"). Fire-once.
#
# Per-user calibration facts (STEADY -> CORNERS -> CLICK), all applied.
GESTURE_MIN_CUTOFF_KEY = "gesture_min_cutoff"
GESTURE_DEADZONE_PX_KEY = "gesture_deadzone_px"
GESTURE_ZONE_KEY = "gesture_zone_bounds"          # the absolute mapping rectangle
GESTURE_CLICK_GAP_ENG_KEY = "gesture_click_gap_engage"
GESTURE_CLICK_GAP_REL_KEY = "gesture_click_gap_release"

# HULL (gesture_recognizer.hull_compactness) is an extra OFF-by-default
# click signal. NABVE_GESTURE_CLICK_HULL=1 re-enables it.
CLICK_USE_HULL = os.environ.get("NABVE_GESTURE_CLICK_HULL", "").strip() in ("1", "true", "yes")
HULL_ENGAGE = 0.16
HULL_RELEASE = 0.28
HULL_SCORE_MAX = 5.0

# "Pointing" pose gate: index AND middle finger STRAIGHTNESS (chord/path
# along the joints — depth-robust, unlike a 2D ratio) must exceed this for
# the cursor to be driven / a left click to fire. Below it the hand isn't
# pointing -> cursor holds (= the clutch).
MOVE_FINGER_RATIO = 0.82
# Pose-based modes (borrowed from the AI-Virtual-Mouse tutorial): the MIDDLE
# finger is the mode switch. Index up + middle CURLED (straightness below
# this) = MOVE (cursor follows the index tip). Index up + middle STRAIGHT
# (above MOVE_FINGER_RATIO) = CLICK-ARM (cursor frozen, pinch index<->middle
# tips to click). The band between the two = hold, so a half-raised middle
# finger doesn't thrash between modes.
MIDDLE_DOWN_MAX = 0.60

# LEFT CLICK — curl ALL FOUR fingers (index..pinky) into a fist, thumb
# NOT sticking out (thumb out = the 👍 right click). The signal is
# `fist_med` = MEDIAN finger straightness (chord/path): open hand ~0.9+,
# a real fist ~0.30-0.45. Catch below ENGAGE, release above RELEASE
# (hysteresis). Chosen over the old index<->middle "tips together" gap:
# MediaPipe holds a closing fist in view where it loses two tips meeting.
# The CLICK calibration phase personalises ENGAGE/RELEASE.
FIST_CLICK_ENGAGE = 0.60
FIST_CLICK_RELEASE = 0.75
FIST_CLICK_ENG_MIN, FIST_CLICK_ENG_MAX = 0.35, 0.72
FIST_CLICK_REL_MAX = 0.88
# index_middle_gap is still computed (diag + the old calibration math
# fallback); clamp a degenerate frame.
CLICK_GAP_MAX = 3.0

# For the RIGHT-CLICK thumbs-up test only: how curled the least-curled
# finger must be (max of the 4 straightness values) for the hand to count
# as "a fist".
FIST_FALLBACK_RATIO = 0.55
FIST_RELEASE_GAP = 0.14
FIST_SCORE_MIN = 0.20
FIST_SCORE_MAX = 1.15
DEFAULT_FIST_RATIO = 0.75

# RIGHT CLICK — thumbs-up: the four fingers curled (a fist) AND the thumb
# tip well away from every fingertip (thumb_gap >= THUMB_GAP_MIN — it
# points away from the fist instead of wrapping over it). Fire-once.
# THUMB_TUCKED_MAX is the LOWER bar for a LEFT-click fist: the thumb must be
# clearly wrapped in. The 0.28..0.36 band is a dead zone — neither click
# fires — which is where a fist-open thumb blip lands.
THUMB_GAP_MIN = 0.36
THUMB_TUCKED_MAX = 0.28
# OPEN PALM ("do nothing / reposition") — a SEPARATE, higher bar than the
# 👍 test: the thumb must be clearly fanned out (a pointing hand's thumb
# noise sits near 0.3-0.4 and used to trip this, freezing the cursor mid-aim).
# Median-smoothed over OPEN_PALM_WINDOW + OPEN_PALM_FRAMES of dwell.
OPEN_PALM_THUMB_MIN = 0.50
OPEN_PALM_WINDOW = 5
OPEN_PALM_FRAMES = 3
RIGHT_CLICK_FRAMES = 3
RIGHT_CLICK_LOCKOUT_S = 0.8
RIGHT_AFTER_LEFT_LOCKOUT_S = 0.35  # brief right-click block after a left click

# SCROLL — index AND middle both clearly extended (a "peace sign"): the
# cursor holds and vertical travel of the fingertip turns the mouse wheel.
# The middle-finger threshold is high + debounced so its noisy straightness
# can't flip in and out of scroll mode while you're just pointing.
# The middle-finger straightness is noisy on this camera (swings ~0.45-1.0
# frame to frame), so the pose test runs on a MEDIAN over SCROLL_MID_WINDOW
# frames, with a wide hysteresis gap and a few frames of dwell.
SCROLL_MID_WINDOW = 5          # median window on the middle-finger signal
SCROLL_MIDDLE_MIN = 0.80       # median straightness to ENTER scroll
SCROLL_MIDDLE_STAY = 0.50      # ...to STAY (hysteresis — wide gap)
SCROLL_ENTER_FRAMES = 3        # consecutive frames both-up before scroll starts
SCROLL_EXIT_FRAMES = 3         # consecutive frames middle-down before it ends
SCROLL_DEADZONE_NORM = 0.006   # ignore vertical drift below this (normalised)
SCROLL_STEP_NORM = 0.014       # normalised vertical travel per one wheel click
SCROLL_MAX_CLICKS_PER_TICK = 3
# False (default): finger up -> page scrolls up. Set NABVE_GESTURE_SCROLL_INVERT=1
# for the opposite (natural / touchpad-style).
SCROLL_INVERT = os.environ.get("NABVE_GESTURE_SCROLL_INVERT", "").strip() in ("1", "true", "yes")

# A click is a TAP by default: after CLICK_TAP_SECONDS held it auto-releases
# unless a signal is still actively squeezed (a drag). The absolute release
# bars sit inside this user's relaxed-hand noise, so without this clicks
# stayed stuck for seconds.
CLICK_TAP_SECONDS = 0.7

# After ANY click-up, block the next click until EITHER this long has passed
# OR the hand has clearly opened (both signals well past their release bars
# for CLICK_RELEASE_FRAMES). That kills the machine-gun where a hand
# oscillating around the engage threshold auto-taps every ~0.7s (it never
# "clearly opens"), while a real release opens the hand and lifts the lock
# at once, so a fast double-click still works.
CLICK_REPEAT_LOCKOUT_S = 1.0

# Shared smoothing + debounce for the click state machines. The gap signal
# is noisy near the engage bar, so a wider median + one more engage frame.
CLICK_MEDIAN_WINDOW = 5
CLICK_ENGAGE_FRAMES = 3
CLICK_RELEASE_FRAMES = 2
CLICK_MAX_HOLD_SECONDS = 4.0

# Pre-click freeze: when a click signal changes fast toward "engaged"
# between frames (fingers closing), the cursor is held for PRECLICK_FREEZE_
# FRAMES ticks so the closing arc can't nudge the pointer off target.
PRECLICK_DELTA = 0.06
PRECLICK_FREEZE_FRAMES = 5

# --- Absolute mapping ----------------------------------------------------
# The pointing rectangle in the (mirrored) camera frame that maps to the
# whole screen: a centred inset box, or the personal rectangle from the
# CORNERS calibration phase. Point near a frame corner -> cursor at that
# screen corner; points outside clamp to the screen edge.
DEFAULT_TRACKING_ZONE = 0.60   # central fraction of the frame -> whole screen

# The cursor EASES toward the mapped point (EMA) instead of snapping there,
# so pointing somewhere far glides and there's time to react. Higher =
# snappier, lower = slower / heavier. Tune this one knob for feel.
ABS_FOLLOW_RATE = 0.18
# After a clutch (open palm / hand lost / physical-mouse yield) the mapping
# is re-anchored so the cursor RESUMES from where it was instead of jumping
# to wherever the finger now points. That offset then decays by this factor
# each frame, so absolute accuracy returns within ~1.5 s of steady pointing.
CLUTCH_DECAY = 0.94
CORNER_CALIBRATION_SAMPLES = 90
CORNER_ZONE_PAD = 0.03         # shrink the swept rectangle inward this much
CORNER_ZONE_MIN_SPAN = 0.18    # below this on an axis -> ignore the sweep entirely
# A narrow sweep that still passes MIN_SPAN is EXPANDED around its centre to
# at least this width per axis, so the mapping gain never gets so high the
# cursor turns hypersensitive (a tiny zone maps big screen moves to a
# fingertip twitch). Also the floor for accepting a STORED zone.
CORNER_ZONE_MIN_WIDTH = 0.42

# On-screen cursor deadzone (px): a mapped move smaller than this is
# ignored, killing the last of the landmark shimmer for a resting hand.
# STEADY calibration measures the user's own fingertip tremor and stores a
# personal value; these are the fallback + clamp band.
CURSOR_DEADZONE_PX = 6
DEADZONE_PX_MIN, DEADZONE_PX_MAX = 2, 30
JITTER_LOW_PX, JITTER_HIGH_PX = 1.5, 9.0   # tremor band -> min_cutoff lerp

# A landmark set that blew up (a fingertip/wrist point flew off, distances
# exploded, every derived signal spiked to its clamp) is rejected as a
# frame: a real hand can't be this small, and no landmark sits this far
# outside the frame.
HAND_MIN_SCALE = 0.04        # wrist -> middle-knuckle distance, normalised
# A coord this far outside [0, 1] is a blowup. Was 1.15 (only 0.15 of
# slack) — too tight: a hand reaching toward a screen corner is legitimately
# ~1/3 out of frame, and dropping those frames made the corner-tracing
# calibration unable to reach the extremes it needs. 1.35 still rejects a
# real skeleton explosion (coords at 3.0 / -2.0); HAND_MIN_SCALE + the
# knuckle-radius check still catch scattered blobs.
LANDMARK_BOUND = 1.35

# Per-user rigid-bone fit (bone_fit.py). The first BONE_SCAN_FRAMES frames
# with a hand present are used to learn this hand's bone lengths (median);
# after that every frame's raw 21 points are snapped so each bone matches
# its learned length along the raw direction — a fingertip that jumps can no
# longer stretch its segment 3x, so the derived click signals stay stable.
BONE_SCAN_FRAMES = 90
# How far to pull a raw point toward its rigid position for SMALL errors
# (the blend ramps to 1.0 = fully rigid as the error approaches a whole bone
# length, i.e. a blowup). Was 0.85 — too stiff, it flattened the real
# finger-curl signal the click detector reads; 0.5 keeps spike protection
# while letting genuine motion through.
BONE_FIT_BLEND = 0.5
BONE_FIT_ENABLED = os.environ.get("NABVE_GESTURE_BONE_FIT", "1").strip() not in ("0", "false", "no")

# MediaPipe num_hands is fixed at 1 — two-hand zoom is gone, and a second
# (often phantom) hand was a source of primary-hand flips and blowups.
HAND_NUM_HANDS = 1

# Hard cap on cursor travel in one worker tick: the smaller of
# MAX_CURSOR_STEP_FRAC * min(screen_w, screen_h) and MAX_CURSOR_STEP_PX.
# Only there to stop a single glitched frame flinging the pointer across the
# display; a real fast sweep must still be able to cross a wide desktop in a
# few ticks, so the cap is generous now (the old 324 px throttled every
# sweep on a 3840-wide desktop to a crawl).
MAX_CURSOR_STEP_FRAC = 0.9
MAX_CURSOR_STEP_PX = 1400

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
ONE_EURO_MIN_CUTOFF = 0.6      # lower = steadier at rest, a touch more lag
# Lowered from 1.6 / 1.0: a hand turned side-on to the camera makes the
# index tip jitter, which reads as "speed" and used to open the filter and
# let the jitter through. Less speed-coupling + a smoother speed estimate
# trades a little lag on fast deliberate moves for a calmer cursor.
ONE_EURO_BETA = 1.1
ONE_EURO_D_CUTOFF = 0.7

# STEADY phase: hold the pointing fingertip still, measure its RMS tremor
# (in screen px, via the mapping), map it across [JITTER_LOW_PX,
# JITTER_HIGH_PX] to a resting 1€ cutoff between MIN_CUTOFF_CEIL (steady
# hand, lighter) and MIN_CUTOFF_FLOOR (shaky, heavier); the same tremor
# sets the on-screen deadzone.
MIN_CUTOFF_FLOOR = 0.45
MIN_CUTOFF_CEIL = 1.6
STEADY_CALIBRATION_SAMPLES = 60

# Calibration refuses to store a threshold learned from a bad feed: a frame
# darker than this (mean 0-255) can't be trusted, and if more than
# CALIBRATION_MAX_DARK_FRACTION of the frames so far are dark the wizard
# aborts instead of persisting garbage (checked at EVERY phase boundary now,
# not just after STEADY — a dark session once wrote the deadzone/pinch
# clamps to their extremes and broke everything).
CALIBRATION_MIN_BRIGHTNESS = 45.0
CALIBRATION_MAX_DARK_FRACTION = 0.4

# A calibration phase that hasn't completed after this many frames (~15-20 s)
# is force-finished with whatever data it has (falling back to the default
# threshold if too little) and the wizard moves on — so a gesture the
# camera can't separate for this user can't hang the whole wizard behind a
# frozen cursor with no way out.
CALIBRATION_PHASE_MAX_FRAMES = 400

# If the reader had frames flowing and then gets nothing for this long (a
# real driver stall, e.g. an abrupt lighting change forcing an exposure
# renegotiation), it reopens the camera rather than wedging the cursor.
# Generous so a merely slow (a few fps) feed is never mistaken for a stall.
CAMERA_STALL_REOPEN_SECONDS = 8.0

# The reader opened the device but not a single frame has ever arrived for
# this long — treat it as "camera busy / unavailable" (Zoom, OBS, a browser
# tab holding it) and shut the mode down with a spoken reason instead of
# idling forever with a frozen cursor and no error.
CAMERA_NO_FRAMES_FAIL_SECONDS = 6.0
# Consecutive failed reopen attempts (each ~CAMERA_STALL_REOPEN_SECONDS
# apart) before the reader stops retrying and reports the camera as gone,
# rather than looping reopen forever behind a dead cursor.
CAMERA_REOPEN_MAX_ATTEMPTS = 3

# A HELD click coasts through this many hand-less frames before it is
# force-released (vs HAND_LOST_COAST_FRAMES for a bare cursor). MediaPipe
# drops the hand constantly and far more during a pinch (fingers overlap) —
# a live run had ~half of pinch-clicks dying mid-press at ~12 frames, so
# ~1 s of grace here (@ ~25 fps).
FIST_LOST_GRACE_FRAMES = 25
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
HAND_LOST_COAST_FRAMES = 18
# A sustained loss (this many missed frames — well past the coast) pulses
# the cursor size once and says so once. The voice line does not repeat for
# HAND_LOST_VOICE_COOLDOWN_S (so a hand that keeps flickering out only nags
# the first time; the pulse still fires each time).
HAND_LOST_ALERT_FRAMES = 45
HAND_LOST_VOICE_COOLDOWN_S = 600.0

# The physical mouse always wins: the instant the real cursor moves by
# more than this (px) from where the worker last put it, gesture control
# yields for this many seconds (refreshed on every further physical move).
# The worker now re-anchors its reference every tick (including ticks it
# doesn't move the cursor), so this only trips on motion from something
# else — 18 px is a comfortable margin over pointer rounding.
PHYSICAL_MOUSE_THRESHOLD_PX = 18
PHYSICAL_MOUSE_OVERRIDE_SECONDS = 1.2

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
# Detection stays strict (first lock-on), but presence/tracking are loose so
# MediaPipe HOLDS the hand through a hard-to-read pose — turned side-on to
# point at the monitor — instead of dropping it and forcing a re-detect.
HAND_DETECTION_CONFIDENCE = 0.6
HAND_PRESENCE_CONFIDENCE = 0.4
HAND_TRACKING_CONFIDENCE = 0.35
HAND_BBOX_MIN = 0.03  # fraction of the frame — smaller = noise
HAND_BBOX_MAX = 0.85  # larger = fills the frame, not a hand held up to the camera
# Max ratio of any wrist->knuckle distance to their mean. A hand turned
# edge-on foreshortens the knuckles unevenly (pinky MCP crowds the wrist in
# 2D), so this is deliberately loose — a real skeleton explosion is caught
# by `blowup`/`bbox` regardless.
HAND_KNUCKLE_RADIUS_TOLERANCE = 4.0
# A hand must be seen this many consecutive frames before it drives the
# cursor, so a one-frame false blip can't jerk the pointer. hand_seen_streak
# decays by 1 on a missed frame rather than resetting, so a brief tracking
# gap doesn't restart the warmup.
HAND_WARMUP_FRAMES = 2

# MediaPipe Tasks HandLandmarker model — fetched once on first use into
# data/models/, same pattern as the Silero TTS weights. The fetch must fail
# loudly (not hang) on a slow/absent network, and a truncated download must
# be rejected rather than handed to MediaPipe as a broken .task file.
MODEL_DOWNLOAD_TIMEOUT_S = 30.0
MODEL_MIN_BYTES = 1_000_000  # the float16 hand_landmarker.task is ~7-8 MB
MODELS_DIR = DATA_DIR / "models"
HAND_LANDMARKER_TASK_PATH = MODELS_DIR / "hand_landmarker.task"
HAND_LANDMARKER_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
