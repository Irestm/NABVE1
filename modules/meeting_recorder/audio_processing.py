from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

# Generous but bounded: real-world opus encoding is much faster than
# realtime, so this should never actually be approached for a legitimate
# (even near-2h30m) recording. The point isn't tuning it tightly — it's
# making sure a hung/pathological ffmpeg process (e.g. fed a truncated
# raw.webm from a crashed browser tab mid-chunk) can't block
# RecordingProcessor's single poller thread forever, freezing every other
# queued recording behind it until the app is restarted.
_FFMPEG_TIMEOUT_SECONDS = 1200
# ffprobe only reads container metadata, not the whole stream — near-instant
# regardless of file length, so this bound is just a safety net.
_FFPROBE_TIMEOUT_SECONDS = 30


def _find_binary(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(
            f"'{name}' was not found on this system. Install ffmpeg "
            f"(it provides both ffmpeg and ffprobe) and ensure it is on PATH."
        )
    return found


def _run(args: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"'{args[0]}' did not finish within {timeout_seconds:.0f}s and was aborted: {' '.join(args)}"
        ) from exc


def convert_to_ogg(raw_path: Path, output_path: Path) -> None:
    """Converts the raw, chunk-appended MediaRecorder capture into a single
    mono Opus/OGG file, with loudness normalization applied best-effort:
    if the `loudnorm` filter pass fails for any reason, falls back to a
    plain re-encode rather than failing the whole recording over a
    cosmetic normalization step."""
    ffmpeg = _find_binary("ffmpeg")
    base_args = [
        ffmpeg,
        "-y",
        "-i",
        str(raw_path),
        "-vn",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
    ]

    normalized = _run([*base_args, "-af", "loudnorm", str(output_path)], timeout_seconds=_FFMPEG_TIMEOUT_SECONDS)
    if normalized.returncode == 0:
        return

    logger.warning(
        "Loudness normalization failed for '%s', falling back to plain conversion: %s",
        raw_path,
        normalized.stderr.strip() or normalized.stdout.strip(),
    )
    plain = _run([*base_args, str(output_path)], timeout_seconds=_FFMPEG_TIMEOUT_SECONDS)
    if plain.returncode != 0:
        raise RuntimeError(
            f"ffmpeg conversion failed (exit code {plain.returncode}): "
            f"{plain.stderr.strip() or plain.stdout.strip()}"
        )


def probe_duration_seconds(path: Path) -> float:
    """Independently measures the actual duration of a file on disk via
    ffprobe — used both for the raw upload (best-effort, for progress ETA)
    and, critically, for the converted final audio, where it is the sole
    source of truth for the 2h30m limit check. The client's self-reported
    duration is never trusted for that decision."""
    ffprobe = _find_binary("ffprobe")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout_seconds=_FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed to read duration of '{path}' (exit code {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"ffprobe returned an unparseable duration for '{path}': {result.stdout!r}") from exc
