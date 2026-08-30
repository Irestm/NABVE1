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

# modules/software_installer. "установи X" is distinct from "поставь X"
# (media/volume/timer), but "установи будильник"/"установи таймер" still
# collide — the marker word ("программу"/"приложение"/"install") group
# forces install intent; without it, interpret() only claims the utterance
# when package_map actually recognizes the name (see the block in
# interpret() below), otherwise it falls through untouched.
_SOFTWARE_INSTALL_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:установи|установить|поставь|инсталлируй|доустанови)\s+(?:мне\s+|нам\s+|себе\s+)?(?P<marker>программу\s+|приложение\s+|прогу\s+)?(?P<app>.+)$"),
    "uk": re.compile(r"^(?:встанови|встановити|інсталюй)\s+(?:мені\s+|нам\s+|собі\s+)?(?P<marker>програму\s+|застосунок\s+|додаток\s+)?(?P<app>.+)$"),
    "en": re.compile(r"^install\s+(?:me\s+)?(?P<marker>the\s+app\s+|app\s+|program\s+|software\s+)?(?P<app>.+)$"),
}

# "нажми далее"/"нажми установить"/"click next" while a third-party
# installer wizard is on screen — routed to installer_click_button.
_INSTALLER_BUTTON_KINDS: dict[str, str] = {
    "далее": "next", "дальше": "next", "продолжить": "next", "next": "next", "continue": "next", "далі": "next",
    "установить": "install", "установи": "install", "инсталлировать": "install", "install": "install", "встановити": "install",
    "готово": "finish", "завершить": "finish", "finish": "finish", "done": "finish", "завершити": "finish",
    "принять": "accept", "согласен": "accept", "принимаю": "accept", "accept": "accept", "agree": "accept", "прийняти": "accept",
}
_INSTALLER_BUTTON_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^нажми(?:\s+кнопку)?\s+(?P<label>[\w'ії-]+)(?:\s+в\s+установщике)?$"),
    "uk": re.compile(r"^натисни(?:\s+кнопку)?\s+(?P<label>[\w'ії-]+)$"),
    "en": re.compile(r"^(?:click|press)\s+(?:the\s+)?(?P<label>[\w-]+)(?:\s+button)?$"),
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

# The captured group is a target name/empty string, same shape as
# _MESSAGING_REPLY_PATTERNS — core/voice/pipeline.py's
# _resolve_edit_pending_message resolves which pending message it means
# (reusing _resolve_pending_message_target) and always asks a follow-up
# "какую инструкцию дать?" itself, so there's no separate captured-
# instruction group here to try to split out.
_TEXT_EDIT_MESSAGE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^отредактируй сообщение\s*(?:от\s+)?(.*)$"),
    "uk": re.compile(r"^відредагуй повідомлення\s*(?:від\s+)?(.*)$"),
    "en": re.compile(r"^edit\s+(?:the\s+)?message\s*(?:from\s+)?(.*)$"),
}

# No captured group — core/voice/pipeline.py's _resolve_analyze_active_editor
# always asks a follow-up "что именно сделать с кодом?" itself, same
# reasoning as _resolve_edit_pending_message above (no rule-based way to
# guess an arbitrary analysis instruction from the bare trigger phrase).
_CODE_ANALYSIS_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:проанализируй код|объясни код|проверь код)$"),
    "uk": re.compile(r"^(?:проаналізуй код|поясни код)$"),
    "en": re.compile(r"^(?:analyze|explain|review)\s+(?:the\s+)?code$"),
}

# Checked before _MEDIA_VERB_PATTERNS/_OPEN_APP_PATTERNS in interpret():
# "включи"/"открой"/"запусти"/"поставь" are also open_media/open_app trigger
# verbs, and "видео" is itself an open_media kind word ("включи видео"
# alone means "play some local video"), so "включи на ютубе X" would
# otherwise get swallowed by the open_media branch (kind="video", losing
# "на ютубе" and the real query) or misread by open_app as an app literally
# named "на ютубе x". Volume/speed deliberately require an explicit
# "видео"/"ютуб" word rather than a bare "громче"/"тише"/"поставь громкость
# N" — those already mean system volume (see
# modules/hardware_adaptive/command_classifier.py, checked later in
# core/voice/pipeline.py's chain, after interpret()), so an unqualified
# match here would permanently shadow system volume control for every
# utterance, video open or not.
_YOUTUBE_SEARCH_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        r"^(?:включи|включим|найди|найду|найдём|открой|открою|откроем|запусти|запустим)\s+"
        r"(?:на\s+ютубе|в\s+ютубе|на\s+youtube)\s+(.+)$"
    ),
    "uk": re.compile(r"^(?:увімкни|знайди|відкрий|запусти)\s+(?:на\s+ютубі|на\s+youtube)\s+(.+)$"),
    "en": re.compile(r"^(?:play|find|open|search)\s+(.+?)\s+on\s+youtube$"),
}

# A bare "пауза"/"продолжи"/"следующее" doesn't say WHICH service it means
# — modules.media_control resolves that at dispatch time by checking what's
# actually playing/loaded right now (YouTube's open tab, Spotify's player
# state). An utterance that ALSO contains a target word ("пауза видео"/
# "пауза музыки") skips that guesswork and goes straight to the named
# service instead — see _VIDEO_QUALIFIER_WORDS/_MUSIC_QUALIFIER_WORDS below.
#
# Deliberately two separate checks (verb, then a plain substring scan for a
# qualifier word) rather than one combined multi-word phrase set matched via
# fuzzy_matches_any — that was the first attempt here, and it doesn't work:
# fuzzy_contains_phrase slides a window sized to the SHORTER side, so a
# short real utterance like "поставь музыку" (2 words) matches as a
# near-identical *chunk* of a longer stored phrase like "поставь музыку на
# паузу" (4 words) even though it means something completely different
# (that's modules.calendar's open-media "поставь музыку", not a pause). A
# plain `word in normalized` scan for the qualifier has no such false
# positive, since it only ever looks for a literal, distinct word.
_PAUSE_VERB_PHRASES: dict[str, set[str]] = {
    "ru": {"пауза", "поставь на паузу"},
    "uk": {"пауза", "постав на паузу"},
    "en": {"pause"},
}

