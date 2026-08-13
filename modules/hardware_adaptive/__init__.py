from __future__ import annotations

from modules.hardware_adaptive.handlers import register_commands
from modules.hardware_adaptive.system_monitor import HardwareMonitor

hardware_monitor = HardwareMonitor()

__all__ = ["register_commands", "hardware_monitor"]
