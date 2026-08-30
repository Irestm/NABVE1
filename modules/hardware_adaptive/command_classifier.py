from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

from core.logger import get_logger
from core.voice.intent import Command
from modules.ai_bridge.semantic_matcher import SemanticMatcher
from modules.ai_bridge import semantic_matcher

logger = get_logger(__name__)

# Multilingual (not the smaller English-only all-MiniLM-L6-v2) since real
# usage is Russian/Ukrainian/English voice commands — see this module's
# design note in the task spec. CPU-only, ~470MB, downloaded from
# HuggingFace on first use and cached under ~/.cache/torch/sentence_transformers
# after that (no network needed on subsequent runs).
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Empirically tuned (measured against real utterances, not picked in the
# abstract — see the task's testing notes): 0.75, the spec's suggested
# starting point, was NOT safe in practice. Ordinary small talk with no
# command intent at all ("что ты умеешь", "спасибо", "привет", "найди
# рецепт борща") scored 0.68-0.83 against this multilingual model's
# nearest catalog phrase — often above 0.75, occasionally above 0.80 —
# because short generic Russian/Ukrainian sentences cluster close together
# in this embedding space regardless of actual meaning. That matters most
# for the commands that execute immediately with no spoken confirmation
# (change_volume, mute, minimize_window, ...): a false positive there
# silently does something the user never asked for, not just a wrong
# answer. 0.80 was the lowest value with no observed false positive among
# tested small-talk/off-topic phrases while still catching real command
# phrasings. This intentionally trades away some recall on longer,
# parameter-heavy utterances (e.g. "удали содержимое <path>" sometimes
# falls just short) — an utterance that doesn't clear the bar simply falls
# through to the normal interpret() -> plugin match -> AI classifier
# pipeline, so a miss here is a slower resolution, never a broken one.
# delete_folder/change_system_locale (core/dispatcher.py's dangerous=True
# commands) also keep their spoken re-confirmation regardless of this
# threshold, so a rare false positive there prompts and can be declined
# rather than silently executing.
_SIMILARITY_THRESHOLD = 0.80


@dataclass(frozen=True)
class _CommandSpec:
    command: str
    phrases: tuple[str, ...]


# Mixed-language example phrases per command — the multilingual model embeds
# all of them into one shared space, so a Russian utterance can still match
# best against an English exemplar and vice versa; language separation here
# is just for readability, not required for matching. Deliberately phrased
# WITHOUT specific numbers/paths baked in where possible: the embedding only
# needs to recognize the *intent*, actual parameters (percent, path, target
# language, ...) are pulled from the real utterance afterward by
# _PARAM_EXTRACTORS below, never from whichever exemplar matched.
_CATALOG: tuple[_CommandSpec, ...] = (
    _CommandSpec("set_volume", (
        "поставь громкость 50 процентов", "громкость на 50", "установи громкость на 30 процентов",
        "сделай громкость 70 процентов", "выставь громкость 20",
        "постав гучність на 50 відсотків", "встанови гучність 40",
        "set the volume to 50 percent", "set volume to 30",
    )),
    _CommandSpec("change_volume", (
        "убавь громкость на 20 процентов", "сделай тише на 20", "прибавь громкость на 10",
        "сделай погромче", "сделай потише", "увеличь громкость", "уменьши громкость", "громче",
        "тише сделай", "зменш гучність на 20", "збільш гучність", "зроби тихіше", "зроби гучніше",
        "turn the volume down by 20", "turn it up a bit", "make it quieter", "make it louder",
    )),
    _CommandSpec("get_volume", (
        "какая сейчас громкость", "сколько сейчас громкости", "какой уровень громкости стоит",
        "яка зараз гучність", "what's the volume level", "what is the current volume",
    )),
    _CommandSpec("set_brightness", (
        "поставь яркость 50 процентов", "яркость на 50", "установи яркость на 30 процентов",
        "сделай яркость 70 процентов", "выставь яркость экрана 20",
        "постав яскравість на 50 відсотків", "встанови яскравість екрана 40",
        "set the screen brightness to 50 percent", "set brightness to 30",
    )),
    _CommandSpec("change_brightness", (
        "убавь яркость на 20 процентов", "сделай ярче на 20", "прибавь яркость на 10",
        "сделай экран ярче", "сделай экран темнее", "сделай поярче", "сделай потемнее",
        "увеличь яркость", "уменьши яркость", "ярче", "темнее сделай",
        "зменш яскравість на 20", "збільш яскравість", "зроби темніше", "зроби яскравіше",
        "turn the brightness down by 20", "make the screen brighter", "make it dimmer", "dim the screen",
    )),
    _CommandSpec("get_brightness", (
        "какая сейчас яркость", "какой уровень яркости стоит", "насколько яркий экран сейчас",
        "яка зараз яскравість", "what's the screen brightness", "what is the current brightness",
    )),
    _CommandSpec("mute", (
        "выключи звук", "заглуши звук", "убери звук совсем", "отключи звук",
        "вимкни звук зовсім", "mute the sound", "mute the audio",
    )),
    _CommandSpec("unmute", (
        "включи звук обратно", "верни звук", "убери отключение звука", "включи звук снова",
        "увімкни звук назад", "unmute the sound", "unmute the audio",
    )),
    _CommandSpec("toggle_mute", (
        "включи или выключи звук", "переключи звук", "перемкни звук", "toggle mute", "toggle the sound",
    )),
    _CommandSpec("minimize_window", (
        "сверни окно", "сверни это окно", "минимизируй окно", "сверни приложение", "скрой окно программы",
        "згорни вікно", "згорни це вікно", "minimize the window", "minimize this window",
    )),
    _CommandSpec("close_os_window", (
        "закрой это окно", "закрой активное окно", "закрой окно приложения", "закрой текущее окно",
        "закрий це вікно", "закрий активне вікно",
        "close this window", "close the active window", "close the current window",
    )),
    _CommandSpec("close_browser_tab", (
        "закрой вкладку", "закрой эту вкладку в браузере", "закрой вкладку в браузере", "закрой текущую вкладку",
        "закрий вкладку", "закрий цю вкладку",
        "close the tab", "close this browser tab", "close the current tab",
    )),
    _CommandSpec("create_folder", (
        # Plain phrasing (no path) so a bare "создай папку" alone still
        # matches, PLUS phrasing WITH a realistic path — real utterances
        # always include one, and a short generic exemplar alone embeds too
        # far from "verb + real filesystem path" for cosine similarity to
        # clear the threshold reliably (measured empirically).
        "создай папку", "создай новую папку", "сделай папку по этому пути", "сделай новую папку тут",
        "создай папку /home/user/documents", "создай папку C:\\Users\\user\\Documents\\project",
        "створи папку", "створи нову папку", "створи папку /home/user/projects",
        "create a folder", "create a new folder", "make a new folder", "create a folder /home/user/notes",
    )),
    _CommandSpec("move_folder", (
        "перемести папку в другое место", "перемести файл в папку", "перенеси папку в",
        "перемести /home/user/downloads/file.txt в /home/user/documents",
        "перемісти папку в", "перенеси файл до папки", "перемісти /home/user/old в /home/user/archive",
        "move the folder to", "move this file into another folder", "move /home/user/a to /home/user/b",
    )),
    _CommandSpec("delete_folder", (
        "удали папку", "удали содержимое папки", "удали эту папку совсем", "сотри папку", "удали папку навсегда",
        "удали папку /home/user/downloads/old", "удали папку C:\\Users\\user\\Downloads\\old",
        "видали папку", "видали вміст папки", "видали папку /home/user/temp",
        "delete the folder", "delete this folder completely", "permanently delete this folder",
        "delete the folder /home/user/temp",
    )),
    _CommandSpec("switch_keyboard_layout", (
        "смени раскладку клавиатуры", "переключи раскладку на английскую", "поставь русскую раскладку",
        "переключи раскладку клавиатуры", "поставь украинскую раскладку",
        "зміни розкладку клавіатури", "перемкни розкладку на англійську",
        "switch the keyboard layout", "change keyboard layout to english",
    )),
    _CommandSpec("change_system_locale", (
        "смени язык системы", "поменяй системный язык на английский", "измени язык операционной системы",
        "поставь другой язык системы",
        "зміни мову системи", "поміняй системну мову на англійську",
        "change the system language", "change system locale to english",
    )),
    _CommandSpec("get_battery_status", (
        "сколько заряда осталось", "сколько батареи", "какой заряд батареи", "сколько процентов заряда",
        "скільки заряду батареї", "скільки відсотків батареї",
        "how much battery is left", "what's the battery percentage", "how much charge is left",
    )),
    _CommandSpec("check_system_updates", (
        "проверь обновления", "есть ли обновления системы", "проверь обновления системы",
        "узнай, есть ли обновления",
        "перевір оновлення", "чи є оновлення системи",
        "check for system updates", "are there any updates available",
    )),
    _CommandSpec("lock_screen", (
        "заблокируй экран", "заблокируй компьютер", "заблокируй систему", "залочь экран",
        "поставь блокировку экрана", "заблокуй екран", "заблокуй комп'ютер",
        "lock the screen", "lock the computer", "lock my pc",
    )),
    # Found missing entirely (no rule-based regex either) while auditing
    # every button in core/command_ui_metadata.py's "Системные команды"
    # panel for voice coverage - unlike the commands above, these had no
    # fast path of any kind and depended wholly on the AI classifier chain,
    # which is slower and (before this same audit's other fix) could
    # hallucinate a fake "done" for a command that was never dispatched.
    _CommandSpec("toggle_timer", (
        "поставь таймер на 10 минут", "поставь таймер на 5 минут", "засеки 15 минут",
        "поставь таймер на полчаса", "включи таймер на 20 минут", "отмени таймер", "останови таймер",
        "убери таймер", "выключи таймер",
        "постав таймер на 10 хвилин", "постав таймер на 5 хвилин", "скасуй таймер", "зупини таймер",
        "set a timer for 10 minutes", "set a timer for 5 minutes", "cancel the timer", "stop the timer",
    )),
    _CommandSpec("toggle_stopwatch", (
        "запусти секундомер", "включи секундомер", "останови секундомер", "выключи секундомер",
        "старт секундомера", "стоп секундомер",
        "запусти секундомір", "увімкни секундомір", "зупини секундомір", "вимкни секундомір",
        "start the stopwatch", "stop the stopwatch", "start stopwatch", "stop stopwatch",
    )),
)


_NUMBER_RE = re.compile(r"-?\d+")


def _extract_set_volume(text: str) -> dict[str, str] | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    percent = max(0, min(100, int(match.group(0))))
    return {"percent": str(percent)}


_INCREASE_WORDS = (
    "прибав", "увелич", "погромче", "громче", "добавь", "додай",
    "збільш", "гучніше", "louder", "increase", "raise",
)
_DECREASE_WORDS = (
    "убав", "уменьш", "потише", "тише", "зменш", "тихіше",
    "quieter", "decrease", "lower",
)
_DEFAULT_VOLUME_STEP = 10


def _extract_change_volume(text: str) -> dict[str, str]:
    normalized = text.lower()
    number_match = _NUMBER_RE.search(normalized)
    if number_match:
        magnitude = abs(int(number_match.group(0)))
        explicit_negative = number_match.group(0).startswith("-")
    else:
        magnitude = _DEFAULT_VOLUME_STEP
        explicit_negative = False

    if any(word in normalized for word in _DECREASE_WORDS) or explicit_negative:
        sign = -1
    else:
        # Covers both an explicit increase word and the "just a number, no
        # clear direction word" case (e.g. a mis-transcribed verb) — a bare
        # "громкость 20" is treated as set_volume by the embedding match
        # anyway, so change_volume only ever gets picked when SOME direction
        # is implied; defaulting the ambiguous remainder to "up" is safer
        # than silently doing nothing.
        sign = 1
    return {"delta_percent": str(sign * magnitude)}


def _extract_set_brightness(text: str) -> dict[str, str] | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    percent = max(0, min(100, int(match.group(0))))
    return {"percent": str(percent)}


_BRIGHTEN_WORDS = (
    "прибав", "увелич", "ярче", "яскравіше", "світліше", "додай", "збільш",
    "brighter", "brighten", "increase", "raise",
)
_DIM_WORDS = (
    "убав", "уменьш", "темнее", "потемнее", "тусклее", "приглуши", "зменш",
    "темніше", "знизь", "dimmer", "darker", "decrease", "lower", "dim",
)
_DEFAULT_BRIGHTNESS_STEP = 10


def _extract_change_brightness(text: str) -> dict[str, str]:
    normalized = text.lower()
    number_match = _NUMBER_RE.search(normalized)
    if number_match:
        magnitude = abs(int(number_match.group(0)))
        explicit_negative = number_match.group(0).startswith("-")
    else:
        magnitude = _DEFAULT_BRIGHTNESS_STEP
        explicit_negative = False

    if any(word in normalized for word in _DIM_WORDS) or explicit_negative:
        sign = -1
    else:
        sign = 1
    return {"delta_percent": str(sign * magnitude)}


def _no_params(_text: str) -> dict[str, str]:
    return {}


_WINDOW_FILLER_WORDS = {
    "окно", "это окно", "текущее окно", "активное окно", "приложения", "программы",
    "вікно", "це вікно", "поточне вікно", "активне вікно",
    "window", "this window", "the window", "the active window", "the current window",
}

_MINIMIZE_APP_RE = re.compile(
    r"^(?:сверни|минимизируй|скрой|згорни|мінімізуй|minimize|hide)\s+"
    r"(?:окно\s+|вікно\s+|the\s+window\s+of\s+)?(.+)$",
    re.IGNORECASE,
)
_CLOSE_WINDOW_APP_RE = re.compile(
    r"^(?:закрой|закрий|close)\s+(?:окно\s+|вікно\s+|the\s+window\s+of\s+)?(.+)$",
    re.IGNORECASE,
)


def _extract_window_app_name(pattern: re.Pattern[str], text: str) -> dict[str, str]:
    match = pattern.match(text.strip())
    if not match:
        return {}
    candidate = match.group(1).strip()
    if not candidate or candidate.lower() in _WINDOW_FILLER_WORDS:
        # Bare "сверни окно"/"close this window" with no real app name —
        # app_name stays unset, so the dispatcher handler falls back to the
        # currently active window (see core/dispatcher.py's
        # _handle_minimize_window/_handle_close_os_window).
        return {}
    return {"app_name": candidate}


def _extract_minimize_window(text: str) -> dict[str, str]:
    return _extract_window_app_name(_MINIMIZE_APP_RE, text)


def _extract_close_os_window(text: str) -> dict[str, str]:
    return _extract_window_app_name(_CLOSE_WINDOW_APP_RE, text)


def _first_match(patterns: tuple[re.Pattern[str], ...], text: str) -> re.Match[str] | None:
    stripped = text.strip()
    for pattern in patterns:
        match = pattern.match(stripped)
        if match:
            return match
    return None


_CREATE_FOLDER_PATTERNS = (
    re.compile(r"^созда(?:й|ть)\s+(?:новую\s+)?папку\s+(.+)$", re.IGNORECASE),
    re.compile(r"^створ(?:и|ити)\s+(?:нову\s+)?папку\s+(.+)$", re.IGNORECASE),
    re.compile(r"^create\s+(?:a\s+)?(?:new\s+)?folder\s+(.+)$", re.IGNORECASE),
)


def _extract_create_folder(text: str) -> dict[str, str] | None:
    match = _first_match(_CREATE_FOLDER_PATTERNS, text)
    if not match:
        return None
    path = match.group(1).strip().strip("\"'")
    return {"path": path} if path else None


_DELETE_FOLDER_PATTERNS = (
    re.compile(r"^удал(?:и|ить)\s+(?:содержимое\s+)?папк[уи]\s+(.+)$", re.IGNORECASE),
    re.compile(r"^сотри\s+папку\s+(.+)$", re.IGNORECASE),
    re.compile(r"^видал(?:и|ити)\s+(?:вміст\s+)?папку\s+(.+)$", re.IGNORECASE),
    re.compile(r"^delete\s+(?:the\s+)?folder\s+(.+)$", re.IGNORECASE),
)


def _extract_delete_folder(text: str) -> dict[str, str] | None:
    match = _first_match(_DELETE_FOLDER_PATTERNS, text)
    if not match:
        return None
    path = match.group(1).strip().strip("\"'")
    return {"path": path} if path else None


_MOVE_FOLDER_PATTERNS = (
    re.compile(r"^перемест(?:и|ить)\s+(.+?)\s+в\s+(.+)$", re.IGNORECASE),
    re.compile(r"^перенес(?:и|ти)\s+(.+?)\s+в\s+(.+)$", re.IGNORECASE),
    re.compile(r"^перемісти(?:ти)?\s+(.+?)\s+(?:в|до)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^move\s+(.+?)\s+(?:to|into)\s+(.+)$", re.IGNORECASE),
)


def _extract_move_folder(text: str) -> dict[str, str] | None:
    match = _first_match(_MOVE_FOLDER_PATTERNS, text)
    if not match:
        return None
    source = match.group(1).strip().strip("\"'")
    destination = match.group(2).strip().strip("\"'")
    if not source or not destination:
        return None
    return {"source": source, "destination": destination}


_LANGUAGE_WORD_MAP: tuple[tuple[str, str], ...] = (
    ("английск", "en"), ("англійськ", "en"), ("english", "en"),
    ("русск", "ru"), ("російськ", "ru"), ("russian", "ru"),
    ("украинск", "uk"), ("українськ", "uk"), ("ukrainian", "uk"),
)


def _extract_language_code(text: str) -> dict[str, str] | None:
    normalized = text.lower()
    for word, code in _LANGUAGE_WORD_MAP:
        if word in normalized:
            return {"language_code": code}
    # No recognizable target language in the utterance — safer to decline
    # the fast path entirely (falls through to the AI classifier) than to
    # guess which language was meant.
    return None


_TIMER_MINUTES_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:минут\w*|мин\b|хвилин\w*|хв\b|min(?:ute)?s?)\b", re.IGNORECASE
)


