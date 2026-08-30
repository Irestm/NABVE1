from __future__ import annotations

import numpy as np

from modules.discussion_mode.config import SPEAKER_PITCH_GAP_HZ

# Lightweight "sounds like one voice or two" heuristic — NOT real speaker
# diarization. A per-utterance fundamental-frequency estimate (autocorrelation,
# pure numpy) is matched against up to two running pitch centroids kept on
# the DiscussionSession. Escalating to pyannote.audio would be the next step
# if this proves too coarse in practice (see the task spec).

_F0_MIN_HZ = 70.0
_F0_MAX_HZ = 400.0
_CENTROID_EMA = 0.3  # how fast a speaker's centroid follows new evidence


def estimate_f0(signal: np.ndarray, sample_rate: int) -> float | None:
    """Rough voiced-pitch estimate for a mono float32 window, or None when
    it's too quiet / has no clear periodicity to call."""
    if signal.ndim > 1:
        signal = signal.mean(axis=1)
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size < sample_rate // 20:  # < ~50ms, not enough to judge
        return None
    signal = signal - signal.mean()
    rms = float(np.sqrt(np.mean(signal**2)))
    if rms < 1e-4:
        return None

    autocorr = np.correlate(signal, signal, mode="full")[signal.size - 1 :]
    min_lag = int(sample_rate / _F0_MAX_HZ)
    max_lag = int(sample_rate / _F0_MIN_HZ)
    if max_lag <= min_lag or max_lag >= autocorr.size:
        return None

    window = autocorr[min_lag:max_lag]
    if window.size == 0 or window.max() <= 0:
        return None
    # Require the periodic peak to be a real fraction of the zero-lag energy
    # — otherwise it's unvoiced noise and a "pitch" would be meaningless.
    if window.max() < 0.3 * autocorr[0]:
        return None

    lag = min_lag + int(np.argmax(window))
    return sample_rate / lag


def estimate_speaker(signal: np.ndarray, sample_rate: int, centroids: list[float]) -> str:
    """Returns "спикер 1" / "спикер 2" for this window, mutating `centroids`
    (a list held on DiscussionSession, 0-2 entries) in place. A third
    distinct voice just maps to whichever of the two it's closest to."""
    f0 = estimate_f0(signal, sample_rate)
    if f0 is None:
        return f"спикер {len(centroids) or 1}"

    if not centroids:
        centroids.append(f0)
        return "спикер 1"

    distances = [abs(f0 - c) for c in centroids]
    nearest = int(np.argmin(distances))
    if distances[nearest] > SPEAKER_PITCH_GAP_HZ and len(centroids) < 2:
        centroids.append(f0)
        return f"спикер {len(centroids)}"

    centroids[nearest] = (1 - _CENTROID_EMA) * centroids[nearest] + _CENTROID_EMA * f0
    return f"спикер {nearest + 1}"
