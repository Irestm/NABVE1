from __future__ import annotations

from core.voice.intent import Command, interpret
from core.voice.plugin_match import match_plugin_command
from modules.hardware_adaptive import command_classifier

# A delayed command is resolved once, at schedule time, through the fast
# fully-local chain only (rule-based interpret -> plugin trigger -> local
# embedding classifier). The AI classifier is deliberately skipped: it is
# slow, may need network/quota, and asking the user to disambiguate ten
# minutes before the command should even run makes no sense. A remainder
# the local chain can't place just isn't schedulable — the caller says so
# out loud rather than guessing.

_UNSCHEDULABLE = frozenset(
    {
        # These need an unbounded number of follow-up voice turns that a
        # fire-and-forget timer has no way to carry out.
        "start_board_game",
        "start_os_agent",
        "messaging_reply",
        "messaging_snooze",
        "run_task_plan",
        "ui_action",
    }
)


def resolve_command(remainder: str, language: str) -> Command | None:
    command = (
        interpret(remainder, language)
        or match_plugin_command(remainder)
        or command_classifier.match_system_command(remainder)
    )
    if command is None or command.name in _UNSCHEDULABLE:
        return None
    return command