def _extract_toggle_timer(text: str) -> dict[str, str]:
    # No number found (e.g. "отмени таймер"/"cancel the timer") isn't a
    # failed extraction here - unlike the other extractors that return None
    # to decline the fast path entirely, an empty dict is toggle_timer's own
    # valid "cancel every active timer" call (see
    # modules/timer/handlers.py's _handle_toggle_timer), so it must reach
    # the dispatcher as {} rather than bailing out.
    match = _TIMER_MINUTES_RE.search(text.lower())
    if not match:
        return {}
    return {"minutes": match.group(1).replace(",", ".")}


# Declining to extract (returning None) makes match_system_command() as a
# whole return None for that utterance — the fast path backs off and lets
# the normal interpret() -> plugin match -> AI classifier chain handle it,
# same as if the embedding similarity itself had been too low. A command
# never dispatches with a guessed/missing required parameter.
_PARAM_EXTRACTORS: dict[str, Callable[[str], dict[str, str] | None]] = {
    "set_volume": _extract_set_volume,
    "change_volume": _extract_change_volume,
    "get_volume": _no_params,
    "set_brightness": _extract_set_brightness,
    "change_brightness": _extract_change_brightness,
    "get_brightness": _no_params,
    "mute": _no_params,
    "unmute": _no_params,
    "toggle_mute": _no_params,
    "minimize_window": _extract_minimize_window,
    "close_os_window": _extract_close_os_window,
    "close_browser_tab": _no_params,
    "create_folder": _extract_create_folder,
    "move_folder": _extract_move_folder,
    "delete_folder": _extract_delete_folder,
    "switch_keyboard_layout": _extract_language_code,
    "change_system_locale": _extract_language_code,
    "get_battery_status": _no_params,
    "check_system_updates": _no_params,
    "lock_screen": _no_params,
    "toggle_timer": _extract_toggle_timer,
    "toggle_stopwatch": _no_params,
}