_RESUME_VERB_PHRASES: dict[str, set[str]] = {
    "ru": {"продолжи", "играй", "сними с паузы"},
    "uk": {"продовжуй", "грай"},
    "en": {"resume", "continue"},
}

_NEXT_VERB_PHRASES: dict[str, set[str]] = {
    "ru": {"следующее"},
    "uk": {"наступне"},
    "en": {"next"},
}

_VIDEO_QUALIFIER_WORDS: dict[str, set[str]] = {
    "ru": {"видео", "ютуб", "youtube"},
    "uk": {"відео", "ютуб", "youtube"},
    "en": {"video", "youtube"},
}

# Word stems, not full words — a plain substring check, so "музык" alone
# covers "музыку"/"музыки"/"музыка"/"музыкой" etc. without enumerating every
# inflected form. None of these stems collide with an unrelated Russian/
# Ukrainian word, so the shorter form is safe here (contrast with
# _VIDEO_QUALIFIER_WORDS' "видео", which doesn't decline at all as a
# borrowed word and so didn't need this).
_MUSIC_QUALIFIER_WORDS: dict[str, set[str]] = {
    "ru": {"музык", "трек", "песн", "спотифа", "spotify"},
    "uk": {"музик", "трек", "пісн", "спотифа", "spotify"},
    "en": {"music", "track", "song", "spotify"},
}


def _contains_any_word(normalized: str, words: set[str]) -> bool:
    return any(word in normalized for word in words)


# Routed straight to modules/weather (a real forecast API, no LLM involved)
# instead of falling through to AI-bridge classification — "какая погода в
# Киеве" used to mean a 10+ second browser-automation round trip (or worse,
# a made-up answer from a model with no live data access) for a question a
# dedicated weather API answers in under a second. _WEATHER_WHEN_MARKERS is
# checked as plain substrings (not word-scanned like the qualifier sets
# above) since "послезавтра" must be checked before "завтра" - it contains
# "завтра" as a substring, and dict iteration order is preserved in Python,
# so listing the longer marker first here is what makes that work.
_WEATHER_TRIGGER_WORDS: dict[str, set[str]] = {
    "ru": {"погода", "погоду", "погоде", "погодка"},
    "uk": {"погода", "погоду", "погоді"},
    "en": {"weather"},
}

_WEATHER_WHEN_MARKERS: dict[str, dict[str, str]] = {
    "ru": {
        "послезавтра": "day_after_tomorrow", "завтра": "tomorrow",
        "позавчера": "day_before_yesterday", "вчера": "yesterday", "сегодня": "today",
    },
    "uk": {
        "післязавтра": "day_after_tomorrow", "завтра": "tomorrow",
        "позавчора": "day_before_yesterday", "вчора": "yesterday", "сьогодні": "today",
    },
    "en": {
        "day after tomorrow": "day_after_tomorrow", "tomorrow": "tomorrow",
        "day before yesterday": "day_before_yesterday", "yesterday": "yesterday", "today": "today",
    },
}

# Arbitrary-day range ("через 5 дней"/"5 дней назад"), on top of the fixed
# named markers above — modules/weather/domain.py's resolve_day_offset also
# accepts a plain signed-integer string ("5"/"-5") for exactly this case,
# clamped to its [-7, 7] window. Checked only when no named marker matched
# (see interpret() below) since a phrase like "через час" (an hour, not a
# day) has no business being caught here, and named markers cover the
# common cases without a number at all. Each pair is (forward, backward) —
# "через" doesn't itself distinguish direction the way "назад"/"ago" does.
_WEATHER_RELATIVE_DAYS_PATTERNS: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "ru": (
        re.compile(r"через\s+(\d+)\s+(?:день|дня|дней)\b"),
        re.compile(r"(\d+)\s+(?:день|дня|дней)\s+назад\b"),
    ),
    "uk": (
        re.compile(r"через\s+(\d+)\s+дн\w*\b"),
        re.compile(r"(\d+)\s+дн\w*\s+тому\b"),
    ),
    "en": (
        re.compile(r"\bin\s+(\d+)\s+days?\b"),
        re.compile(r"(\d+)\s+days?\s+ago\b"),
    ),
}

# The preposition that idiomatically precedes a when-marker in "погоду НА
# завтра"/"weather FOR tomorrow" (as opposed to a bare "погода завтра" with
# no preposition at all, already handled without this). Only used to strip
# that whole two-word phrase before city extraction below — see its comment.
_WEATHER_WHEN_PREPOSITIONS: dict[str, str] = {"ru": "на", "uk": "на", "en": "for"}

# Captures a trailing "в/на <город>", tolerating a when-marker either
# before or after it ("погода в Киеве завтра" and "погода завтра в Киеве"
# both work) since the group is anchored to the city phrase itself, not to
# the sentence's start/end.
_WEATHER_CITY_PATTERNS: dict[str, re.Pattern[str]] = {
    # "во" (not just "в") - found live: "погода во Львове" left city empty,
    # since "во" is the standard Russian elision spelling of "в" before a
    # word starting with certain consonant clusters (Львов, Владивосток,
    # ...) and the pattern only ever recognized bare "в".
    "ru": re.compile(r"(?:^|\s)(?:во|в|на)\s+([а-яё][а-яё\- ]*?)(?:\s+(?:сегодня|завтра|послезавтра))?$"),
    "uk": re.compile(r"(?:^|\s)(?:в|у|на)\s+([а-яіїєґ][а-яіїєґ\- ]*?)(?:\s+(?:сьогодні|завтра|післязавтра))?$"),
    "en": re.compile(r"(?:^|\s)in\s+([a-z][a-z\- ]*?)(?:\s+(?:today|tomorrow))?$"),
}

# The captured group is optional — a bare "перемотай вперёд" with no
# explicit duration falls back to _YOUTUBE_DEFAULT_SEEK_SECONDS.
_YOUTUBE_SEEK_FORWARD_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^перемотай(?:\s+видео)?\s+вперёд(?:\s+на\s+(\d+)\s*секунд\w*)?$"),
    "uk": re.compile(r"^перемотай(?:\s+відео)?\s+вперед(?:\s+на\s+(\d+)\s*секунд\w*)?$"),
    "en": re.compile(r"^(?:seek|skip)(?:\s+the\s+video)?\s+forward(?:\s+(\d+)\s*seconds?)?$"),
}

