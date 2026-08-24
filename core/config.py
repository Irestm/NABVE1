from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent
# Overridable so a packaged Electron build (frontend/electron/backend.ts)
# can point these at a per-user writable directory (Electron's
# app.getPath("userData")) instead of next to the source tree — the source
# tree itself may be inside a read-only AppImage mount or a per-machine
# Program Files install with no write access. Unset in every other context
# (dev checkout, docker, tests), so behavior there is unchanged.
DATA_DIR: Path = Path(os.environ["ASSISTANT_DATA_DIR"]) if os.environ.get("ASSISTANT_DATA_DIR") else BASE_DIR / "data"
LOGS_DIR: Path = Path(os.environ["ASSISTANT_LOGS_DIR"]) if os.environ.get("ASSISTANT_LOGS_DIR") else BASE_DIR / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_API_TOKEN_PATH: Path = DATA_DIR / "api_token.txt"


def _load_or_create_api_token() -> str:
    """bind_host defaults to 0.0.0.0 (see Settings.bind_host below), so
    every /api/* route is reachable from anything on the LAN unless it
    proves it knows this token (see core/main.py's auth middleware) — a
    dangerous=True command otherwise only needs the two unauthenticated
    HTTP calls (dispatch, then confirm) that the legitimate frontend itself
    makes, which is no protection at all against another device on the
    network. Persisted to disk (rather than regenerated per process) so a
    restart doesn't invalidate every phone that already scanned the LAN QR
    code (see /api/lan_url, which embeds this value in the URL)."""
    env_token = os.environ.get("ASSISTANT_API_TOKEN")
    if env_token:
        return env_token
    if _API_TOKEN_PATH.is_file():
        stored = _API_TOKEN_PATH.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    token = secrets.token_urlsafe(32)
    _API_TOKEN_PATH.write_text(token, encoding="utf-8")
    return token


