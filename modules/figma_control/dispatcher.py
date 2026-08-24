from __future__ import annotations

from core.logger import get_logger
from core.voice import gender as gender_module
from modules.figma_control import command_parser, screen_fallback
from modules.figma_control.command_parser import session_state
from modules.figma_control.ws_server import FigmaPluginUnavailableError, figma_ws_server

logger = get_logger(__name__)

# Actions that create or select a layer — after any of these succeeds
# (through either execution path), session_state.last_selected_layer is
# updated so a follow-up command like "сделай его красным" can resolve
# "его" without the user repeating the layer's name (see
# command_parser.py's FigmaSessionState docstring).
_SELECTS_A_LAYER = frozenset({"select_layer", "create_rectangle", "create_text", "create_frame"})


def _update_session_state(action: str, params: dict, plugin_result: dict | None) -> None:
    if action == "delete_layer":
        deleted_name = params.get("layer_name")
        if deleted_name and session_state.last_selected_layer == deleted_name:
            session_state.last_selected_layer = None
        return

    if action not in _SELECTS_A_LAYER:
        return

    # The plugin knows the real Figma-assigned name (e.g. "Rectangle 1" for
    # a freshly created shape); screen_fallback doesn't create through the
    # API so it only ever has whatever layer_name the user already gave.
    name = None
    if plugin_result:
        name = plugin_result.get("name")
    if not name:
        name = params.get("layer_name")
    if name:
        session_state.last_selected_layer = name


async def _try_plugin(action: str, params: dict) -> str | None:
    """Returns the spoken result if the plugin handled `action`, or None if
    the caller should fall back to screen_fallback.py (plugin not
    connected, unreachable, or it replied {"status": "unsupported"})."""
    if not figma_ws_server.is_plugin_connected:
        return None

    try:
        response = await figma_ws_server.send_command(action, params)
    except FigmaPluginUnavailableError as exc:
        logger.info("Figma plugin unavailable mid-command ('%s'), falling back: %s", action, exc)
        return None

    status = response.get("status")
    message = response.get("message") or ""

    if status == "unsupported":
        logger.info("Figma plugin reported '%s' as unsupported, falling back", action)
        return None

    if status == "success":
        _update_session_state(action, params, response.get("result") if isinstance(response.get("result"), dict) else None)
        return message or "Готово."

    # status == "error" (or anything else the plugin might send) is a
    # definitive answer, not a reason to fall back — the plugin DID handle
    # this action, it just failed (e.g. "layer not found"), and
    # screen_fallback has no better chance at succeeding with the same
    # missing information.
    return message or "Не удалось выполнить команду в Figma."


def _try_fallback(action: str, params: dict) -> str:
    try:
        message = screen_fallback.execute(action, params)
    except screen_fallback.FigmaNotFocusedError as exc:
        logger.info("Figma fallback refused: %s", exc)
        return "Не выполняю: активное окно сейчас не Figma."
    except screen_fallback.FallbackActionUnsupportedError as exc:
        logger.info("Figma fallback has no way to do this: %s", exc)
        return "Не могу выполнить эту команду в Figma."
    except RuntimeError as exc:
        # _require_pyautogui/_require_cv2's dependency-missing errors.
        logger.warning("Figma fallback dependency missing: %s", exc)
        return "Не могу выполнить эту команду в Figma: не хватает нужного компонента на компьютере."
    except Exception:
        logger.exception("Figma screen fallback failed for action '%s'", action)
        return "Не удалось выполнить команду в Figma."

    _update_session_state(action, params, None)
    return message


async def process_figma_command(text: str) -> str:
    """Entry point for the whole module (see modules/figma_control/handlers.py,
    which registers this behind the dispatcher, and core/voice/intent.py's
    trigger phrases). Parses the voice text, tries the Figma plugin over
    WebSocket first, and falls back to screen_fallback.py's pyautogui/OCR
    path whenever the plugin isn't connected or can't handle this
    particular action. Always returns Russian text meant to be spoken
    aloud, never raises."""
    parsed = await command_parser.parse_command(text)
    if parsed is None:
        return gender_module.pick("Не понял, что нужно сделать в Figma.", "Не поняла, что нужно сделать в Figma.")

    plugin_message = await _try_plugin(parsed.action, parsed.params)
    if plugin_message is not None:
        return plugin_message

    return _try_fallback(parsed.action, parsed.params)
