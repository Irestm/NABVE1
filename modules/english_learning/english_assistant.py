from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from core.logger import get_logger
from modules.ai_bridge.providers.base import AllProvidersFailed, ChatMessage
from modules.english_learning import assistant_engine, difficulty, service_layer
from modules.english_learning.assistant_engine import AnswerGuard, sse
from modules.english_learning.domain import CEFR_LEVELS, Card
from modules.english_learning.repository import AssistantMessage
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

MODULE = "english"
HISTORY_LIMIT = 12
CONTEXT_CARD_LIMIT = 80
MAX_TOKENS = 1200
GENERAL_KNOWLEDGE_NOTE = "Оценка по общим знаниям, без анализа субтитров — может быть неточной."

Screen = Literal["library", "episode", "learn"]
UowFactory = Callable[[], EnglishUnitOfWork]
StreamFn = Callable[[list[ChatMessage], int], AsyncIterator[str]]


@dataclass(frozen=True)
class ScreenContext:
    screen: Screen = "library"
    title_id: int | None = None
    episode_id: int | None = None
    card_id: int | None = None
    answered: bool = True
    direction: Literal["en_ru", "ru_en"] = "en_ru"
    mistake_card_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class TurnAction:
    type: Literal["difficulty_check", "difficulty_general"]
    title: str = ""
    year: int | None = None
    kind: str | None = None
    title_id: int | None = None


def _card_line(card: Card, *, with_answer: bool = True) -> str:
    level = card.cefr or "без уровня"
    kind = "" if card.kind == "word" else f", {card.kind.replace('_', ' ')}"
    sense = f" ({card.sense_label})" if card.sense_label else ""
    answer = f" — {', '.join(card.translations_ru)}" if with_answer else ""
    return f"- {card.word}{sense}{answer} [{level}{kind}]"


def _stats_line(stats: Any) -> str:
    if stats is None:
        return "статистика не посчитана"
    top = ", ".join(lemma for lemma, _ in stats.top_above_b2[:8]) or "нет"
    return (
        f"{stats.token_count} слов, темп {stats.words_per_minute:.0f} слов/мин, "
        f"идиом/сленга {stats.expressions_per_1000:.1f} на 1000, неанглийских реплик {stats.non_english_share * 100:.0f}%, "
        f"частые слова выше B2: {top}"
    )


def active_question(context: ScreenContext) -> bool:
    return context.screen == "learn" and context.card_id is not None and not context.answered


def build_context(context: ScreenContext, uow_factory: UowFactory = EnglishUnitOfWork) -> tuple[str, list[str]]:
    settings = service_layer.get_module_settings(uow_factory)
    lines: list[str] = [f"Уровень пользователя: {settings.user_level}."]
    forbidden: list[str] = []
    with uow_factory() as uow:
        if context.screen == "library":
            lines.append("Экран: список папок (библиотека тайтлов).")
            for title in uow.titles.list_all():
                if title.id is None:
                    continue
                episodes = uow.episodes.list_for_title(title.id)
                kind = "фильм" if title.kind == "movie" else "сериал"
                lines.append(f"* {title.display_name} ({kind}), эпизодов/частей: {len(episodes)}")
                for episode in episodes[:6]:
                    if episode.id is not None:
                        lines.append(f"  - {episode.code}: {_stats_line(uow.stats.get(episode.id))}")
            return "\n".join(lines), forbidden

        episode = uow.episodes.get(context.episode_id) if context.episode_id is not None else None
        title = uow.titles.get(episode.title_id) if episode is not None else None
        if episode is None or title is None or episode.id is None:
            lines.append("Экран: раздел английского, конкретный эпизод не выбран.")
            return "\n".join(lines), forbidden
        place = episode.code if title.kind == "series" else f"фильм, {episode.code}"
        lines.append(f"Тайтл: {title.display_name} ({'фильм' if title.kind == 'movie' else 'сериал'}), {place}.")
        lines.append(f"Статистика: {_stats_line(uow.stats.get(episode.id))}.")
        cards = uow.cards.list_for_episode(episode.id)
        filter_settings = service_layer.effective_filter(uow, title.id, episode.id)
        visible = [card for card in cards if filter_settings.admits(card.kind, card.cefr)]

        if context.screen == "episode":
            lines.append(f"Экран: список карточек эпизода ({len(visible)} с учётом фильтра уровней).")
            lines.extend(_card_line(card) for card in visible[:CONTEXT_CARD_LIMIT])
            return "\n".join(lines), forbidden

        lines.append("Экран: режим заучивания (Learn).")
        current = uow.cards.get(context.card_id) if context.card_id is not None else None
        hidden = current is not None and active_question(context) and not settings.allow_answer_hints
        if current is not None:
            direction = "EN→RU" if context.direction == "en_ru" else "RU→EN"
            if hidden:
                prompt = current.word if context.direction == "en_ru" else ", ".join(current.translations_ru)
                lines.append(
                    f"Текущий вопрос ({direction}, ответ ещё не дан): «{prompt}». Пример из серии: {current.example}"
                )
                forbidden = (
                    list(current.translations_ru)
                    if context.direction == "en_ru"
                    else [value for value in (current.word, current.lemma, current.surface_form) if value]
                )
            else:
                lines.append(f"Текущая карточка ({direction}): {_card_line(current)}. Пример: {current.example}")
        mistakes = [
            card
            for card_id in dict.fromkeys(context.mistake_card_ids)
            if (card := uow.cards.get(card_id)) is not None and (not hidden or card.id != context.card_id)
        ]
        if mistakes:
            lines.append("Ошибки за сессию (сложные слова):")
            lines.extend(_card_line(card) for card in mistakes[:20])
    return "\n".join(lines), forbidden