_YOUTUBE_SEEK_BACKWARD_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^перемотай(?:\s+видео)?\s+назад(?:\s+на\s+(\d+)\s*секунд\w*)?$"),
    "uk": re.compile(r"^перемотай(?:\s+відео)?\s+назад(?:\s+на\s+(\d+)\s*секунд\w*)?$"),
    "en": re.compile(r"^(?:seek|skip)(?:\s+the\s+video)?\s+back(?:ward)?(?:\s+(\d+)\s*seconds?)?$"),
}

_YOUTUBE_DEFAULT_SEEK_SECONDS = 10

_YOUTUBE_VOLUME_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:поставь\s+)?громкост[ьи]\s+видео(?:\s+на)?\s+(\d+)(?:\s*процент\w*)?$"),
    "uk": re.compile(r"^гучність\s+відео(?:\s+на)?\s+(\d+)(?:\s*відсотк\w*)?$"),
    "en": re.compile(r"^(?:set\s+)?(?:the\s+)?video\s+volume(?:\s+to)?\s+(\d+)(?:\s*percent)?$"),
}

# _normalize() strips all punctuation, including "."/"," — a literal
# decimal ("1.5") never survives it, so speed is voiced/parsed as a whole-
# number percentage instead ("скорость видео 150 процентов" -> rate 1.5),
# same units convention _YOUTUBE_VOLUME_PATTERNS already uses.
_YOUTUBE_SPEED_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:поставь\s+)?скорость\s+видео(?:\s+на)?\s+(\d+)(?:\s*процент\w*)?$"),
    "uk": re.compile(r"^швидкість\s+відео(?:\s+на)?\s+(\d+)(?:\s*відсотк\w*)?$"),
    "en": re.compile(r"^(?:set\s+)?(?:the\s+)?video\s+speed(?:\s+to)?\s+(\d+)(?:\s*percent)?$"),
}

# Same reasoning as _YOUTUBE_SEARCH_PATTERNS above: checked before
# _MEDIA_VERB_PATTERNS/_OPEN_APP_PATTERNS so "включи на спотифае X" isn't
# swallowed by open_media/open_app first. "на спотифае", not "в спотифае" —
# the latter was tried first and dropped: "включи в спотифае ..." fuzzy-
# matched _SHUTDOWN_PHRASES' "выключи пк" closely enough on the "включи в"
# chunk (short strings, high accidental SequenceMatcher ratio) to return
# `shutdown` instead of ever reaching this pattern — measured directly, not
# assumed. "на спотифае" doesn't share that risk.
_SPOTIFY_SEARCH_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        r"^(?:включи|включим|найди|найду|найдём|открой|открою|откроем|запусти|запустим)\s+"
        r"(?:на\s+спотифае|на\s+spotify)\s+(.+)$"
    ),
    "uk": re.compile(r"^(?:увімкни|знайди|відкрий|запусти)\s+(?:на\s+спотіфаї|на\s+spotify)\s+(.+)$"),
    "en": re.compile(r"^(?:play|find|open|search)\s+(.+?)\s+on\s+spotify$"),
}

# Same "explicit word required" reasoning as _YOUTUBE_VOLUME_PATTERNS —
# bare "громче"/"тише" must keep meaning system volume.
_SPOTIFY_VOLUME_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:поставь\s+)?громкост[ьи]\s+музык(?:и|у)(?:\s+на)?\s+(\d+)(?:\s*процент\w*)?$"),
    "uk": re.compile(r"^гучність\s+музики(?:\s+на)?\s+(\d+)(?:\s*відсотк\w*)?$"),
    "en": re.compile(r"^(?:set\s+)?(?:the\s+)?music\s+volume(?:\s+to)?\s+(\d+)(?:\s*percent)?$"),
}

# System (OS-mixer) volume — found live: unlike video/music volume just
# above, this had NO rule-based pattern at all despite the comment at the
# top of this section already claiming bare "громче"/"тише"/"поставь
# громкость N" "already mean system volume" — that was only ever true if
# something else caught them, and nothing did. Every such phrase, even a
# clean, common one, fell through interpret() entirely and depended on AI
# classification (see core/dispatcher.py's set_volume/change_volume) —
# unreliable for something that should be instant and deterministic, the
# same reasoning core/voice/weather's rule-based interception was added
# for earlier.
#
# "до N" always means absolute set_volume(N), regardless of which verb
# comes before it — found live: "увеличь громкость до 100" is phrased with
# an increase-flavored verb but means "set it to 100", not "raise it by
# 100" the way "увеличь громкость НА 100" would. Checked first, with every
# verb accepted, so it isn't shadowed by the narrower increase/decrease
# patterns below (which only recognize "на N" as relative change).
# Optional device filler ("на ноутбуке"/"на компьютере") tolerated right
# after "громкость"/"гучність"/"volume" and before the amount — found live:
# "поднять громкость на ноутбуке до 10%" fell through this regex entirely
# (no filler tolerance at all) and landed on the AI fallback instead of the
# deterministic rule-based path, purely because of three harmless extra
# words naming the obvious device. Doesn't attempt every possible device
# word, just the common ones actually heard live.
_VOLUME_DEVICE_FILLER_RU = r"(?:\s+на\s+(?:ноутбуке|компьютере|ноуте|компе|телефоне))?"
_VOLUME_DEVICE_FILLER_UK = r"(?:\s+на\s+(?:ноутбуці|комп'ютері|телефоні))?"
_VOLUME_DEVICE_FILLER_EN = r"(?:\s+on\s+(?:the\s+)?(?:laptop|computer|pc|phone))?"

_SYSTEM_VOLUME_SET_TO_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        r"^(?:(?:поставь|сделай|установи|переключи|увеличь|увеличи|уменьши|убавь|прибавь|подними|повысь|"
        rf"понизь|сбавь)\s+)?(?:мне\s+)?громкост[ьи]{_VOLUME_DEVICE_FILLER_RU}\s+до\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:(?:постав|зроби|встанови|збільш\w*|підніми|зменш\w*|знизь)\s+)?гучність{_VOLUME_DEVICE_FILLER_UK}"
        rf"\s+до\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:(?:set|increase|raise|decrease|lower)\s+)?(?:the\s+)?(?:system\s+)?volume{_VOLUME_DEVICE_FILLER_EN}"
        rf"\s+to\s+(\d+)(?:\s*percent)?$"
    ),
}