@dataclass(frozen=True)
class Settings:
    # Used for local health checks (watchdog) and as the default API base URL —
    # always loopback, regardless of where the server actually binds.
    host: str = os.environ.get("ASSISTANT_HOST", "127.0.0.1")
    port: int = int(os.environ.get("ASSISTANT_PORT", "8756"))
    # The address uvicorn actually binds to. Defaults to all interfaces so a
    # phone on the same Wi-Fi/LAN can reach http://<pc-lan-ip>:{port} as a thin
    # client (see core/main.py's static frontend mount and /api/voice/*).
    # This is a LAN-only convenience, not internet exposure: nothing here opens
    # a router port, so the server stays unreachable from outside the LAN
    # unless something else (e.g. explicit port forwarding) does that.
    bind_host: str = os.environ.get("ASSISTANT_BIND_HOST", "0.0.0.0")
    # Shared secret every /api/* request must present (header X-Assistant-Token
    # or ?token= query param) — see core/main.py's auth middleware and
    # _load_or_create_api_token's docstring above for why this exists.
    api_token: str = _load_or_create_api_token()
    log_file: Path = LOGS_DIR / "assistant.log"
    db_path: Path = DATA_DIR / "assistant.db"
    confirmation_ttl_seconds: int = int(os.environ.get("ASSISTANT_CONFIRM_TTL", "60"))
    voice_autostart: bool = os.environ.get("ASSISTANT_VOICE_AUTOSTART", "true").lower() == "true"
    # "*" is safe here because allow_credentials=False (see main.py's
    # CORSMiddleware setup) — the real access boundary is api_token above,
    # not origin checking. A specific-origins allowlist (previously just the
    # Vite dev server) breaks the packaged Electron build: it loads the UI
    # over file://, whose Origin header (null / "file://", depending on
    # platform) never matches an http://host:port entry, so the renderer's
    # fetch() calls were silently CORS-blocked — the request reached the
    # server and got a 200 (visible in the server log), but the browser
    # withheld the response from JS, which read as a permanent "no
    # connection" error. LAN thin clients (phone browsers) already load the
    # page same-origin from this same server so were never affected either
    # way, and the dev server origin still works under "*" too.
    allowed_origins: tuple[str, ...] = ("*",)
    # modules/meeting_recorder: 2h30m matches the client-side auto-stop limit
    # (see the module's frontend capture logic) — this is the independent
    # server-side check via ffprobe, the client's own reported duration is
    # never trusted for the actual accept/reject decision.
    meeting_recording_max_duration_seconds: int = int(
        os.environ.get("ASSISTANT_MEETING_MAX_DURATION_SECONDS", str(2 * 3600 + 30 * 60))
    )
    # Streaming upload is rejected mid-flight once the raw file passes this
    # size, rather than buffering the whole thing and checking at the end.
    meeting_recording_max_size_bytes: int = int(
        os.environ.get("ASSISTANT_MEETING_MAX_SIZE_BYTES", str(500 * 1024 * 1024))
    )
    # Optional free-tier Groq API key (https://console.groq.com) — used by
    # modules/ai_bridge/api_providers.py::GroqApiAdapter as a fast tier ahead
    # of the local model and the ai_bridge browser-automation chain (see
    # core/ai_adapter_chain.py::free_api_first_chain). Absent by default: no
    # key means that adapter simply doesn't exist and every AI call behaves
    # exactly as it did before this feature — never a paid fallback.
    groq_api_key: str | None = os.environ.get("GROQ_API_KEY") or None
    # Optional outbound Telegram notifications (battery/disk alerts, due
    # reminders, plugins awaiting review — see core/telegram_notifier.py).
    # telegram_notify_bot_token is a Bot API token (from @BotFather — reuse
    # your own bot's token, e.g. the same BOT_TOKEN a companion Telegram bot
    # project already uses); telegram_notify_chat_id is the Telegram user id
    # that should receive them (your own id — the same one a bot's
    # ADMIN_IDS would contain). Both None by default: notifications are
    # simply not sent, nothing else about this app changes.
    telegram_notify_bot_token: str | None = os.environ.get("TELEGRAM_NOTIFY_BOT_TOKEN") or None
    telegram_notify_chat_id: str | None = os.environ.get("TELEGRAM_NOTIFY_CHAT_ID") or None
    # Where the Jarvis Voice Control Blender addon's local HTTP server (see
    # blender_addon/server.py) listens — always loopback by default since
    # Blender runs on the same machine as this backend. See
    # modules/blender_control/ws_client.py.
    blender_host: str = os.environ.get("ASSISTANT_BLENDER_HOST", "127.0.0.1")
    blender_port: int = int(os.environ.get("ASSISTANT_BLENDER_PORT", "8766"))
    # Where office_bridge/server.py's local HTTP server listens — one shared
    # bridge for every LibreOffice app Jarvis controls (Writer, Calc, ...;
    # see office_bridge/server.py's own docstring for why one process), used
    # by both modules/office_writer/bridge_client.py and
    # modules/office_excel/bridge_client.py. That server runs under the
    # system Python (it needs pyuno, which isn't pip-installable into this
    # project's venv), spawned on demand by bridge_client.ensure_bridge_running()
    # rather than started at app boot, so most sessions never launch
    # LibreOffice at all.
    office_bridge_host: str = os.environ.get("ASSISTANT_OFFICE_BRIDGE_HOST", "127.0.0.1")
    office_bridge_port: int = int(os.environ.get("ASSISTANT_OFFICE_BRIDGE_PORT", "8767"))
    # The interpreter bridge_client.py spawns office_bridge/server.py with.
    # Linux-only setting: Ubuntu ships python3-uno as a system dist-packages
    # module, not a pip wheel, hence a separate interpreter path; override if
    # pyuno lives somewhere else. Ignored on Windows — bridge_client.py's
    # _IS_WINDOWS branch spawns office_bridge/server_win.py with this
    # backend's own sys.executable instead, since pywin32 (that bridge's
    # dependency) installs straight into this project's venv.
    office_bridge_system_python: str = os.environ.get("ASSISTANT_OFFICE_BRIDGE_PYTHON", "/usr/bin/python3")
    # How long modules.fitness_tracker's voice context (core/voice/module_context.py)
    # stays active with no fitness-related utterance before it silently
    # resets to the normal command pipeline — see
    # modules/fitness_tracker/context_state.py. Mid-range of the "5-10
    # minutes" the task spec asked for.
    fitness_context_timeout_seconds: int = int(os.environ.get("ASSISTANT_FITNESS_CONTEXT_TIMEOUT_SECONDS", "420"))


