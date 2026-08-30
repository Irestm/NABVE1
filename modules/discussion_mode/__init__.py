from __future__ import annotations

from modules.discussion_mode.state import session

# No register_commands: discussion mode is driven entirely from
# core/voice/pipeline.py's sub-loop (same as board games / os-agent mode),
# not through a dispatcher command.
__all__ = ["session"]
