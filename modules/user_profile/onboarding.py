from __future__ import annotations

import threading
from dataclasses import dataclass
from difflib import SequenceMatcher

from core.logger import get_logger
from core.voice import audio_io
from core.voice import voice_preference
from core.voice.config import VoiceSettings
from core.voice.language import resolve_language, resolve_response_language
from core.voice.silero_tts import VOICE_OPTIONS
from core.voice.stt import SpeechToText
from core.voice.tts import TextToSpeech
from modules.user_profile import service_layer
from modules.user_profile.communication_styles import COMMUNICATION_STYLES, MAX_SELECTED_STYLES
from modules.user_profile.domain import (
    ASSISTANT_NAME_KEY,
    COMMUNICATION_STYLE_KEY,
    STOP_WORD_KEY,
    FactCategory,
)
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

# Below this fuzzy-match score, a spoken answer to a fixed-choice question
# (style, voice) is treated as "didn't match anything" rather than guessed
# at — same SequenceMatcher approach as
# modules.ai_bridge.intent_classifier._best_direct_match and
# core/voice/wake_word.py, just with a lower bar since these answers are
# often one short, easily-mistranscribed word ("агрессивно", "байя").
_LABEL_MATCH_THRESHOLD = 0.35

# Spoken before the first question, in every supported language since the
# user's language isn't known yet at this point — see run_onboarding.
# Already includes the first question ("what should I call you") so it
# isn't asked twice.
_GREETING: dict[str, str] = {
    "ru": (
        "Здравствуйте! Кажется, мы ещё не знакомы. Прежде чем начать, я задам "
        "несколько коротких вопросов, чтобы лучше вам помогать. Как мне к вам обращаться?"
    ),
    "uk": (
        "Вітаю! Здається, ми ще не знайомі. Перш ніж почати, я поставлю кілька "
        "коротких запитань, щоб краще вам допомагати. Як мені до вас звертатися?"
    ),
    "en": (
        "Hello! It looks like we haven't met yet. Before we start, I'll ask a "
        "few short questions so I can help you better. What should I call you?"
    ),
}

_CLOSING: dict[str, str] = {
    "ru": "Спасибо! Я всё запомнила и буду дополнять это по ходу нашего общения.",
    "uk": "Дякую! Я все запам'ятала і доповнюватиму це під час спілкування.",
    "en": "Thank you! I've got that, and I'll keep learning as we talk.",
}


@dataclass(frozen=True)
class OnboardingQuestion:
    key: str
    importance: float
    prompts: dict[str, str]


# Deliberately short and fixed (not AI-generated) — a first-run interview
# needs to be reliable and can't depend on a browser-automated AI provider
# being reachable. `importance` feeds directly into
# modules.user_profile.domain.ProfileFact.retention_score, but as CORE
# facts these are exempt from eviction regardless (see service_layer.set_fact).
_QUESTIONS: tuple[OnboardingQuestion, ...] = (
    OnboardingQuestion(
        key="name",
        importance=1.0,
        prompts={  # Unused: folded into _GREETING so it isn't asked twice.
            "ru": "Как мне к вам обращаться?",
            "uk": "Як мені до вас звертатися?",
            "en": "What should I call you?",
        },
    ),
    OnboardingQuestion(
        key="city",
        importance=0.8,
        prompts={
            "ru": "В каком городе вы находитесь? Это поможет с напоминаниями и часовым поясом.",
            "uk": "У якому місті ви перебуваєте? Це допоможе з нагадуваннями та часовим поясом.",
            "en": "What city are you in? That helps with reminders and time zone.",
        },
    ),
    OnboardingQuestion(
        key="occupation",
        importance=0.5,
        prompts={
            "ru": "Чем вы обычно занимаетесь, чтобы я могла быть полезнее?",
            "uk": "Чим ви зазвичай займаєтесь, щоб я могла бути кориснішою?",
            "en": "What do you usually work on, so I can be more useful?",
        },
    ),
)


_ASSISTANT_NAME_QUESTION: dict[str, str] = {
    "ru": "Как вы хотите, чтобы я называла себя, если вы спросите моё имя?",
    "uk": "Як ви хочете, щоб я себе називала, якщо ви запитаєте моє ім'я?",
    "en": "What would you like me to call myself, if you ask my name?",
}

_STYLE_QUESTION: dict[str, str] = {
    "ru": (
        "Как вы хотели бы, чтобы я с вами общалась? Варианты: {options}. Можно назвать до трёх "
        "и смешать их — например, «агрессивно и с юмором»."
    ),
    "uk": (
        "Як би ви хотіли, щоб я з вами спілкувалася? Варіанти: {options}. Можна назвати до трьох "
        "і поєднати їх — наприклад, «агресивно і з гумором»."
    ),
    "en": (
        "How would you like me to talk to you? Options: {options}. Name up to three and mix them — "
        "for example, \"aggressive and humorous\"."
    ),
}