settings = Settings()

MEETING_RECORDINGS_DIR: Path = DATA_DIR / "meeting_recordings"
MEETING_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

GENERATED_IMAGES_DIR: Path = DATA_DIR / "generated_images"
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# modules/office_notes' notebooks — LibreOffice has no OneNote analog, so a
# "notebook" is just a Writer .odt file here, addressed by name rather than
# a full path (see modules/office_notes/dispatcher.py's _resolve_path).
NOTES_DIR: Path = DATA_DIR / "notebooks"
NOTES_DIR.mkdir(parents=True, exist_ok=True)

# modules/fitness_tracker's meal/progress photos — stored locally only, per
# the task spec's privacy requirement (never uploaded anywhere except the
# one AI provider call that analyzes a given photo, same one-shot exposure
# modules.code_analysis's screenshot vision path already has).
FITNESS_MEDIA_DIR: Path = DATA_DIR / "fitness_media"
FITNESS_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Prepended to every prompt sent to any model — local or via ai_bridge — so the
# assistant's tone stays consistent no matter which provider actually answers.
# Applied centrally in ProviderManager.send_prompt and LocalInferenceEngine.generate
# (see modules/ai_bridge/system_prompt.py), never at individual call sites.
#
# Structure follows the same "ideal prompt" checklist deliberately: state the
# role and WHY the constraints exist (a model generalizes a rule better once
# it understands the reason, not just the rule), separate distinct instruction
# categories instead of one run-on paragraph, phrase the highest-risk
# constraints as both a positive rule and its explicit negative counterpart,
# and reserve CAPS for the handful of rules most responsible for a bad
# real-world result (unread-aloud formatting artifacts, invented facts,
# unsolicited rambling) rather than everything at once — capitalizing the
# whole prompt would just make the model pattern-match "loud text", not
# "important text".
SYSTEM_PROMPT_PREFIX: str = (
    "ТЫ — ГОЛОСОВОЙ АССИСТЕНТ. Твой ответ читает вслух синтезатор речи и НИКОГДА не показывается "
    "как текст на экране — учитывай это в каждом ответе.\n"
    "ФОРМАТ ОТВЕТА: только обычный связный текст, как в устной речи. НЕ ИСПОЛЬЗУЙ: markdown, "
    "звёздочки и решётки, дефисы или цифры как маркеры списка, таблицы, блоки кода, кавычки-ёлочки, "
    "эмодзи, символ процента и другие знаки форматирования — синтезатор речи прочитает их вслух "
    "буквально как отдельные слова или символы, и ответ станет бессмысленным. Числа и проценты "
    "пиши словами (например «двадцать процентов», а не «20%»).\n"
    "ОТВЕЧАЙ ТОЛЬКО НА ТО, О ЧЁМ СПРОСИЛИ, И ОСТАНАВЛИВАЙСЯ СРАЗУ ПОСЛЕ ОТВЕТА. Не добавляй "
    "дополнительные факты, оговорки, примеры или «кстати» — то, что не спрашивали, не говори.\n"
    "НИКОГДА НЕ ПРИДУМЫВАЙ факты, цифры, даты, проценты, статистику или источники, в которых не "
    "уверен. Если не знаешь точного ответа или не можешь его проверить — так и скажи прямо, а не "
    "выдавай догадку за факт.\n"
    "Отвечай вежливо, кратко и по существу, без вступлений и извинений. Если команда неоднозначна "
    "— уточни коротко, что нужно сделать."
)


def detect_lan_ip() -> str:
    """Best-effort LAN IP of this machine, for display (e.g. a QR code) so a
    phone on the same network knows what address to open. Uses the standard
    UDP-connect trick: no packet is actually sent, it just asks the OS which
    local interface would route to that address."""
    import socket

    # Deferred import, like `socket` above: core/logger.py itself imports
    # `settings` from this module, so a module-level import here would be
    # circular — safe as a local import since by call time both modules are
    # already fully loaded.
    from core.logger import get_logger

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError as no_route_available:
        get_logger(__name__).debug("Could not detect LAN IP, falling back to loopback: %s", no_route_available, exc_info=True)
        return "127.0.0.1"
    finally:
        sock.close()