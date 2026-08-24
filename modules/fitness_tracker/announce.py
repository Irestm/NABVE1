from __future__ import annotations

# Fixed voice-response strings for modules/fitness_tracker — same ru/uk/en
# shape as modules/os_agent/announce.py: this is product-facing TTS output
# driven by core/voice/pipeline.py's response_language, unrelated to this
# assistant session's own separate "reply to the user only in Russian" rule.

_CONTEXT_ACTIVATED = {
    "ru": "Хорошо, перешёл в модуль фитнеса, слушаю.",
    "uk": "Добре, перейшов у модуль фітнесу, слухаю.",
    "en": "Okay, switched to fitness mode, listening.",
}
_CONTEXT_DEACTIVATED = {
    "ru": "Вышел из режима фитнеса.",
    "uk": "Вийшов з режиму фітнесу.",
    "en": "Left fitness mode.",
}
_SEX_LABELS = {
    "ru": {"male": "мужской", "female": "женский"},
    "uk": {"male": "чоловіча", "female": "жіноча"},
    "en": {"male": "male", "female": "female"},
}
_WEIGHT_RECORDED = {
    "ru": "Записал, твой вес теперь {value:g} килограмм.",
    "uk": "Записав, твоя вага тепер {value:g} кілограм.",
    "en": "Got it, your weight is now {value:g} kilograms.",
}
_HEIGHT_RECORDED = {
    "ru": "Записал, твой рост теперь {value:g} сантиметров.",
    "uk": "Записав, твій зріст тепер {value:g} сантиметрів.",
    "en": "Got it, your height is now {value:g} centimeters.",
}
_AGE_RECORDED = {
    "ru": "Записал, тебе {value:g} лет.",
    "uk": "Записав, тобі {value:g} років.",
    "en": "Got it, you're {value:g} years old.",
}
_SEX_RECORDED = {
    "ru": "Записал, пол — {value}.",
    "uk": "Записав, стать — {value}.",
    "en": "Got it, sex — {value}.",
}
_MEASUREMENT_RECORDED = {
    "ru": "Записал замер: {body_part} — {value:g} сантиметров.",
    "uk": "Записав замір: {body_part} — {value:g} сантиметрів.",
    "en": "Got it, {body_part} measurement — {value:g} centimeters.",
}
_GOAL_RECORDED = {
    "ru": "Записал цель: {description}.",
    "uk": "Записав ціль: {description}.",
    "en": "Got it, goal recorded: {description}.",
}
_MEAL_LOGGED_WITH_CALORIES = {
    "ru": "Записал приём пищи: {description}, примерно {calories:g} килокалорий.",
    "uk": "Записав прийом їжі: {description}, приблизно {calories:g} кілокалорій.",
    "en": "Logged the meal: {description}, about {calories:g} kilocalories.",
}
_MEAL_LOGGED_WITHOUT_CALORIES = {
    "ru": "Записал приём пищи: {description}.",
    "uk": "Записав прийом їжі: {description}.",
    "en": "Logged the meal: {description}.",
}
_MEAL_ANALYSIS_FAILED = {
    "ru": "Записал приём пищи как есть — не удалось оценить калорийность: {reason}",
    "uk": "Записав прийом їжі як є — не вдалося оцінити калорійність: {reason}",
    "en": "Logged the meal as-is — couldn't estimate calories: {reason}",
}
_CLARIFY_NUMBER = {
    "ru": "Уточни, пожалуйста, число — не расслышал значение.",
    "uk": "Уточни, будь ласка, число — не розчув значення.",
    "en": "Could you repeat the number? I didn't catch the value.",
}
_CLARIFY_BODY_PART = {
    "ru": "Какую часть тела замерить?",
    "uk": "Яку частину тіла заміряти?",
    "en": "Which body part should I measure?",
}
_NOT_UNDERSTOOD_IN_CONTEXT = {
    "ru": "Не совсем понял. Можешь переформулировать?",
    "uk": "Не зовсім зрозумів. Можеш переформулювати?",
    "en": "I didn't quite catch that. Could you rephrase?",
}
_API_KEY_HINT = {
    "ru": "Кстати, точность таких ответов можно повысить, подключив свой API-ключ в настройках.",
    "uk": "До речі, точність таких відповідей можна підвищити, підключивши свій API-ключ у налаштуваннях.",
    "en": "By the way, you can get more accurate answers by adding your own API key in Settings.",
}


def _pick(table: dict[str, str], language: str) -> str:
    return table.get(language, table["ru"])


def context_activated_text(language: str) -> str:
    return _pick(_CONTEXT_ACTIVATED, language)


def context_deactivated_text(language: str) -> str:
    return _pick(_CONTEXT_DEACTIVATED, language)


def weight_recorded_text(value: float, language: str) -> str:
    return _pick(_WEIGHT_RECORDED, language).format(value=value)


def height_recorded_text(value: float, language: str) -> str:
    return _pick(_HEIGHT_RECORDED, language).format(value=value)


def age_recorded_text(value: float, language: str) -> str:
    return _pick(_AGE_RECORDED, language).format(value=value)


def sex_recorded_text(sex: str, language: str) -> str:
    label = _SEX_LABELS.get(language, _SEX_LABELS["ru"]).get(sex, sex)
    return _pick(_SEX_RECORDED, language).format(value=label)


def measurement_recorded_text(body_part: str, value: float, language: str) -> str:
    return _pick(_MEASUREMENT_RECORDED, language).format(body_part=body_part, value=value)


def goal_recorded_text(description: str, language: str) -> str:
    return _pick(_GOAL_RECORDED, language).format(description=description)


def meal_logged_text(description: str, calories: float | None, language: str) -> str:
    if calories is None:
        return _pick(_MEAL_LOGGED_WITHOUT_CALORIES, language).format(description=description)
    return _pick(_MEAL_LOGGED_WITH_CALORIES, language).format(description=description, calories=calories)


def meal_analysis_failed_text(reason: str, language: str) -> str:
    return _pick(_MEAL_ANALYSIS_FAILED, language).format(reason=reason)


def clarify_number_text(language: str) -> str:
    return _pick(_CLARIFY_NUMBER, language)


def clarify_body_part_text(language: str) -> str:
    return _pick(_CLARIFY_BODY_PART, language)


def not_understood_in_context_text(language: str) -> str:
    return _pick(_NOT_UNDERSTOOD_IN_CONTEXT, language)


def api_key_hint_text(language: str) -> str:
    return _pick(_API_KEY_HINT, language)
