from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.config import settings
from core.dispatcher import CommandDispatcher, build_dispatcher
from core.message_bus import MessageBus, message_bus
from core.telegram_notifier import TelegramNotifier
from core.voice.announcements import ReminderAnnouncer
from core.voice.pipeline import VoiceAssistantLoop
from core.voice.proactive_announcer import ProactiveAnnouncer
from modules.ai_bridge import register_commands as register_ai_bridge_commands
from modules.blender_control import register_commands as register_blender_control_commands
from modules.calendar import reminder_checker, register_commands as register_calendar_commands
from modules.calendar.events import ReminderDue
from modules.calendar.notifier import ReminderChecker
from modules.cmd_executor import register_commands as register_cmd_executor_commands
from modules.crm_transcribe import register_commands as register_crm_transcribe_commands
from modules.custom_commands import register_commands as register_custom_commands_commands
from modules.figma_control import register_commands as register_figma_control_commands
from modules.files import register_commands as register_files_commands
from modules.gmail import gmail_poller
from modules.gmail.poller import GmailPoller
from modules.hardware_adaptive import command_classifier, hardware_monitor, register_commands as register_hardware_adaptive_commands
from modules.hardware_adaptive.events import HardwareAlertRaised
from modules.hardware_adaptive.system_monitor import HardwareMonitor
from modules.media import register_commands as register_media_commands
from modules.meeting_recorder import recording_processor, recording_transcriber
from modules.meeting_recorder.processor import RecordingProcessor
from modules.meeting_recorder.transcriber_worker import RecordingTranscriber
from modules.messaging import register_commands as register_messaging_commands
from modules.messaging import snooze_checker
from modules.messaging.snooze_checker import SnoozeChecker
from modules.password_manager import register_commands as register_password_manager_commands
from modules.plugin_agent import register_commands as register_plugin_agent_commands
from modules.plugin_agent import shutdown as shutdown_plugin_agent
from modules.plugin_agent.events import PluginCandidateReadyForReview
from modules.quizlet_clone import register_commands as register_quizlet_clone_commands
from modules.search import register_commands as register_search_commands
from modules.task_orchestrator import register_commands as register_task_orchestrator_commands
from modules.ui_automation import register_commands as register_ui_automation_commands
from modules.ui_control import register_commands as register_ui_control_commands
from modules.user_profile import register_commands as register_user_profile_commands
from modules.wordpress_bridge import register_commands as register_wordpress_bridge_commands


@dataclass
class Composed:
    """Everything core/main.py's FastAPI app needs a handle on. Building
    this in one place (rather than each module constructing its own
    eager-at-import-time or lazy-on-first-call singleton) is this app's
    composition root — see
    https://www.cosmicpython.com/book/chapter_13_dependency_injection.html.
    Some singletons still legitimately live inside their module (e.g.
    ai_bridge's Playwright browser sessions) since
    they're genuinely long-lived adapter state, not something the
    composition root needs to reach into; what's composed here is
    specifically the cross-module wiring — the dispatcher, the voice loop,
    and the message-bus subscriptions that connect one module's events to
    another module's reactions."""

    dispatcher: CommandDispatcher
    voice_loop: VoiceAssistantLoop
    reminder_checker: ReminderChecker
    # modules.hardware_adaptive's HardwareMonitor is the same "no dispatcher
    # commands of its own, just a background poller" shape as
    # reminder_checker above — needs a start/stop handle from the lifespan.
    hardware_monitor: HardwareMonitor
    shutdown_plugin_agent: Callable[[], None]
    # modules.meeting_recorder has no dispatcher commands (its endpoints are
    # dedicated REST, not /api/command — see core/main.py), but its two
    # background pollers still need a start/stop handle from the lifespan,
    # same reason reminder_checker is composed here rather than started from
    # inside its own module.
    recording_processor: RecordingProcessor
    recording_transcriber: RecordingTranscriber
    # modules.messaging's SnoozeChecker is the same "no dispatcher commands
    # of its own, just a background poller" shape as recording_processor
    # above — see that comment.
    messaging_snooze_checker: SnoozeChecker
    # modules.gmail has no dispatcher commands either (read-only — see the
    # module's own docstring): modules.messaging's existing
    # messaging_watch_contact/messaging_list_watched/messaging_snooze
    # already work for any source unmodified. Same "just a background
    # poller" shape as messaging_snooze_checker above.
    gmail_poller: GmailPoller


