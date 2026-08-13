from __future__ import annotations

import re
from dataclasses import dataclass

from core.voice.phrase_matching import fuzzy_matches_any

# Minimal rule-based intent parser. It only exists to close the voice loop
# (wake word -> speech -> command -> response) end to end. Real natural
# language understanding belongs in a dedicated future module.


@dataclass(frozen=True)
class Command:
    name: str
    params: dict[str, str]


# Each Russian verb here is listed in several conjugated forms, not just
# the imperative ("открой") a user would actually say: Whisper routinely
# drifts a short imperative verb to a different, similar-sounding
# conjugation of the same verb ("открой" -> "открою"/"откроем", "включи" ->
# "включим") even on otherwise-clean audio — a measured, reproducible
# failure mode, not a hypothetical one. Because these patterns are anchored
# at the very start of the utterance (`^`) and require an exact literal
# match there, that drift alone made the whole pattern fail to match at
# all, so the command silently fell through to free-text AI classification
# and usually came back "не поняла команду". Listing the real variants
# directly (rather than loosening the anchor or switching to fuzzy
# matching, which would also start swallowing unrelated sentences that
# happen to begin with a similar word) keeps the match exact while covering
# the STT noise that's actually been observed.
_OPEN_APP_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:открой|открою|откроем|открывай|запусти|запущу|запустим|запускай)\s+(.+)$"),
    "uk": re.compile(r"^(?:відкрий|відкрию|відкриємо|запусти|запущу|запустимо)\s+(.+)$"),
    "en": re.compile(r"^open\s+(.+)$"),
}

# Checked before _OPEN_APP_PATTERNS in interpret() — distinct verbs, so
# there's no overlap risk, but locality-of-check matters once several
# prefix-verb patterns exist in the same function.
#
# "заверши" ("finish"/"wrap up") is deliberately NOT included as a trigger
# verb here despite being a plausible synonym for "close an app": it's also
# how a formal shutdown request reads ("заверши работу компьютера"), and
# since that phrasing doesn't fuzzy-match _SHUTDOWN_PHRASES closely enough
# to be caught there first, it used to fall through to here and get
# misread as "close an app literally named 'работу компьютера'". "закрой"/
# "выйди из" are unambiguous, so they're kept.
_CLOSE_APP_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:закрой|закрою|закроем|закрывай|выйди из)\s+(.+)$"),
    "uk": re.compile(r"^(?:закрий|закрию|закриємо|вийди з)\s+(.+)$"),
    "en": re.compile(r"^(?:close|quit|exit)\s+(.+)$"),
}

# Checked before _OPEN_APP_PATTERNS (see interpret()) since "открой видео"
# would otherwise match the generic open-app pattern first. _MEDIA_VERB_PATTERNS
# only pins down the verb; the media-kind noun itself is then searched for
# anywhere in what follows (see _MEDIA_KIND_PATTERNS below) rather than
# required immediately after the verb — a real-world phrasing like "запусти
# мне песню" or "запусти любую песню" has a filler word in between, and
# requiring strict adjacency made those fall through to _OPEN_APP_PATTERNS
# instead, which then tried to open "мне песню" as if it were an application
# name. Whatever comes after the matched kind word is the specific
# title/topic ("видео с котиками") and skips the mood question entirely
# (see core/voice/pipeline.py._resolve_media_target); a bare "включи
# музыку"/"открой видео" with nothing else (or only filler before the kind
# word) triggers it.
_MEDIA_VERB_PATTERNS: dict[str, re.Pattern[str]] = {
    # See _OPEN_APP_PATTERNS above for why each verb is listed in several
    # conjugated forms, not just the imperative.
    "ru": re.compile(
        r"^(?:включи|включим|включай|открой|открою|откроем|открывай|"
        r"запусти|запущу|запустим|запускай|поставь|поставим|ставь)\s+(.+)$"
    ),
    "uk": re.compile(
        r"^(?:увімкни|увімкнемо|відкрий|відкрию|відкриємо|запусти|запущу|запустимо|постав|поставимо)\s+(.+)$"
    ),
    "en": re.compile(r"^(?:play|open)\s+(.+)$"),
}