_matcher = SemanticMatcher(model_name=_MODEL_NAME)
_catalog_built = False
_available = False


def _ensure_initialized() -> bool:
    """Builds the shared SemanticMatcher against this module's own catalog,
    once per process. Never raises: any failure (package not installed, no
    internet on first run to fetch the model, ...) just leaves the
    classifier unavailable so callers fall back to the normal interpret() ->
    plugin match -> AI classifier pipeline, same shape as
    modules.hardware_adaptive.local_ai's "never break the caller" contract.
    The model itself is loaded (and cached) by
    modules.ai_bridge.semantic_matcher.get_shared_model — see that module
    for why this no longer loads its own private copy."""
    global _catalog_built, _available
    if _catalog_built:
        return _available

    catalog = {spec.command: spec.phrases for spec in _CATALOG}
    _available = _matcher.build(catalog)
    _catalog_built = True
    if _available:
        phrase_count = sum(len(spec.phrases) for spec in _CATALOG)
        logger.info(
            "Local command classifier ready (%d example phrases across %d commands)",
            phrase_count, len(_CATALOG),
        )
    return _available


def warm_up() -> None:
    """Kicks off model load + embedding precompute on a background thread —
    called once from core/bootstrap.py's compose() so the classifier is
    already warm by the time the first voice command arrives, without
    blocking server startup on the ~1-2s model load. Safe to call more than
    once (or never, if the caller relies on lazy init on first real use
    instead) — _ensure_initialized() is itself idempotent."""
    threading.Thread(target=_ensure_initialized, daemon=True, name="command-classifier-warmup").start()


