from __future__ import annotations

# Module-level "is agent mode currently listening for a task" flag — 1:1
# shape with modules.board_games.ui_session, but deliberately stateless
# beyond the flag itself: the actual per-task journal/queue
# (modules.os_agent.domain.AgentSession) is local to one runner.run_task()
# call, never stored here. One agent mode at a time, single-user local app,
# same reasoning as board_games' one-game-at-a-time singleton.
_active = False


def start() -> None:
    global _active
    _active = True


def is_active() -> bool:
    return _active


def finish() -> None:
    global _active
    _active = False