def compose(bus: MessageBus = message_bus) -> Composed:
    dispatcher = build_dispatcher(settings.confirmation_ttl_seconds)
    voice_loop = VoiceAssistantLoop(dispatcher)

    # Starts loading the local embedding model + precomputing its command
    # catalog on a background thread now, so it's already warm by the time
    # the first voice command arrives (see command_classifier.match_system_command,
    # used by core/voice/pipeline.py and core/voice/web_pipeline.py) instead
    # of paying the ~1-2s model-load cost on that first real request.
    command_classifier.warm_up()

    register_files_commands(dispatcher)
    register_custom_commands_commands(dispatcher)
    register_quizlet_clone_commands(dispatcher)
    register_figma_control_commands(dispatcher)
    register_blender_control_commands(dispatcher)
    register_crm_transcribe_commands(dispatcher)
    register_ai_bridge_commands(dispatcher)
    register_search_commands(dispatcher)
    register_calendar_commands(dispatcher)
    register_cmd_executor_commands(dispatcher)
    register_user_profile_commands(dispatcher)
    register_password_manager_commands(dispatcher)
    register_plugin_agent_commands(dispatcher)
    register_ui_control_commands(dispatcher)
    register_hardware_adaptive_commands(dispatcher)
    register_media_commands(dispatcher)
    register_ui_automation_commands(dispatcher)
    register_messaging_commands(dispatcher)
    register_wordpress_bridge_commands(dispatcher)
    # Registered last is not load-bearing: dispatcher.list_commands() (what
    # modules.task_orchestrator.service_layer.build_plan offers the planner
    # as candidate steps) is only ever called later, at an actual voice
    # turn, by which point every register_*_commands call above has already
    # run regardless of source order.
    register_task_orchestrator_commands(dispatcher)

    # Cross-module wiring: a due reminder is also spoken aloud while the
    # voice loop is running, on top of calendar's own desktop-notification
    # subscriber (wired inside modules/calendar/__init__.py, since that one
    # doesn't need anything outside the calendar module).
    announcer = ReminderAnnouncer(voice_loop)
    bus.subscribe(ReminderDue, announcer.handle)

    # Same cross-module wiring shape as the reminder announcer above:
    # modules.hardware_adaptive only knows how to detect a low-battery/
    # low-disk condition and publish it, speaking it aloud depends on
    # core.voice's running loop, so that half is composed here.
    proactive_announcer = ProactiveAnnouncer(voice_loop)
    bus.subscribe(HardwareAlertRaised, proactive_announcer.handle)

    # Outbound Telegram notifications (see core/telegram_notifier.py) — a
    # separate delivery channel from the two spoken subscribers above, for
    # exactly the events that matter even when nobody's near the mic. A
    # no-op when TELEGRAM_NOTIFY_BOT_TOKEN/TELEGRAM_NOTIFY_CHAT_ID aren't
    # set, so this subscription is unconditional.
    telegram_notifier = TelegramNotifier()
    bus.subscribe(ReminderDue, telegram_notifier.handle_reminder)
    bus.subscribe(HardwareAlertRaised, telegram_notifier.handle_hardware_alert)
    bus.subscribe(PluginCandidateReadyForReview, telegram_notifier.handle_plugin_candidate)

    return Composed(
        dispatcher=dispatcher,
        voice_loop=voice_loop,
        reminder_checker=reminder_checker,
        hardware_monitor=hardware_monitor,
        shutdown_plugin_agent=shutdown_plugin_agent,
        recording_processor=recording_processor,
        recording_transcriber=recording_transcriber,
        messaging_snooze_checker=snooze_checker,
        gmail_poller=gmail_poller,
    )