_VOICE_INTRO: dict[str, str] = {
    "ru": "Теперь выберем голос. Сейчас я озвучу каждый вариант.",
    "uk": "Тепер оберемо голос. Зараз я озвучу кожен варіант.",
    "en": "Now let's pick a voice. I'll read out each option.",
}

# Always spoken in Russian regardless of onboarding language — the Silero
# voices being previewed only exist as Russian speech (see
# core/voice/silero_tts.py); a preview in another language wouldn't
# actually demonstrate the timbre being chosen.
_VOICE_PREVIEW_TEMPLATE = "Например, вот так звучу я — {name}."

_VOICE_QUESTION: dict[str, str] = {
    "ru": "Какой голос вам понравился больше? Назовите его.",
    "uk": "Який голос вам сподобався більше? Назвіть його.",
    "en": "Which voice did you like best? Say its name.",
}


_STOP_WORD_QUESTION: dict[str, str] = {
    "ru": (
        "Назовите стоп-слово. Скажите его в любой момент, чтобы я перестала реагировать на что-либо, "
        "и повторите то же самое слово ещё раз, чтобы я снова начала вас слушать."
    ),
    "uk": (
        "Назвіть стоп-слово. Скажіть його будь-коли, щоб я перестала реагувати на щось, "
        "і повторіть те саме слово ще раз, щоб я знову почала вас слухати."
    ),
    "en": (
        "Choose a stop word. Say it any time to make me stop responding to anything, "
        "and say the same word again to make me start listening to you again."
    ),
}


def _ask_stop_word(
    tts: TextToSpeech, stt: SpeechToText, settings: VoiceSettings, stop_event: threading.Event, language: str
) -> None:
    if stop_event.is_set():
        return
    tts.speak(_STOP_WORD_QUESTION.get(language, _STOP_WORD_QUESTION["ru"]), language)

    audio = audio_io.record_until_silence(settings, stop_event)
    if audio.size == 0:
        return
    answer = stt.transcribe(audio).text.strip()
    if answer:
        service_layer.set_fact(
            ProfileUnitOfWork(), STOP_WORD_KEY, answer, category=FactCategory.CORE, importance=1.0
        )


def _match_label(spoken: str, labels: list[str]) -> str | None:
    """Fuzzy-matches a short spoken answer against `labels`; returns the
    best match, or None if even the best one falls below
    _LABEL_MATCH_THRESHOLD (better to keep the default than guess wrong)."""
    normalized = spoken.strip().lower()
    if not normalized:
        return None

    best_label: str | None = None
    best_score = 0.0
    for label in labels:
        candidate = label.lower()
        score = SequenceMatcher(None, normalized, candidate).ratio()
        if normalized in candidate or candidate in normalized:
            score = max(score, 0.7)
        if score > best_score:
            best_score = score
            best_label = label
    return best_label if best_score >= _LABEL_MATCH_THRESHOLD else None


# Deliberately much stricter than _LABEL_MATCH_THRESHOLD: _match_label picks
# a single best-scoring label, so competition among candidates filters out
# incidental noise on its own — a low bar is fine there. _match_labels below
# instead keeps *everything* that clears the bar, with no such competition,
# so a loose threshold let unrelated labels through: a single-word answer
# like "вежливо" was also "matching" "агрессивно" and "дружелюбно" purely
# from incidental shared characters. Requiring either a real substring
# match or a near-exact SequenceMatcher ratio avoids that.
_MULTI_LABEL_MATCH_THRESHOLD = 0.75


def _match_labels(spoken: str, labels: list[str], max_count: int) -> list[str]:
    """Like _match_label, but returns every label that plausibly appears
    somewhere in `spoken` (not just the single best one), for questions
    where the answer may name more than one option in the same sentence —
    e.g. mixing communication-style traits ("агрессивно и с юмором").
    Ranked by score, capped at `max_count`."""
    normalized = spoken.strip().lower()
    if not normalized:
        return []

    scored: list[tuple[float, str]] = []
    for label in labels:
        candidate = label.lower()
        score = 1.0 if candidate in normalized else SequenceMatcher(None, normalized, candidate).ratio()
        if score >= _MULTI_LABEL_MATCH_THRESHOLD:
            scored.append((score, label))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [label for _, label in scored[:max_count]]


def _voice_short_name(label: str) -> str:
    # VOICE_OPTIONS labels carry a parenthetical aside for some entries
    # (e.g. "Ксения (Xenia)", "Случайный (звучит по-разному каждый раз)")
    # that isn't something a user would actually say back — match/preview
    # against the leading name only.
    return label.split(" (")[0]