def system_prompt(context_text: str, *, hide_answer: bool) -> str:
    hint_rule = (
        "Сейчас идёт активный вопрос теста. НЕ называй перевод или ответ на текущий вопрос ни прямо, ни по буквам, "
        "ни намёком-синонимом. Можно объяснить употребление, дать ассоциацию, пример из другой ситуации, подсказку о "
        "части речи. Если просят ответ — вежливо откажи и предложи сначала ответить."
        if hide_answer
        else "Ответы на карточки можно объяснять полностью."
    )
    return (
        "Ты — ассистент по изучению английского языка в приложении NABVE (Jarvis), раздел «Английский по сериалам и "
        "фильмам». Отвечай по-русски, английские слова, примеры и термины пиши по-английски. Используй Markdown "
        "(списки, таблицы, выделение), будь краток и конкретен. Отвечай только в рамках изучения английского и "
        "контекста ниже; на посторонние темы вежливо верни разговор к английскому.\n\n"
        f"{hint_rule}\n\n"
        "Особые команды — в этих случаях верни ТОЛЬКО JSON без какого-либо текста:\n"
        '1) пользователь спрашивает, справится ли он с сериалом или фильмом, потянет ли его, насколько он сложный: '
        '{"action":"difficulty_check","title":"<официальное английское название>","year":null или год,'
        '"kind":"series|movie|unknown"}. Если название не указано и на экране открыт тайтл — используй его.\n'
        '2) пользователь сообщает свой уровень английского или просит его поменять: {"action":"set_level","level":"A1..C2"}.\n\n'
        f"Контекст экрана:\n{context_text}"
    )


def _history(messages: list[AssistantMessage]) -> list[ChatMessage]:
    recent = [message for message in messages if message.role in ("user", "assistant") and message.content.strip()]
    return [{"role": message.role, "content": message.content} for message in recent[-HISTORY_LIMIT:]]  # type: ignore[misc]


@dataclass
class TurnOutput:
    text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _default_stream(messages: list[ChatMessage], max_tokens: int) -> AsyncIterator[str]:
    return assistant_engine.stream_reply(messages, max_tokens)