# "на N" (or bare "громкость N") with no increase/decrease verb — also
# absolute, matching how the already-existing _YOUTUBE_VOLUME_PATTERNS/
# _SPOTIFY_VOLUME_PATTERNS above treat their own "на N".
_SYSTEM_VOLUME_SET_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:(?:поставь|сделай|установи|переключи)\s+)?(?:мне\s+)?громкост[ьи]{_VOLUME_DEVICE_FILLER_RU}"
        rf"\s+(?:на\s+)?(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:(?:постав|зроби|встанови)\s+)?гучність{_VOLUME_DEVICE_FILLER_UK}\s+(?:на\s+)?(\d+)"
        rf"(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:set\s+)?(?:the\s+)?(?:system\s+)?volume{_VOLUME_DEVICE_FILLER_EN}(?:\s+to)?\s+(\d+)(?:\s*percent)?$"
    ),
}

_SYSTEM_VOLUME_INCREASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:увеличь|увеличи|прибавь|подними|повысь)\s+(?:мне\s+)?громкост[ьи]{_VOLUME_DEVICE_FILLER_RU}"
        rf"\s+на\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:збільш\w*|підніми)\s+гучність{_VOLUME_DEVICE_FILLER_UK}\s+на\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:increase|raise|turn\s+up)\s+(?:the\s+)?volume{_VOLUME_DEVICE_FILLER_EN}\s+by\s+(\d+)(?:\s*percent)?$"
    ),
}

_SYSTEM_VOLUME_DECREASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:уменьши|убавь|сбавь|понизь)\s+(?:мне\s+)?громкост[ьи]{_VOLUME_DEVICE_FILLER_RU}"
        rf"\s+на\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:зменш\w*|знизь)\s+гучність{_VOLUME_DEVICE_FILLER_UK}\s+на\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:decrease|lower|turn\s+down)\s+volume{_VOLUME_DEVICE_FILLER_EN}\s+by\s+(\d+)(?:\s*percent)?$"
    ),
}

# Screen brightness (core/dispatcher.py's set_brightness/change_brightness) —
# mirrors the _SYSTEM_VOLUME_*_PATTERNS above one-for-one, just keyed on the
# "яркость"/"яскравість"/"brightness" noun instead of "громкость". The two
# families never overlap: the noun word alone disambiguates them. Same
# device-filler tolerance (the _VOLUME_DEVICE_FILLER_* regexes are generic
# "на ноутбуке"/"on the laptop" fragments, not volume-specific) and the same
# "до N = absolute, на N = relative" split. A bare "сделай ярче"/"потемнее"
# with no number deliberately isn't matched here — it falls through to the
# embedding classifier's change_brightness with a default step, exactly as
# "сделай погромче" does for volume.
_SYSTEM_BRIGHTNESS_SET_TO_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        r"^(?:(?:поставь|сделай|установи|переключи|увеличь|увеличи|уменьши|убавь|прибавь|подними|повысь|"
        rf"понизь|сбавь)\s+)?(?:мне\s+)?яркост[ьи]{_VOLUME_DEVICE_FILLER_RU}\s+до\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:(?:постав|зроби|встанови|збільш\w*|підніми|зменш\w*|знизь)\s+)?яскравіст[ьі]{_VOLUME_DEVICE_FILLER_UK}"
        rf"\s+до\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:(?:set|increase|raise|decrease|lower|dim)\s+)?(?:the\s+)?(?:screen\s+|display\s+)?brightness"
        rf"{_VOLUME_DEVICE_FILLER_EN}\s+to\s+(\d+)(?:\s*percent)?$"
    ),
}

_SYSTEM_BRIGHTNESS_SET_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:(?:поставь|сделай|установи|переключи)\s+)?(?:мне\s+)?яркост[ьи]{_VOLUME_DEVICE_FILLER_RU}"
        rf"\s+(?:на\s+)?(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:(?:постав|зроби|встанови)\s+)?яскравіст[ьі]{_VOLUME_DEVICE_FILLER_UK}\s+(?:на\s+)?(\d+)"
        rf"(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:set\s+)?(?:the\s+)?(?:screen\s+|display\s+)?brightness{_VOLUME_DEVICE_FILLER_EN}"
        rf"(?:\s+to)?\s+(\d+)(?:\s*percent)?$"
    ),
}

_SYSTEM_BRIGHTNESS_INCREASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:увеличь|увеличи|прибавь|подними|повысь|добавь)\s+(?:мне\s+)?яркост[ьи]{_VOLUME_DEVICE_FILLER_RU}"
        rf"\s+на\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:збільш\w*|підніми|додай)\s+яскравіст[ьі]{_VOLUME_DEVICE_FILLER_UK}\s+на\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:increase|raise|turn\s+up)\s+(?:the\s+)?(?:screen\s+|display\s+)?brightness{_VOLUME_DEVICE_FILLER_EN}"
        rf"\s+by\s+(\d+)(?:\s*percent)?$"
    ),
}

_SYSTEM_BRIGHTNESS_DECREASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:уменьши|убавь|сбавь|понизь|снизь)\s+(?:мне\s+)?яркост[ьи]{_VOLUME_DEVICE_FILLER_RU}"
        rf"\s+на\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:зменш\w*|знизь)\s+яскравіст[ьі]{_VOLUME_DEVICE_FILLER_UK}\s+на\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        rf"^(?:decrease|lower|dim|turn\s+down)\s+(?:the\s+)?(?:screen\s+|display\s+)?brightness"
        rf"{_VOLUME_DEVICE_FILLER_EN}\s+by\s+(\d+)(?:\s*percent)?$"
    ),
}

# The assistant's own voice (TTS output) volume, distinct from the
# OS-mixer volume above — found live: a user asking for "свою"/"личную"
# громкость had no rule-based path, no dispatcher command to even resolve
# to (see core/dispatcher.py's set_assistant_volume/change_assistant_volume,
# added alongside these patterns), and fell through to the AI free-text
# fallback, which could return a plausible-sounding "sure, done!" answer
# with nothing actually changed. Mirrors the system-volume patterns above
# one-for-one, just with a personal-possessive marker word required
# immediately before "громкость" so the two families never overlap
# (_SYSTEM_VOLUME_*_PATTERNS only tolerate an optional "мне", never "свою"/
# "личную"/"твою", so a phrase matching one of these never falls into the
# other).
_ASSISTANT_VOLUME_MARKER_RU = r"(?:свою|личную|твою|собственную)"
_ASSISTANT_VOLUME_MARKER_UK = r"(?:власну|особисту)"

