from __future__ import annotations

from modules.discussion_mode.handlers import register_commands
from modules.discussion_mode.state import session

# The mode itself runs in core/voice/pipeline.py's sub-loop (same as board
# games / os-agent mode). register_commands only adds the "discussion_start"
# button/API entry point and needs the voice loop, so bootstrap calls it
# with an extra argument rather than the usual (dispatcher) signature.
__all__ = ["register_commands", "session"]
