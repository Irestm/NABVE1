from __future__ import annotations

import threading
from dataclasses import dataclass

from core.logger import get_logger
from core.voice import audio_io
from core.voice.config import VoiceSettings
from core.voice.language import resolve_language, resolve_response_language
from core.voice.stt import SpeechToText
from core.voice.tts import TextToSpeech
from modules.user_profile import service_layer
from modules.user_profile.domain import FactCategory
from modules.user_profile.uow import ProfileUnitOfWork

logger = get_logger(__name__)

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
# Deliberately just the name — city/occupation/assistant name/stop
# word/voice used to be asked here too, but the interview is meant to be
# minimal (name, then a mention that the rest is set manually, done); every
# other field can still be picked up later as an ordinary episodic fact or
# set explicitly through the Настройки/Профиль panel (see
# _MANUAL_SETUP_NOTE below), and communication style is set via the
# Личность settings panel instead of a voice questionnaire.
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
)


# Onboarding used to also ask for the assistant's own name, preview every
# TTS voice out loud, and ask for a stop word — dropped in favor of a single
# mention that all of that is configurable afterward, since walking through
# four back-to-back voice questions made the interview noticeably longer
# than just getting the user's name warranted. Every one of those fields is
# already reachable anytime through the Настройки/Профиль panel (assistant
# name and stop word via frontend/src/components/SettingsPanel.tsx's
# profile_get/profile_set calls; voice via its own voice list + set
# endpoint in core/voice/web_pipeline.py).
_MANUAL_SETUP_NOTE: dict[str, str] = {
    "ru": (
        "Моё имя, стоп-слово и голос можно будет задать в любой момент в Настройках, "
        "во вкладке Профиль."
    ),
    "uk": (
        "Моє ім'я, стоп-слово і голос можна буде задати будь-коли в Налаштуваннях, "
        "на вкладці Профіль."
    ),
    "en": ("You can set my name, a stop word, and my voice anytime in Settings, under Profile."),
}


def _mention_manual_setup(tts: TextToSpeech, stop_event: threading.Event, language: str) -> None:
    if stop_event.is_set():
        return
    tts.speak(_MANUAL_SETUP_NOTE.get(language, _MANUAL_SETUP_NOTE["ru"]), language)


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

    _mention_manual_setup(tts, stop_event, language)

    service_layer.complete_onboarding(ProfileUnitOfWork())
    tts.speak(_CLOSING.get(language, _CLOSING["ru"]), language)
    logger.info("Onboarding completed")