_ASSISTANT_VOLUME_SET_TO_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:(?:поставь|сделай|установи|переключи|увеличь|увеличи|уменьши|убавь|прибавь|подними|повысь|"
        rf"понизь|сбавь)\s+)?(?:мне\s+)?{_ASSISTANT_VOLUME_MARKER_RU}\s+громкост[ьи]\s+до\s+(\d+)"
        rf"(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:(?:постав|зроби|встанови|збільш\w*|підніми|зменш\w*|знизь)\s+)?{_ASSISTANT_VOLUME_MARKER_UK}"
        rf"\s+гучність\s+до\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(
        r"^(?:(?:set|increase|raise|decrease|lower)\s+)?your(?:\s+own)?\s+volume\s+to\s+(\d+)(?:\s*percent)?$"
    ),
}

_ASSISTANT_VOLUME_SET_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:(?:поставь|сделай|установи|переключи)\s+)?(?:мне\s+)?{_ASSISTANT_VOLUME_MARKER_RU}"
        rf"\s+громкост[ьи]\s+(?:на\s+)?(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:(?:постав|зроби|встанови)\s+)?{_ASSISTANT_VOLUME_MARKER_UK}\s+гучність\s+(?:на\s+)?(\d+)"
        rf"(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(r"^(?:set\s+)?your(?:\s+own)?\s+volume(?:\s+to)?\s+(\d+)(?:\s*percent)?$"),
}

_ASSISTANT_VOLUME_INCREASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:увеличь|увеличи|прибавь|подними|повысь)\s+(?:мне\s+)?{_ASSISTANT_VOLUME_MARKER_RU}"
        rf"\s+громкост[ьи]\s+на\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:збільш\w*|підніми)\s+{_ASSISTANT_VOLUME_MARKER_UK}\s+гучність\s+на\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(r"^(?:increase|raise|turn\s+up)\s+your(?:\s+own)?\s+volume\s+by\s+(\d+)(?:\s*percent)?$"),
}

_ASSISTANT_VOLUME_DECREASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(
        rf"^(?:уменьши|убавь|сбавь|понизь)\s+(?:мне\s+)?{_ASSISTANT_VOLUME_MARKER_RU}"
        rf"\s+громкост[ьи]\s+на\s+(\d+)(?:\s*процент\w*)?$"
    ),
    "uk": re.compile(
        rf"^(?:зменш\w*|знизь)\s+{_ASSISTANT_VOLUME_MARKER_UK}\s+гучність\s+на\s+(\d+)(?:\s*відсотк\w*)?$"
    ),
    "en": re.compile(r"^(?:decrease|lower|turn\s+down)\s+your(?:\s+own)?\s+volume\s+by\s+(\d+)(?:\s*percent)?$"),
}

# Deliberately no bare "громче"/"тише" pattern here (unlike the
# parameterized patterns above) — those already have a working path via
# modules/hardware_adaptive/command_classifier.py's embedding-based
# matcher, checked later in core/voice/pipeline.py, and interpret() must
# keep returning None for them so they actually reach it (see
# test_bare_system_volume_phrase_is_not_claimed_by_youtube). Only phrases
# with an explicit number were genuinely missing a fast path.

# Checked before _OPEN_APP_PATTERNS for the same reason as _YOUTUBE_SEARCH_
# PATTERNS above — "нарисуй"/"сгенерируй" aren't claimed by anything else,
# but placed alongside the other media-search patterns for locality.
_IMAGE_GENERATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ru": re.compile(r"^(?:сгенерируй|сгенерируем|нарисуй|нарисуем)(?:\s+изображение|\s+картинку)?\s+(.+)$"),
    "uk": re.compile(r"^(?:згенеруй|намалюй)(?:\s+зображення|\s+картинку)?\s+(.+)$"),
    "en": re.compile(r"^(?:generate|draw)\s+(?:an?\s+)?(?:image|picture)\s+(?:of\s+)?(.+)$"),
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