_MEDIA_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"\b(музыку|песню|видео|фильм)\b"),
    "uk": re.compile(r"\b(музику|пісню|відео|фільм)\b"),
    "en": re.compile(r"\b(music|a song|video|a movie)\b"),
}

# Checked before _MEDIA_PATTERNS/_OPEN_APP_PATTERNS for the same reason:
# these verb phrases don't overlap with either, but locality-of-check
# matters more than overlap risk once there are several prefix-verb
# patterns in the same function. The captured group is raw free text —
# actual date/title extraction happens via AI (see
# modules/calendar/extraction.py), not here; a rule-based parser can't
# reliably turn "в пятницу" or "через час" into a real date.
_SCHEDULE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:запиши в планировщик|добавь в планировщик|поставь напоминание|напомни мне)\s*(.*)$"),
    "uk": re.compile(
        r"^(?:запиши в планувальник|додай в планувальник|постав нагадування|нагадай мені)\s*(.*)$"
    ),
    "en": re.compile(r"^(?:add to (?:the )?planner|schedule a reminder|remind me)\s*(.*)$"),
}

# Checked before _OPEN_APP_PATTERNS (see interpret()) — only unambiguous
# verbs go here. Deliberately does NOT include "открой"/"open": that's
# _OPEN_APP_PATTERNS' own trigger, and a compound instruction like "открой
# консоль и напиши X" needs to keep matching that (launching an app), not
# get swallowed here. Utterances that genuinely mean a UI action but start
# with "открой" (or any other ambiguous phrasing) simply don't match this
# regex at all and fall through to the AI classifier instead (see
# modules/ui_automation/handlers.py's registered "ui_action" command,
# which is what makes that fallback path work) — this is a deliberate,
# tested trade-off (see tests/core/voice/test_intent.py), not an oversight.
# The captured group is raw free text, same reasoning as _SCHEDULE_PATTERNS:
# a rule-based parser can't itself figure out which on-screen element
# "тренды" refers to — that's modules/ui_automation/grounding.py's job.
_UI_ACTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:нажми|нажать|кликни|клацни|тапни|напечатай|напиши|введи)\s+(?:на\s+)?(.+)$"),
    "uk": re.compile(r"^(?:натисни|клацни|надрукуй|введи)\s+(?:на\s+)?(.+)$"),
    "en": re.compile(r"^(?:click|tap|type|press)\s+(?:on\s+)?(.+)$"),
}

# Checked in interpret() alongside the other trigger blocks. "ответь"/
# "отложи" resolve against modules/messaging's pending-message state (see
# core/voice/pipeline.py._resolve_messaging_reply/_resolve_messaging_snooze),
# which is why the captured groups here are just raw free text — which
# pending message is meant, what to actually say, and how long to snooze
# are all figured out later, not by this regex.
_MESSAGING_REPLY_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:ответь|ответить)\s*(.*)$"),
    "uk": re.compile(r"^(?:відповідай|відповісти)\s*(.*)$"),
    "en": re.compile(r"^reply\s*(.*)$"),
}

_MESSAGING_SNOOZE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:отложи|отложить)\s*(.*)$"),
    "uk": re.compile(r"^(?:відклади|відкласти)\s*(.*)$"),
    "en": re.compile(r"^(?:snooze|postpone)\s*(.*)$"),
}

# Deliberately literal: the captured text is stored as-is as the source
# identifier (a Telegram @username/phone), not resolved via AI against a
# spoken display name — see modules/messaging/service_layer.py's
# _normalize_identifier and the module's own design notes on why.
_MESSAGING_WATCH_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:следи за|отслеживай)\s+(.+)$"),
    "uk": re.compile(r"^(?:стеж за|відстежуй)\s+(.+)$"),
    "en": re.compile(r"^(?:watch|track)\s+(.+)$"),
}