def _verdict_prompt(report: difficulty.DifficultyReport) -> str:
    data = json.dumps(report.as_dict(), ensure_ascii=False)
    source = (
        f"по субтитрам {report.episodes_analyzed} эпизод(ов)"
        if report.kind == "series"
        else f"по субтитрам фильма ({report.episodes_analyzed} част.)"
    )
    return (
        "Ты честно оцениваешь, подходит ли тайтл пользователю для просмотра на английском. Используй ТОЛЬКО данные "
        "ниже, ничего не додумывай и не приукрашивай. Ответ по-русски, английские слова — по-английски, Markdown.\n"
        f"Первая строка — ровно «**{report.verdict}** — » и одна фраза почему.\n"
        f"Затем конкретика: покрытие {report.coverage * 100:.1f}% (доля слов, которые пользователь уровня "
        f"{report.user_level} скорее всего знает), темп речи, сколько слов выше его уровня, 3–5 примеров таких слов "
        "из examples, особенности из factors (сленг, скорость, реплики на другом языке, специальная лексика).\n"
        f"Обязательно укажи источник: «{source}».\n"
        + ("Выборка — одна серия: скажи, что в других сезонах сложность может отличаться.\n" if report.small_sample else "")
        + "Дай практичный совет по результату: смотреть с английскими субтитрами, с какого сезона начать, сначала "
        "пройти карточки части, или предложи более подходящий по уровню тайтл того же жанра (с пометкой, что это "
        "по общим знаниям). Если данные говорят «трудно» — так и скажи.\n\n"
        f"Данные: {data}"
    )


def _general_prompt(action: TurnAction, user_level: str) -> str:
    what = action.title + (f" ({action.year})" if action.year else "")
    return (
        "Пользователь спрашивает, справится ли он с тайтлом на английском. Субтитры НЕ анализировались. Оцени по "
        f"общим знаниям о «{what}» для уровня {user_level}: первая строка — «**Подходит**», «**Подходит с усилием**» "
        "или «**Пока рано**» и одна фраза почему; затем особенности речи (сленг, акцент, темп, жанровая лексика) и "
        "практичный совет. Не утверждай, что анализ субтитров был. Не повторяй пометку про общие знания — она уже "
        "выведена. Ответ по-русски, английские слова — по-английски, Markdown."
    )


