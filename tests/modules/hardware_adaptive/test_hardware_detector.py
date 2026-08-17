from __future__ import annotations

import subprocess
from io import StringIO
from types import SimpleNamespace

import pytest

from modules.hardware_adaptive import hardware_detector as hd


def _fake_open_for(path_to_content: dict[str, str]):
    real_open = open

    def _fake_open(path, *args, **kwargs):
        text = path_to_content.get(str(path))
        if text is None:
            raise OSError(f"no such file: {path}")
        return StringIO(text)

    return _fake_open


def test_detect_ram_gb_reads_proc_meminfo(monkeypatch: pytest.MonkeyPatch) -> None:
    meminfo = "MemTotal:       16384000 kB\nMemFree:         2048000 kB\n"
    monkeypatch.setattr("builtins.open", _fake_open_for({"/proc/meminfo": meminfo}))

    assert hd._detect_ram_gb() == round(16384000 / (1024 * 1024))


def test_detect_ram_gb_falls_back_to_zero_when_proc_unavailable_and_not_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("builtins.open", _fake_open_for({}))
    monkeypatch.setattr(hd.platform, "system", lambda: "Linux")

    assert hd._detect_ram_gb() == 0


def test_detect_ram_gb_uses_windows_api_when_proc_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.open", _fake_open_for({}))
    monkeypatch.setattr(hd.platform, "system", lambda: "Windows")

    fake_kernel32 = SimpleNamespace(
        GlobalMemoryStatusEx=lambda ref: setattr(ref._obj, "ullTotalPhys", 8 * (1024**3))
    )
    fake_windll = SimpleNamespace(kernel32=fake_kernel32)
    monkeypatch.setattr("ctypes.windll", fake_windll, raising=False)

    assert hd._detect_ram_gb() == 8


def test_detect_ram_gb_falls_back_to_zero_when_windows_api_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.open", _fake_open_for({}))
    monkeypatch.setattr(hd.platform, "system", lambda: "Windows")

    def _boom(ref):
        raise OSError("no such API")

    fake_windll = SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=_boom))
    monkeypatch.setattr("ctypes.windll", fake_windll, raising=False)

    assert hd._detect_ram_gb() == 0


def test_detect_gpu_parses_nvidia_smi_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_result = SimpleNamespace(stdout="NVIDIA GeForce RTX 4050, 6144\n")
    monkeypatch.setattr(hd.subprocess, "run", lambda *a, **k: fake_result)

    vram_gb, gpu_name = hd._detect_gpu()

    assert vram_gb == round(6144 / 1024)
    assert gpu_name == "NVIDIA GeForce RTX 4050"


def test_detect_gpu_returns_zero_and_none_when_nvidia_smi_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")

    monkeypatch.setattr(hd.subprocess, "run", _raise)

    assert hd._detect_gpu() == (0, None)


def test_detect_gpu_returns_zero_and_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)

    monkeypatch.setattr(hd.subprocess, "run", _raise)

    assert hd._detect_gpu() == (0, None)


def test_detect_cpu_model_reads_proc_cpuinfo_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    cpuinfo = "processor\t: 0\nmodel name\t: AMD Ryzen 7 5800X\ncpu MHz\t: 3800\n"
    monkeypatch.setattr("builtins.open", _fake_open_for({"/proc/cpuinfo": cpuinfo}))
    monkeypatch.setattr(hd.platform, "system", lambda: "Linux")

    assert hd._detect_cpu_model() == "AMD Ryzen 7 5800X"


def test_detect_cpu_model_falls_back_when_proc_cpuinfo_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.open", _fake_open_for({}))
    monkeypatch.setattr(hd.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hd.platform, "processor", lambda: "x86_64")

    assert hd._detect_cpu_model() == "x86_64"


def test_detect_cpu_model_falls_back_to_uname_when_processor_is_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.open", _fake_open_for({}))
    monkeypatch.setattr(hd.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hd.platform, "processor", lambda: "")
    monkeypatch.setattr(hd.platform, "uname", lambda: SimpleNamespace(processor="unknown-cpu"))

    assert hd._detect_cpu_model() == "unknown-cpu"


def test_detect_cpu_model_skips_proc_on_non_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_open(*a, **k):
        raise AssertionError("should not read /proc/cpuinfo on non-Linux")

    monkeypatch.setattr("builtins.open", _fail_open)
    monkeypatch.setattr(hd.platform, "system", lambda: "Windows")
    monkeypatch.setattr(hd.platform, "processor", lambda: "Intel64 Family 6")

    assert hd._detect_cpu_model() == "Intel64 Family 6"


@pytest.mark.parametrize(
    "cpu_model,expected_tier",
    [
        ("Intel Core i9-13900K", "high"),
        ("AMD Ryzen 9 7950X", "high"),
        ("Intel Xeon E5-2680", "high"),
        ("Intel Core i7-10700K", "mid"),
        ("AMD Ryzen 5 5600X", "mid"),
        ("Intel Core i3-10100", "low"),
        ("Intel Celeron N4020", "low"),
        ("Some Obscure ARM Chip", "unknown"),
    ],
)
def test_classify_cpu_tier(cpu_model: str, expected_tier: str) -> None:
    assert hd._classify_cpu_tier(cpu_model) == expected_tier


def test_detect_hardware_assembles_profile_from_sub_detections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hd, "_detect_ram_gb", lambda: 32)
    monkeypatch.setattr(hd, "_detect_gpu", lambda: (8, "NVIDIA GeForce RTX 4060"))
    monkeypatch.setattr(hd, "_detect_cpu_model", lambda: "Intel Core i9-13900K")

    profile = hd.detect_hardware()

    assert profile == {
        "ram_gb": 32,
        "vram_gb": 8,
        "cpu_tier": "high",
        "cpu_model": "Intel Core i9-13900K",
        "gpu_name": "NVIDIA GeForce RTX 4060",
    }