_MEDIA_KIND_BY_WORD: dict[str, str] = {
    "музыку": "music", "песню": "music", "музику": "music", "пісню": "music",
    "music": "music", "a song": "music",
    "видео": "video", "фильм": "video", "відео": "video", "фільм": "video",
    "video": "video", "a movie": "video",
}

# Each entry pairs a distinct VERB ROOT with "компьютер" — fuzzy_matches_any
# already tolerates a shorter/informal noun in what's actually said ("комп",
# "пк") against the "компьютер" stored here (they overlap enough character-
# for-character to clear the similarity threshold), but it can't bridge two
# lexically unrelated verb roots that just happen to be synonyms ("выруби"
# vs "выключи" share almost no characters despite meaning the same thing) -
# those need their own entry. Regression: "выруби комп"/"вырубай комп" (an
# everyday colloquial way to say this) used to match nothing at all here,
# so the utterance fell through to free-text AI classification instead of
# ever reaching the dispatcher's real confirmation flow.
_SHUTDOWN_PHRASES: dict[str, set[str]] = {
    "ru": {
        "выключи компьютер", "выключи пк", "выключи систему",
        "выруби компьютер", "вырубай компьютер",
        "отруби компьютер", "отрубай компьютер",
    },
    "uk": {"вимкни комп'ютер", "вимкни пк", "вируби комп'ютер"},
    "en": {"shut down", "shutdown", "shut down the computer", "turn off the computer"},
}

_RESTART_PHRASES: dict[str, set[str]] = {
    "ru": {
        "перезагрузи компьютер", "перезагрузи пк", "перезапусти компьютер",
        "ребутни компьютер",
    },
    "uk": {"перезавантаж комп'ютер", "перезавантаж пк"},
    "en": {"restart", "restart the computer", "reboot"},
}

_SHOW_WINDOW_PHRASES: dict[str, set[str]] = {
    "ru": {"покажи окно", "разверни окно", "открой интерфейс"},
    "uk": {"покажи вікно", "розгорни вікно", "відкрий інтерфейс"},
    "en": {"show window", "show the window", "expand window"},
}

_HIDE_WINDOW_PHRASES: dict[str, set[str]] = {
    "ru": {"скрой окно", "сверни окно", "спрячь окно"},
    "uk": {"сховай вікно", "згорни вікно"},
    "en": {"hide window", "hide the window", "minimize window"},
}

_CAPABILITIES_PHRASES: dict[str, set[str]] = {
    "ru": {
        "что ты умеешь", "что ты умеешь делать", "что ты можешь", "что умеешь",
        "какие у тебя команды", "расскажи что ты умеешь", "помощь",
    },
    "uk": {"що ти вмієш", "що ти можеш", "які в тебе команди", "допомога"},
    "en": {"what can you do", "what do you know how to do", "help", "list your commands"},
}

# Rule-only (see interpret() below) — deliberately not routed through the
# AI classifier fallback the way most free-text commands are, since
# modules.board_games has no dispatcher-registered command for the
# classifier to offer as a candidate in the first place (there's nothing
# for it to *dispatch*: the whole game runs synchronously inside
# core/voice/pipeline.py::_resolve_board_game itself, called directly from
# interpret()'s match, same shape as _resolve_messaging_reply's "handles
# everything itself, never hands a Command to the generic dispatch call"
# pattern). A phrasing that doesn't match one of these variants just won't
# start a game — a known first-slice limitation, not an oversight.
_BOARD_GAME_PHRASES: dict[str, set[str]] = {
    "ru": {
        "давай сыграем партию", "давай сыграем", "сыграем партию", "сыграем",
        "хочу поиграть", "хочу сыграть", "давай поиграем",
        "сыграем в шахматы", "давай сыграем в шахматы", "хочу сыграть в шахматы",
        "сыграем в шашки", "давай сыграем в шашки", "хочу сыграть в шашки",
    },
    "uk": {
        "давай зіграємо партію", "давай зіграємо", "зіграємо партію", "зіграємо",
        "хочу пограти", "хочу зіграти",
        "зіграємо в шахи", "зіграємо в шашки",
    },
    "en": {
        "let's play a game", "let's play chess", "let's play checkers",
        "i want to play chess", "i want to play checkers",
    },
}