class EnglishAssistant:
    def __init__(self, uow_factory: UowFactory = EnglishUnitOfWork, stream: StreamFn | None = None) -> None:
        self._uow_factory = uow_factory
        self._stream = stream or _default_stream

    async def _emit_stream(
        self, messages: list[ChatMessage], output: TurnOutput, guard: AnswerGuard | None = None
    ) -> AsyncIterator[str]:
        async for delta in self._stream(messages, MAX_TOKENS):
            text = guard.feed(delta) if guard else delta
            if text:
                output.text += text
                yield sse("delta", {"text": text})
        if guard:
            tail = guard.flush()
            if tail:
                output.text += tail
                yield sse("delta", {"text": tail})

    async def _emit_text(self, text: str, output: TurnOutput) -> AsyncIterator[str]:
        output.text += text
        yield sse("delta", {"text": text})

    async def chat(
        self, history: list[AssistantMessage], context: ScreenContext, output: TurnOutput
    ) -> AsyncIterator[str]:
        context_text, forbidden = build_context(context, self._uow_factory)
        settings = service_layer.get_module_settings(self._uow_factory)
        hide = bool(forbidden) and not settings.allow_answer_hints
        messages: list[ChatMessage] = [
            {"role": "system", "content": system_prompt(context_text, hide_answer=hide)},
            *_history(history),
        ]
        guard = AnswerGuard(forbidden) if hide else None
        buffered = ""
        mode: bool | None = None
        async for delta in self._stream(messages, MAX_TOKENS):
            if mode is None:
                buffered += delta
                mode = assistant_engine.looks_like_json(buffered)
                if mode is False:
                    text = guard.feed(buffered) if guard else buffered
                    buffered = ""
                    if text:
                        output.text += text
                        yield sse("delta", {"text": text})
                continue
            if mode:
                buffered += delta
                continue
            text = guard.feed(delta) if guard else delta
            if text:
                output.text += text
                yield sse("delta", {"text": text})
        if mode:
            action = assistant_engine.parse_action(buffered)
            if action is not None:
                async for event in self.handle_action(action, context, output):
                    yield event
                return
            text = guard.feed(buffered) if guard else buffered
            if text:
                output.text += text
                yield sse("delta", {"text": text})
        elif mode is None and buffered:
            text = guard.feed(buffered) if guard else buffered
            output.text += text
            yield sse("delta", {"text": text})
        if guard:
            tail = guard.flush()
            if tail:
                output.text += tail
                yield sse("delta", {"text": tail})

    async def handle_action(
        self, action: dict[str, Any], context: ScreenContext, output: TurnOutput
    ) -> AsyncIterator[str]:
        if action.get("action") == "set_level":
            level = str(action.get("level") or "").upper()
            if level not in CEFR_LEVELS:
                async for event in self._emit_text("Не понял уровень — укажите от A1 до C2.", output):
                    yield event
                return
            service_layer.save_module_settings(user_level=level, uow_factory=self._uow_factory)
            output.meta["user_level"] = level
            async for event in self._emit_text(f"Запомнил: ваш уровень английского — **{level}**.", output):
                yield event
            return
        title = str(action.get("title") or "").strip()
        year = action.get("year") if isinstance(action.get("year"), int) else None
        kind = str(action.get("kind") or "unknown")
        if not title and context.episode_id is not None:
            with self._uow_factory() as uow:
                episode = uow.episodes.get(context.episode_id)
                stored = uow.titles.get(episode.title_id) if episode is not None else None
            if stored is not None:
                title, year, kind = stored.name, stored.year, stored.kind
        async for event in self.difficulty(TurnAction("difficulty_check", title, year, kind), output):
            yield event

    async def difficulty(self, action: TurnAction, output: TurnOutput) -> AsyncIterator[str]:
        settings = service_layer.get_module_settings(self._uow_factory)
        if action.type == "difficulty_general":
            async for event in self.general_answer(action, settings.user_level, output):
                yield event
            return
        if not action.title and action.title_id is None:
            async for event in self._emit_text("О каком сериале или фильме речь? Напишите название.", output):
                yield event
            return
        report = difficulty.title_report(
            action.title, action.year, action.kind, settings.user_level, self._uow_factory, title_id=action.title_id
        )
        if report is None:
            offer = {"title": action.title, "year": action.year, "kind": action.kind or "unknown"}
            output.meta["offer"] = offer
            yield sse("offer", offer)
            text = (
                f"«{action.title}» ещё нет в вашей библиотеке, поэтому честно посчитать сложность пока не по чему.\n\n"
                "Могу **проанализировать** субтитры (первую серию сериала или фильм целиком) — это как импорт, но без "
                "создания карточек. Учтите: скачивание тратит одну загрузку из дневного лимита OpenSubtitles.\n\n"
                "Или отвечу **по общим знаниям** — это будет менее точно."
            )
            async for event in self._emit_text(text, output):
                yield event
            return
        card = report.as_dict()
        output.meta["difficulty"] = card
        yield sse("difficulty", card)
        messages: list[ChatMessage] = [
            {"role": "system", "content": _verdict_prompt(report)},
            {"role": "user", "content": f"Справлюсь ли я с «{report.title}»?"},
        ]
        head = ""
        checked = False
        async for delta in self._stream(messages, MAX_TOKENS):
            if checked:
                output.text += delta
                yield sse("delta", {"text": delta})
                continue
            head += delta
            if "\n" not in head and len(head) < 80:
                continue
            checked = True
            if report.verdict not in head.split("\n", 1)[0]:
                prefix = f"**{report.verdict}**\n\n"
                output.text += prefix
                yield sse("delta", {"text": prefix})
            output.text += head
            yield sse("delta", {"text": head})
        if not checked:
            if report.verdict not in head:
                head = f"**{report.verdict}**\n\n{head}"
            output.text += head
            yield sse("delta", {"text": head})

    async def general_answer(self, action: TurnAction, user_level: str, output: TurnOutput) -> AsyncIterator[str]:
        output.meta["source"] = "general_knowledge"
        async for event in self._emit_text(f"_{GENERAL_KNOWLEDGE_NOTE}_\n\n", output):
            yield event
        messages: list[ChatMessage] = [
            {"role": "system", "content": _general_prompt(action, user_level)},
            {"role": "user", "content": f"Справлюсь ли я с «{action.title}»?"},
        ]
        async for event in self._emit_stream(messages, output):
            yield event


def safe_error(exc: BaseException) -> str:
    if isinstance(exc, AllProvidersFailed):
        return "Ни один ИИ-провайдер не ответил — проверьте раздел «Провайдеры ИИ»."
    return "Не удалось получить ответ ассистента."