def _ask_assistant_name(
    tts: TextToSpeech, stt: SpeechToText, settings: VoiceSettings, stop_event: threading.Event, language: str
) -> None:
    if stop_event.is_set():
        return
    tts.speak(_ASSISTANT_NAME_QUESTION.get(language, _ASSISTANT_NAME_QUESTION["ru"]), language)

    audio = audio_io.record_until_silence(settings, stop_event)
    if audio.size == 0:
        return
    answer = stt.transcribe(audio).text.strip()
    if answer:
        service_layer.set_fact(
            ProfileUnitOfWork(), ASSISTANT_NAME_KEY, answer, category=FactCategory.CORE, importance=1.0
        )


def _ask_communication_style(
    tts: TextToSpeech, stt: SpeechToText, settings: VoiceSettings, stop_event: threading.Event, language: str
) -> None:
    if stop_event.is_set():
        return
    labels = [style.label for style in COMMUNICATION_STYLES]
    prompt = _STYLE_QUESTION.get(language, _STYLE_QUESTION["ru"]).format(options=", ".join(labels))
    tts.speak(prompt, language)

    audio = audio_io.record_until_silence(settings, stop_event)
    if audio.size == 0:
        return
    spoken = stt.transcribe(audio).text
    matched_labels = _match_labels(spoken, labels, MAX_SELECTED_STYLES)
    if not matched_labels:
        logger.info("Communication style answer %r didn't match a known style; keeping default", spoken)
        return
    matched_keys = [style.key for style in COMMUNICATION_STYLES if style.label in matched_labels]
    service_layer.set_fact(
        ProfileUnitOfWork(), COMMUNICATION_STYLE_KEY, ",".join(matched_keys), category=FactCategory.CORE, importance=1.0
    )


def _ask_voice(
    tts: TextToSpeech, stt: SpeechToText, settings: VoiceSettings, stop_event: threading.Event, language: str
) -> None:
    if stop_event.is_set():
        return
    tts.speak(_VOICE_INTRO.get(language, _VOICE_INTRO["ru"]), language)

    for option in VOICE_OPTIONS:
        if stop_event.is_set():
            return
        preview = _VOICE_PREVIEW_TEMPLATE.format(name=_voice_short_name(option.label))
        tts.speak(preview, "ru", speaker=option.speaker)

    tts.speak(_VOICE_QUESTION.get(language, _VOICE_QUESTION["ru"]), language)
    audio = audio_io.record_until_silence(settings, stop_event)
    if audio.size == 0:
        return
    spoken = stt.transcribe(audio).text
    names = [_voice_short_name(option.label) for option in VOICE_OPTIONS]
    matched_name = _match_label(spoken, names)
    if matched_name is None:
        logger.info("Voice answer %r didn't match a known voice; keeping default", spoken)
        return
    chosen = next(option for option in VOICE_OPTIONS if _voice_short_name(option.label) == matched_name)
    voice_preference.set_selected_speaker(chosen.speaker)


def run_onboarding(settings: VoiceSettings, stop_event: threading.Event) -> None:
    """First-run "getting acquainted" interview: asked once, before the
    assistant waits for the wake word for the first time (see
    core/voice/pipeline.py). Each answer is stored as a CORE fact via
    modules.user_profile.service_layer, so it never gets auto-evicted the
    way incidentally-learned facts do (see C3 / record_episodic_fact)."""
    stt = SpeechToText(settings)
    tts = TextToSpeech(settings)
    language = settings.response_language_override or "ru"
    if language not in _GREETING:
        language = "ru"

    tts.speak(_GREETING[language], language)

    for index, question in enumerate(_QUESTIONS):
        if stop_event.is_set():
            return

        if index > 0:
            prompt = question.prompts.get(language, question.prompts["ru"])
            tts.speak(prompt, language)

        audio = audio_io.record_until_silence(settings, stop_event)
        if audio.size == 0:
            continue

        result = stt.transcribe(audio)
        if index == 0:
            # The name question doubled as the language probe: everything
            # asked after this uses the language actually spoken back.
            decision = resolve_language(result.detected_language, result.language_probability, settings)
            language = resolve_response_language(decision.resolved, settings)
            if language not in _GREETING:
                language = "ru"

        answer = result.text.strip()
        if answer:
            service_layer.set_fact(
                ProfileUnitOfWork(),
                question.key,
                answer,
                category=FactCategory.CORE,
                importance=question.importance,
            )

    _ask_assistant_name(tts, stt, settings, stop_event, language)
    _ask_communication_style(tts, stt, settings, stop_event, language)
    # Runs after the style question on purpose: by the time the voice
    # previews play, get_current_style() (see core/voice/tts.py) already
    # picks up the just-chosen style's prosody, so the user hears their
    # chosen personality's intonation while picking a voice, not the
    # neutral default.
    _ask_voice(tts, stt, settings, stop_event, language)
    _ask_stop_word(tts, stt, settings, stop_event, language)

    service_layer.complete_onboarding(ProfileUnitOfWork())
    tts.speak(_CLOSING.get(language, _CLOSING["ru"]), language)
    logger.info("Onboarding completed")