# Checked against the same normalized text _BOARD_GAME_PHRASES matched —
# whichever marker (if any) appears literally in the utterance decides
# which game without a second question ("сыграем в шахматы" starts chess
# immediately); absent, core/voice/pipeline.py's resolver asks which game
# as its own first voice exchange.
_BOARD_GAME_KIND_MARKERS: dict[str, dict[str, str]] = {
    "ru": {"шахматы": "chess", "шашки": "checkers"},
    "uk": {"шахи": "chess", "шашки": "checkers"},
    "en": {"chess": "chess", "checkers": "checkers"},
}

AFFIRMATIVE_PHRASES: dict[str, set[str]] = {
    "ru": {"да", "подтверждаю", "согласен", "выполняй"},
    "uk": {"так", "підтверджую", "згоден", "виконуй"},
    "en": {"yes", "confirm", "confirmed", "do it", "go ahead"},
}

# Deliberately short, single-word-ish phrases: barge-in (see
# core/voice/barge_in.py) transcribes a ~1.2s rolling window while the
# assistant is still talking, so anything longer than a couple of words
# risks being split across two windows and never matching whole.
STOP_PHRASES: dict[str, set[str]] = {
    "ru": {"стоп", "стой", "хватит", "тихо", "замолчи", "остановись", "отмена"},
    "uk": {"стоп", "досить", "тихо", "мовчи", "зупинись"},
    "en": {"stop", "quiet", "silence", "cancel", "stop it"},
}


def is_stop_command(text: str, language: str) -> bool:
    """Fuzzy, not exact set membership — same reasoning as is_affirmative
    below. This used to be the one holdout still doing a byte-for-byte
    comparison of the *entire* normalized utterance against STOP_PHRASES,
    which meant barge-in (see core/voice/barge_in.py's 1.2s rolling window)
    failed to recognize the stop word whenever the window also captured so
    much as one extra stray word alongside it (background noise, the tail
    of the assistant's own speech bleeding into the mic, ...) - a single
    word buried in a two-word transcription could never equal a one-word
    set member."""
    normalized = _normalize(text)
    if not normalized:
        return False
    return fuzzy_matches_any(normalized, STOP_PHRASES.get(language, set()))


# Distinct from STOP_PHRASES/is_stop_command: "сдаюсь" mid-game (see
# core/voice/pipeline.py::_resolve_board_game) means "end this chess/
# draughts game as a loss," not "stop talking" — conflating the two would
# make an ordinary "стоп" during a game ambiguous between "pause" and
# "resign," when the player almost always means the former.
RESIGN_PHRASES: dict[str, set[str]] = {
    "ru": {"сдаюсь", "я сдаюсь", "сдаться", "хочу сдаться"},
    "uk": {"здаюся", "я здаюся", "здатися"},
    "en": {"i resign", "i give up", "resign"},
}


