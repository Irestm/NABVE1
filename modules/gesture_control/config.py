from __future__ import annotations

from core.config import DATA_DIR

# Profile-fact keys — stored the same way as stop_word / assistant_name
# (modules/user_profile), so per-user gesture tuning rides the same
# encrypted table/backup path as everything else.
GESTURE_PINCH_THRESHOLD_KEY = "gesture_pinch_threshold"
GESTURE_CURSOR_SCALE_KEY = "gesture_cursor_scale"
GESTURE_EMA_ALPHA_KEY = "gesture_ema_alpha"
GESTURE_TRACKING_ZONE_KEY = "gesture_tracking_zone"

# Falling back to these when the fact isn't set yet (before the first
# calibration / before the user touches the slider).
DEFAULT_PINCH_THRESHOLD = 0.06  # normalized landmark distance, replaced by calibration
DEFAULT_CURSOR_SCALE = 1.3
DEFAULT_EMA_ALPHA = 0.4  # 0..1, higher = snappier / less smoothed
DEFAULT_TRACKING_ZONE = 0.6  # central fraction of the camera frame that maps to the whole screen

# Processing is capped well below the camera's max FPS — enough for a
# responsive cursor, not enough to pin a CPU core. See the task's
# performance note and feedback_dont_overload_machine.
PROCESSING_FPS = 18
CAMERA_INDEX = 0

# MediaPipe Tasks HandLandmarker model — not on pip, fetched once on first
# use and cached here, the same shape as core/voice/silero_tts.py's weights
# file (see frontend/electron/setup.ts's SILERO_WEIGHTS_URL).
MODELS_DIR = DATA_DIR / "models"
HAND_LANDMARKER_TASK_PATH = MODELS_DIR / "hand_landmarker.task"
HAND_LANDMARKER_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