# Checked before _SHUTDOWN_PHRASES in interpret(): "заблокируй компьютер"
# and "lock the computer" both fuzzily match a shutdown trigger ("выключи
# компьютер" / "shut down the computer") and must be claimed as a lock
# first. Locking is trivially reversible but still routed through the
# dispatcher's spoken-confirmation flow (dangerous=True), same as
# shutdown/restart, per the task spec. Phrases here are kept deliberately
# clear of the volume/brightness device-filler shapes checked later in
# interpret() ("...громкость на компьютере...", "...the screen brightness...")
# — a bare "lock the screen"/"залочь ..." collided with those at the 0.75
# sliding-window threshold, so it's left to the semantic classifier / AI
# fallback instead of this fast path.
_LOCK_SCREEN_PHRASES: dict[str, set[str]] = {
    "ru": {
        "заблокируй компьютер", "заблокируй пк", "заблокируй систему",
        "заблокируй экран", "блокировка экрана", "поставь блокировку экрана",
    },
    "uk": {
        "заблокуй комп'ютер", "заблокуй пк", "заблокуй екран", "блокування екрана",
    },
    "en": {
        "lock screen", "lock my screen", "lock the computer", "lock the pc",
        "lock the workstation",
    },
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
# for it to *dispatch*: starting a game runs synchronously inside
# core/voice/pipeline.py::_resolve_board_game itself, called directly from
# interpret()'s match, same shape as _resolve_messaging_reply's "handles
# everything itself, never hands a Command to the generic dispatch call"
# pattern). Only the *start* of a game needs one of these trigger phrases —
# once a game is active, individual moves are recognized a different way
# (see core/voice/pipeline.py::_resolve_active_board_game_utterance, checked
# before interpret() is even called). A phrasing that doesn't match one of
# these variants just won't start a game — a known first-slice limitation,
# not an oversight.
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
# core/voice/pipeline.py::_resolve_active_board_game_utterance) means "end
# this chess/draughts game as a loss," not "stop talking" — conflating the
# two would make an ordinary "стоп" during a game ambiguous between "pause"
# and "resign," when the player almost always means the former.
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


# Trigger phrases for modules.os_agent — starts agent mode itself only; the
# task description that follows is free text, matched directly in
# core/voice/pipeline.py::_resolve_active_os_agent_utterance (checked before
# interpret() even runs), same shape as a chess/checkers move never needing
# its own intent.py pattern once _BOARD_GAME_PHRASES has started the game.
_OS_AGENT_START_PHRASES: dict[str, set[str]] = {
    # Deliberately no bare "запусти агента"/"запусти режим агента" — the short
    # "запусти X" shape already collides (via fuzzy_contains_phrase's
    # character-level ratio) with open_app's own launch-verb-drift tolerance
    # ("запустим стим"), same false-positive class documented for
    # "поставь музыку"/"поставь музыку на паузу" elsewhere.
    "ru": {"включи режим агента", "активируй режим агента"},
    "uk": {"увімкни режим агента", "активуй режим агента"},
    "en": {
        "turn on agent mode", "enable agent mode", "start agent mode", "activate agent mode",
    },
}

# Trigger phrases for modules.discussion_mode — same shape as
# _OS_AGENT_START_PHRASES: only *entering* the mode is recognized here; once
# active, everything said is handled by pipeline.py's discussion sub-loop
# (transcribe + buffer, never classify), and only the explicit exit phrase
# (modules/discussion_mode/detector.py) leaves it.
_DISCUSSION_START_PHRASES: dict[str, set[str]] = {
    "ru": {
        "давай подискутируем", "давай подискутируем втроём", "режим дискуссии",
        "включи режим дискуссии", "давай обсудим втроём",
    },
    "uk": {"давай подискутуємо", "режим дискусії", "увімкни режим дискусії"},
    "en": {"let's have a discussion", "discussion mode", "enable discussion mode"},
}

# Trigger phrases for modules.fitness_tracker's voice context (see
# core/voice/pipeline.py::_resolve_active_fitness_context_utterance) — same
# shape as _OS_AGENT_START_PHRASES: only the *entry* into the context is
# recognized here via interpret(); everything said once the context is
# active is handled by modules.fitness_tracker.intent_parser instead, not by
# a fixed phrase list. Deliberately no short "давай..."/"хочу..." openers
# (as the task spec's own examples suggested, e.g. "давай про показатели")
# — those collide with _BOARD_GAME_PHRASES's "давай поиграем"/"хочу
# поиграть" via fuzzy_contains_phrase's character-level ratio, and no
# "активируй режим X" shape either, which collides with
# _OS_AGENT_START_PHRASES's "активируй режим агента" the same way. Checked
# empirically against every other fuzzy-matched phrase catalog in this file
# before being finalized — see the fitness_tracker plan's note on this bug
# class.
_FITNESS_START_PHRASES: dict[str, set[str]] = {
    "ru": {
        "перейди в фитнес трекер", "открой фитнес трекер",
        "включи режим отслеживания фитнеса", "открой модуль спорта",
        "запусти дневник тренировок",
    },
    "uk": {
        "перейди в фітнес трекер", "відкрий фітнес трекер",
        "увімкни режим відстеження фітнесу",
    },
    "en": {
        "open the fitness tracker", "switch to fitness tracking mode",
        "activate fitness tracking mode",
    },
}

# Distinct from STOP_PHRASES/is_stop_command, same reasoning as
# RESIGN_PHRASES above: exiting the fitness context is a deliberate,
# fitness-specific action, not the general "stop talking" barge-in phrase —
# checked only while modules.fitness_tracker.context_state.is_active() (see
# core/voice/pipeline.py). A bare "хватит"/"досить"/"stop" still exits the
# context too (it's a real word of these phrases, matched via the same
# fuzzy window), which mirrors every other "in-progress mode" here already
# treating a bare stop word as an implicit exit.
_FITNESS_EXIT_PHRASES: dict[str, set[str]] = {
    "ru": {
        "выйди из фитнес трекера", "закончи с отслеживанием фитнеса",
        "вернись в обычный режим работы", "хватит про фитнес", "хватит про спорт",
    },
    "uk": {"вийди з фітнес трекера", "досить про фітнес"},
    "en": {"exit fitness tracker", "stop tracking fitness", "leave fitness mode"},
}


def is_fitness_exit_command(text: str, language: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    return fuzzy_matches_any(normalized, _FITNESS_EXIT_PHRASES.get(language, set()))

# Trigger words for modules.figma_control (see that module's
# command_parser.py for the actual action/params parsing — this only
# decides whether an utterance should be routed there at all).
# Deliberately broad and unanchored, and checked last (right before the
# equally-broad _OPEN_APP_PATTERNS) since a Figma voice command can start
# with many different verbs ("создай", "выдели", "покрась", "сгруппируй",
# "выровняй", "удали слой", "отмени", ...) that aren't worth enumerating
# here when command_parser.py already knows how to parse each of them.
# Extend this set as real usage surfaces gaps or false positives.
_FIGMA_TRIGGER_WORDS: dict[str, tuple[str, ...]] = {
    "ru": ("в фигме", "в figma", "фигма", "фигму", "слой", "фрейм", "прямоугольник"),
    "en": ("in figma", "figma", "layer", "frame", "rectangle"),
}


def _mentions_figma(normalized: str, language: str) -> bool:
    return any(word in normalized for word in _FIGMA_TRIGGER_WORDS.get(language, ()))


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
    if fuzzy_matches_any(normalized, _LOCK_SCREEN_PHRASES.get(language, set())):
        return Command(name="lock_screen", params={})

    if fuzzy_matches_any(normalized, _SHUTDOWN_PHRASES.get(language, set())):
        return Command(name="shutdown", params={})

    if fuzzy_matches_any(normalized, _RESTART_PHRASES.get(language, set())):
        return Command(name="restart", params={})

    # modules/software_installer — checked early so bare "нажми далее" /
    # "установи <known program>" aren't first claimed by ui_action /
    # media_next / open_app. The installer-button pattern only fires when
    # the single label word is a recognized button (_INSTALLER_BUTTON_KINDS);
    # the install pattern only claims the utterance when a marker word is
    # present or package_map recognizes the name (otherwise falls through).
    installer_button_pattern = _INSTALLER_BUTTON_PATTERNS.get(language)
    if installer_button_pattern:
        button_match = installer_button_pattern.match(normalized)
        if button_match:
            kind = _INSTALLER_BUTTON_KINDS.get(button_match.group("label").strip().lower())
            if kind is not None:
                return Command(name="installer_click_button", params={"button": kind})

    install_pattern = _SOFTWARE_INSTALL_PATTERNS.get(language)
    if install_pattern:
        install_match = install_pattern.match(normalized)
        if install_match:
            app = install_match.group("app").strip()
            has_marker = bool(install_match.group("marker"))
            from modules.software_installer import package_map

            if app and (has_marker or package_map.resolve(app) is not None):
                return Command(name="software_install", params={"app": app})

    if normalized in _SHOW_WINDOW_PHRASES.get(language, set()):
        return Command(name="show_window", params={})

    if normalized in _HIDE_WINDOW_PHRASES.get(language, set()):
        return Command(name="hide_window", params={})

    if normalized in _CAPABILITIES_PHRASES.get(language, set()):
        return Command(name="list_capabilities", params={"language": language})

    if _contains_any_word(normalized, _WEATHER_TRIGGER_WORDS.get(language, set())):
        when = "today"
        when_marker = ""
        for marker, value in _WEATHER_WHEN_MARKERS.get(language, {}).items():
            if marker in normalized:
                when = value
                when_marker = marker
                break
        if not when_marker:
            forward_pattern, backward_pattern = _WEATHER_RELATIVE_DAYS_PATTERNS.get(language, (None, None))
            forward_match = forward_pattern.search(normalized) if forward_pattern else None
            backward_match = backward_pattern.search(normalized) if backward_pattern else None
            if forward_match:
                when = forward_match.group(1)
                when_marker = forward_match.group(0)
            elif backward_match:
                when = f"-{backward_match.group(1)}"
                when_marker = backward_match.group(0)
        city = ""
        city_pattern = _WEATHER_CITY_PATTERNS.get(language)
        if city_pattern:
            # Strip the when-marker (and an idiomatic preposition right
            # before it, e.g. "на завтра"/"for tomorrow") before searching
            # for the city — regression found live: "погоду на завтра в
            # Киеве" was captured whole as the city ("завтра в киеве"),
            # since the city pattern's capture group allows spaces and
            # nothing stopped it from also swallowing "на завтра" once the
            # search started there instead of at the real "в Киеве". A bare
            # marker with no preceding preposition ("погода завтра в
            # Киеве", already covered by existing tests) is unaffected —
            # stripping it here just leaves the same clean text that case
            # already produced.
            text_for_city = normalized
            if when_marker:
                preposition = _WEATHER_WHEN_PREPOSITIONS.get(language, "")
                optional_preposition = rf"(?:{re.escape(preposition)}\s+)?" if preposition else ""
                text_for_city = re.sub(rf"{optional_preposition}{re.escape(when_marker)}\b", " ", text_for_city)
                text_for_city = re.sub(r"\s+", " ", text_for_city).strip()
            city_match = city_pattern.search(text_for_city)
            if city_match:
                city = city_match.group(1).strip()
        return Command(name="weather_get", params={"city": city, "when": when})

    assistant_set_to_pattern = _ASSISTANT_VOLUME_SET_TO_PATTERNS.get(language)
    if assistant_set_to_pattern:
        assistant_set_to_match = assistant_set_to_pattern.match(normalized)
        if assistant_set_to_match:
            return Command(name="set_assistant_volume", params={"percent": assistant_set_to_match.group(1)})

    assistant_increase_pattern = _ASSISTANT_VOLUME_INCREASE_PATTERNS.get(language)
    if assistant_increase_pattern:
        assistant_increase_match = assistant_increase_pattern.match(normalized)
        if assistant_increase_match:
            return Command(
                name="change_assistant_volume", params={"delta_percent": assistant_increase_match.group(1)}
            )

    assistant_decrease_pattern = _ASSISTANT_VOLUME_DECREASE_PATTERNS.get(language)
    if assistant_decrease_pattern:
        assistant_decrease_match = assistant_decrease_pattern.match(normalized)
        if assistant_decrease_match:
            return Command(
                name="change_assistant_volume",
                params={"delta_percent": f"-{assistant_decrease_match.group(1)}"},
            )

    assistant_set_pattern = _ASSISTANT_VOLUME_SET_PATTERNS.get(language)
    if assistant_set_pattern:
        assistant_set_match = assistant_set_pattern.match(normalized)
        if assistant_set_match:
            return Command(name="set_assistant_volume", params={"percent": assistant_set_match.group(1)})

    set_to_pattern = _SYSTEM_VOLUME_SET_TO_PATTERNS.get(language)
    if set_to_pattern:
        set_to_match = set_to_pattern.match(normalized)
        if set_to_match:
            return Command(name="set_volume", params={"percent": set_to_match.group(1)})

    increase_pattern = _SYSTEM_VOLUME_INCREASE_PATTERNS.get(language)
    if increase_pattern:
        increase_match = increase_pattern.match(normalized)
        if increase_match:
            return Command(name="change_volume", params={"delta_percent": increase_match.group(1)})

    decrease_pattern = _SYSTEM_VOLUME_DECREASE_PATTERNS.get(language)
    if decrease_pattern:
        decrease_match = decrease_pattern.match(normalized)
        if decrease_match:
            return Command(name="change_volume", params={"delta_percent": f"-{decrease_match.group(1)}"})

    set_volume_pattern = _SYSTEM_VOLUME_SET_PATTERNS.get(language)
    if set_volume_pattern:
        set_volume_match = set_volume_pattern.match(normalized)
        if set_volume_match:
            return Command(name="set_volume", params={"percent": set_volume_match.group(1)})

    brightness_set_to_pattern = _SYSTEM_BRIGHTNESS_SET_TO_PATTERNS.get(language)
    if brightness_set_to_pattern:
        brightness_set_to_match = brightness_set_to_pattern.match(normalized)
        if brightness_set_to_match:
            return Command(name="set_brightness", params={"percent": brightness_set_to_match.group(1)})

    brightness_increase_pattern = _SYSTEM_BRIGHTNESS_INCREASE_PATTERNS.get(language)
    if brightness_increase_pattern:
        brightness_increase_match = brightness_increase_pattern.match(normalized)
        if brightness_increase_match:
            return Command(
                name="change_brightness", params={"delta_percent": brightness_increase_match.group(1)}
            )

    brightness_decrease_pattern = _SYSTEM_BRIGHTNESS_DECREASE_PATTERNS.get(language)
    if brightness_decrease_pattern:
        brightness_decrease_match = brightness_decrease_pattern.match(normalized)
        if brightness_decrease_match:
            return Command(
                name="change_brightness",
                params={"delta_percent": f"-{brightness_decrease_match.group(1)}"},
            )

    brightness_set_pattern = _SYSTEM_BRIGHTNESS_SET_PATTERNS.get(language)
    if brightness_set_pattern:
        brightness_set_match = brightness_set_pattern.match(normalized)
        if brightness_set_match:
            return Command(name="set_brightness", params={"percent": brightness_set_match.group(1)})

    if fuzzy_matches_any(normalized, _BOARD_GAME_PHRASES.get(language, set())):
        kind = ""
        for marker, game in _BOARD_GAME_KIND_MARKERS.get(language, {}).items():
            if marker in normalized:
                kind = game
                break
        return Command(name="start_board_game", params={"game": kind})

    if fuzzy_matches_any(normalized, _OS_AGENT_START_PHRASES.get(language, set())):
        return Command(name="start_os_agent", params={})

    if fuzzy_matches_any(normalized, _DISCUSSION_START_PHRASES.get(language, set())):
        return Command(name="start_discussion", params={})

    if fuzzy_matches_any(normalized, _FITNESS_START_PHRASES.get(language, set())):
        return Command(name="fitness_activate_context", params={})

    youtube_search_pattern = _YOUTUBE_SEARCH_PATTERNS.get(language)
    if youtube_search_pattern:
        youtube_search_match = youtube_search_pattern.match(normalized)
        if youtube_search_match:
            return Command(
                name="youtube_search_and_play", params={"query": youtube_search_match.group(1).strip()}
            )

    spotify_search_pattern = _SPOTIFY_SEARCH_PATTERNS.get(language)
    if spotify_search_pattern:
        spotify_search_match = spotify_search_pattern.match(normalized)
        if spotify_search_match:
            return Command(
                name="spotify_search_and_play", params={"query": spotify_search_match.group(1).strip()}
            )

    # Verb first, then (only on a match) a plain word scan decides the
    # target — see the block comment above _PAUSE_VERB_PHRASES for why this
    # is two separate checks rather than one combined fuzzy phrase set.
    if fuzzy_matches_any(normalized, _PAUSE_VERB_PHRASES.get(language, set())):
        if _contains_any_word(normalized, _VIDEO_QUALIFIER_WORDS.get(language, set())):
            return Command(name="youtube_pause", params={})
        if _contains_any_word(normalized, _MUSIC_QUALIFIER_WORDS.get(language, set())):
            return Command(name="spotify_pause", params={})
        return Command(name="media_pause", params={})

    if fuzzy_matches_any(normalized, _RESUME_VERB_PHRASES.get(language, set())):
        if _contains_any_word(normalized, _VIDEO_QUALIFIER_WORDS.get(language, set())):
            return Command(name="youtube_resume", params={})
        if _contains_any_word(normalized, _MUSIC_QUALIFIER_WORDS.get(language, set())):
            return Command(name="spotify_resume", params={})
        return Command(name="media_resume", params={})

    if fuzzy_matches_any(normalized, _NEXT_VERB_PHRASES.get(language, set())):
        if _contains_any_word(normalized, _VIDEO_QUALIFIER_WORDS.get(language, set())):
            return Command(name="youtube_next", params={})
        if _contains_any_word(normalized, _MUSIC_QUALIFIER_WORDS.get(language, set())):
            return Command(name="spotify_next", params={})
        return Command(name="media_next", params={})

    spotify_volume_pattern = _SPOTIFY_VOLUME_PATTERNS.get(language)
    if spotify_volume_pattern:
        spotify_volume_match = spotify_volume_pattern.match(normalized)
        if spotify_volume_match:
            return Command(name="spotify_set_volume", params={"percent": spotify_volume_match.group(1)})

    image_generation_pattern = _IMAGE_GENERATION_PATTERNS.get(language)
    if image_generation_pattern:
        image_generation_match = image_generation_pattern.match(normalized)
        if image_generation_match:
            return Command(name="generate_image", params={"prompt": image_generation_match.group(1).strip()})

    seek_forward_pattern = _YOUTUBE_SEEK_FORWARD_PATTERNS.get(language)
    if seek_forward_pattern:
        seek_forward_match = seek_forward_pattern.match(normalized)
        if seek_forward_match:
            seconds = int(seek_forward_match.group(1)) if seek_forward_match.group(1) else _YOUTUBE_DEFAULT_SEEK_SECONDS
            return Command(name="youtube_seek", params={"offset_seconds": str(seconds)})

    seek_backward_pattern = _YOUTUBE_SEEK_BACKWARD_PATTERNS.get(language)
    if seek_backward_pattern:
        seek_backward_match = seek_backward_pattern.match(normalized)
        if seek_backward_match:
            seconds = int(seek_backward_match.group(1)) if seek_backward_match.group(1) else _YOUTUBE_DEFAULT_SEEK_SECONDS
            return Command(name="youtube_seek", params={"offset_seconds": str(-seconds)})

    volume_pattern = _YOUTUBE_VOLUME_PATTERNS.get(language)
    if volume_pattern:
        volume_match = volume_pattern.match(normalized)
        if volume_match:
            return Command(name="youtube_set_volume", params={"percent": volume_match.group(1)})

    speed_pattern = _YOUTUBE_SPEED_PATTERNS.get(language)
    if speed_pattern:
        speed_match = speed_pattern.match(normalized)
        if speed_match:
            return Command(name="youtube_set_speed", params={"rate": str(int(speed_match.group(1)) / 100)})

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

    text_edit_pattern = _TEXT_EDIT_MESSAGE_PATTERNS.get(language)
    if text_edit_pattern:
        text_edit_match = text_edit_pattern.match(normalized)
        if text_edit_match:
            return Command(
                name="edit_pending_message", params={"raw_target": text_edit_match.group(1).strip()}
            )

    code_analysis_pattern = _CODE_ANALYSIS_PATTERNS.get(language)
    if code_analysis_pattern and code_analysis_pattern.match(normalized):
        return Command(name="analyze_active_editor", params={})

    if _mentions_figma(normalized, language):
        return Command(name="figma_command", params={"text": text})

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