def is_resign_command(text: str, language: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    return fuzzy_matches_any(normalized, RESIGN_PHRASES.get(language, set()))


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s']", "", text, flags=re.UNICODE).strip().lower()


def interpret(text: str, language: str) -> Command | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    # Fuzzy, not exact set membership: dangerous commands still require a
    # separate spoken confirmation afterward (see is_affirmative below and
    # core/dispatcher.py's CONFIRMATION_REQUIRED flow), so being lenient
    # about recognizing the *intent* to shut down/restart here doesn't skip
    # that safety gate — it just means a phrasing that isn't a byte-for-byte
    # match against the fixed set ("выключи ноутбук" vs the exact phrase
    # "выключи компьютер") still gets a chance to ask for confirmation
    # instead of falling through to be misread as something else entirely.
    if fuzzy_matches_any(normalized, _SHUTDOWN_PHRASES.get(language, set())):
        return Command(name="shutdown", params={})

    if fuzzy_matches_any(normalized, _RESTART_PHRASES.get(language, set())):
        return Command(name="restart", params={})

    if normalized in _SHOW_WINDOW_PHRASES.get(language, set()):
        return Command(name="show_window", params={})

    if normalized in _HIDE_WINDOW_PHRASES.get(language, set()):
        return Command(name="hide_window", params={})

    if normalized in _CAPABILITIES_PHRASES.get(language, set()):
        return Command(name="list_capabilities", params={"language": language})

    if fuzzy_matches_any(normalized, _BOARD_GAME_PHRASES.get(language, set())):
        kind = ""
        for marker, game in _BOARD_GAME_KIND_MARKERS.get(language, {}).items():
            if marker in normalized:
                kind = game
                break
        return Command(name="start_board_game", params={"game": kind})

    schedule_pattern = _SCHEDULE_PATTERNS.get(language)
    if schedule_pattern:
        schedule_match = schedule_pattern.match(normalized)
        if schedule_match:
            return Command(name="schedule_event", params={"raw_text": schedule_match.group(1).strip()})

    media_verb_pattern = _MEDIA_VERB_PATTERNS.get(language)
    media_kind_pattern = _MEDIA_KIND_PATTERNS.get(language)
    if media_verb_pattern and media_kind_pattern:
        verb_match = media_verb_pattern.match(normalized)
        if verb_match:
            remainder = verb_match.group(1)
            kind_match = media_kind_pattern.search(remainder)
            if kind_match:
                kind = _MEDIA_KIND_BY_WORD.get(kind_match.group(1), "video")
                query = remainder[kind_match.end():].strip()
                return Command(name="open_media", params={"kind": kind, "query": query})

    close_pattern = _CLOSE_APP_PATTERNS.get(language)
    if close_pattern:
        close_match = close_pattern.match(normalized)
        if close_match:
            return Command(name="close_app", params={"target": close_match.group(1).strip()})

    ui_action_pattern = _UI_ACTION_PATTERNS.get(language)
    if ui_action_pattern:
        ui_action_match = ui_action_pattern.match(normalized)
        if ui_action_match:
            return Command(name="ui_action", params={"raw_text": ui_action_match.group(1).strip()})

    reply_pattern = _MESSAGING_REPLY_PATTERNS.get(language)
    if reply_pattern:
        reply_match = reply_pattern.match(normalized)
        if reply_match:
            return Command(name="messaging_reply", params={"raw_target": reply_match.group(1).strip()})

    snooze_pattern = _MESSAGING_SNOOZE_PATTERNS.get(language)
    if snooze_pattern:
        snooze_match = snooze_pattern.match(normalized)
        if snooze_match:
            return Command(name="messaging_snooze", params={"raw_text": snooze_match.group(1).strip()})

    watch_pattern = _MESSAGING_WATCH_PATTERNS.get(language)
    if watch_pattern:
        watch_match = watch_pattern.match(normalized)
        if watch_match:
            return Command(
                name="messaging_watch_contact", params={"raw_text": watch_match.group(1).strip()}
            )

    pattern = _OPEN_APP_PATTERNS.get(language)
    if pattern:
        match = pattern.match(normalized)
        if match:
            return Command(name="open_app", params={"target": match.group(1).strip()})

    return None


def is_affirmative(text: str, language: str) -> bool:
    """Fuzzy, not exact set membership — this gates real actions
    (dangerous-command confirmation, "did you mean X?" resolution), so a
    confirmation shouldn't silently fail just because the user said "да,
    давай" or "ну да" instead of a byte-for-byte "да". Known trade-off: an
    idiom where an affirmative word doesn't mean agreement ("да ладно" as
    disbelief, not "yes") could misfire — accepted because the reported,
    everyday failure mode was the opposite (a clear yes not being
    recognized), not a false confirmation."""
    normalized = _normalize(text)
    if not normalized:
        return False
    return fuzzy_matches_any(normalized, AFFIRMATIVE_PHRASES.get(language, set()))
