from __future__ import annotations

import sys
from pathlib import Path

# office_bridge/win_*_handlers.py + win_session.py use the same flat,
# run-as-a-script import style as the Linux side (office_bridge/server.py
# adds its own directory to sys.path automatically when launched directly —
# see that script's own `from office_session import ...`), so tests need the
# same directory on sys.path to import them the identical way. Deliberately
# NOT importing office_bridge/server.py, office_session.py, or any of the
# Linux writer_handlers.py/etc. here — those import UNO (`import uno`,
# `from com.sun.star...`) at module level, which isn't installed in this
# venv; win_session.py/win_*_handlers.py were specifically kept free of that
# dependency (see win_session.py's own module docstring) so they, unlike
# their Linux counterparts, actually can be unit-tested here.
_OFFICE_BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent / "office_bridge"
if str(_OFFICE_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_OFFICE_BRIDGE_DIR))