def match_system_command(text: str) -> Command | None:
    """The fast, fully local first filter for system commands (volume,
    windows, filesystem, language, battery, updates) — tried after the
    rule-based interpret() and plugin-trigger matching, before the utterance
    is ever sent to modules.ai_bridge's intent classifier / any external AI
    provider. Returns None (never raises) whenever it can't confidently
    resolve the utterance, so the caller falls through to the normal AI
    pipeline exactly as if this fast path didn't exist."""
    stripped = text.strip()
    if not stripped:
        return None
    if not _ensure_initialized():
        return None

    match = _matcher.best_match(stripped)
    if match is None:
        return None
    command_name, best_score = match
    if best_score < _SIMILARITY_THRESHOLD:
        logger.info(
            "Local command classifier: no match for %r (closest was '%s', score=%.3f < threshold=%.2f)",
            text, command_name, best_score, _SIMILARITY_THRESHOLD,
        )
        return None

    extractor = _PARAM_EXTRACTORS.get(command_name, _no_params)
    params = extractor(stripped)
    if params is None:
        logger.info(
            "Local command classifier: '%s' scored above threshold (score=%.3f) for %r but its "
            "param extractor declined (missing/unparseable required parameter)",
            command_name, best_score, text,
        )
        return None

    logger.info(
        "Local command classifier matched '%s' (score=%.3f) for utterance: %r",
        command_name, best_score, text,
    )
    return Command(name=command_name, params=params)


def unavailable_reason() -> str | None:
    """Human-readable reason the local classifier isn't available, or None
    if it is. Mainly for status/diagnostics — mirrors
    modules.hardware_adaptive.local_ai.unavailable_reason()."""
    _ensure_initialized()
    return semantic_matcher.unavailable_reason(_MODEL_NAME)
