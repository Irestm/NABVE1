from __future__ import annotations

import re

from num2words import num2words

from core.logger import get_logger

logger = get_logger(__name__)

# Matches a bare number (optional leading minus, optional decimal part with
# either separator) with an optional trailing "%" glued directly to it —
# the exact shape numbers show up in generated reply text (e.g.
# modules/weather/domain.py's "22", "-5", a volume level's "100%").
_NUMBER_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?%?")

_NUM2WORDS_LANGUAGE_BY_VOICE_LANGUAGE: dict[str, str] = {
    "ru": "ru",
    "uk": "uk",
    "en": "en",
}

_PERCENT_WORD_BY_LANGUAGE: dict[str, str] = {
    "ru": "процентов",
    "uk": "відсотків",
    "en": "percent",
}


def spell_out_numbers(text: str, language: str) -> str:
    """Replaces every bare number in `text` with its spelled-out word form
    (e.g. "22" -> "двадцать два", "100%" -> "сто процентов") before it
    reaches TTS synthesis.

    Found live: Silero's own built-in text normalizer either silently
    drops bare Arabic-numeral tokens from the spoken audio entirely — a
    reply like "температура от 12 до 22 градусов" was audibly missing both
    numbers, confirmed by feeding the synthesized audio straight back
    through this project's own STT — or, for a text that's *just* a bare
    number with nothing else around it, raises outright inside its
    normalizer. core/voice/tts.py catches that crash and permanently
    switches to Piper (a single voice, not the multi-speaker Silero
    catalog) for the rest of the process's life, silently degrading every
    subsequent reply's voice too, not just the one that triggered it —
    this is the actual fix for both symptoms, not two separate bugs.

    `language` unrecognized by num2words (anything other than
    supported_languages' "ru"/"uk"/"en") leaves `text` untouched rather
    than guessing; a single number that num2words can't convert for any
    reason is left as digits in place rather than failing the whole
    reply — this is a best-effort safety net, not something that should
    ever raise out of a TTS call."""
    num2words_language = _NUM2WORDS_LANGUAGE_BY_VOICE_LANGUAGE.get(language)
    if num2words_language is None:
        return text

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        has_percent = raw.endswith("%")
        numeric_part = raw[:-1] if has_percent else raw
        try:
            value: float = float(numeric_part.replace(",", "."))
            words = num2words(int(value) if value.is_integer() else value, lang=num2words_language)
        except (ValueError, NotImplementedError, OverflowError):
            logger.debug("Could not spell out %r for TTS; leaving as digits", raw, exc_info=True)
            return raw
        if has_percent:
            words = f"{words} {_PERCENT_WORD_BY_LANGUAGE.get(language, '%')}"
        return words

    return _NUMBER_PATTERN.sub(_replace, text)
