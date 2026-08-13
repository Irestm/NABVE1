from __future__ import annotations

import platform

from core.os_adapter.base import OSAdapter

_adapter: OSAdapter | None = None


def get_os_adapter() -> OSAdapter:
    global _adapter
    if _adapter is not None:
        return _adapter

    system = platform.system()
    if system == "Windows":
        from core.os_adapter.windows import WindowsAdapter

        _adapter = WindowsAdapter()
    elif system == "Linux":
        from core.os_adapter.linux import LinuxAdapter

        _adapter = LinuxAdapter()
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")

    return _adapter
