from __future__ import annotations

import platform
import re
import subprocess
from typing import TypedDict

from core.logger import get_logger

logger = get_logger(__name__)


class HardwareProfile(TypedDict):
    ram_gb: int
    vram_gb: int
    cpu_tier: str
    cpu_model: str
    gpu_name: str | None


_CPU_TIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("high", re.compile(r"i9|ryzen 9|ryzen threadripper|xeon", re.I)),
    ("mid", re.compile(r"i7|i5|ryzen 7|ryzen 5", re.I)),
    ("low", re.compile(r"i3|ryzen 3|celeron|pentium|atom", re.I)),
)


def _detect_ram_gb() -> int:
    """Total system RAM in GB, rounded. /proc/meminfo on Linux, the Windows
    API via ctypes elsewhere; 0 if neither is available (detection failure
    should degrade to "no local model", never crash the caller)."""
    try:
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemTotal:"):
                    kib = int(line.split()[1])
                    return round(kib / (1024 * 1024))
    except OSError:
        pass

    if platform.system() == "Windows":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return round(status.ullTotalPhys / (1024 ** 3))
        except (OSError, AttributeError, ValueError) as exc:
            logger.warning("Failed to detect RAM via Windows API: %s", exc)

    logger.warning("Could not detect total system RAM; assuming 0 GB")
    return 0


def _detect_gpu() -> tuple[int, str | None]:
    """(vram_gb, gpu_name) for the first NVIDIA GPU visible to nvidia-smi, or
    (0, None) if nvidia-smi isn't present/no CUDA GPU exists. A CUDA-capable
    NVIDIA GPU is a hard requirement for the local model — anything else is
    treated identically to "no GPU"."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        first_line = result.stdout.strip().splitlines()[0]
        name, mem_mib = (part.strip() for part in first_line.split(","))
        return round(int(mem_mib) / 1024), name
    except (subprocess.SubprocessError, OSError, IndexError, ValueError) as exc:
        logger.info("No NVIDIA/CUDA GPU detected (nvidia-smi unavailable or failed): %s", exc)
        return 0, None


def _detect_cpu_model() -> str:
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="ascii") as cpuinfo:
                for line in cpuinfo:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.uname().processor or "unknown"


def _classify_cpu_tier(cpu_model: str) -> str:
    for tier, pattern in _CPU_TIER_PATTERNS:
        if pattern.search(cpu_model):
            return tier
    return "unknown"


def detect_hardware() -> HardwareProfile:
    """Detects the RAM/VRAM/CPU available on this machine, used by
    modules.hardware_adaptive.model_tiers.select_tier to decide whether (and
    which) local model to run. Detection is best-effort: any failure degrades
    toward "local model unavailable" rather than raising, since ai_bridge is
    always a safe fallback."""
    ram_gb = _detect_ram_gb()
    vram_gb, gpu_name = _detect_gpu()
    cpu_model = _detect_cpu_model()
    profile: HardwareProfile = {
        "ram_gb": ram_gb,
        "vram_gb": vram_gb,
        "cpu_tier": _classify_cpu_tier(cpu_model),
        "cpu_model": cpu_model,
        "gpu_name": gpu_name,
    }
    logger.info("Detected hardware profile: %s", profile)
    return profile
