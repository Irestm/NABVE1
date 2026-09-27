from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.logger import get_logger
from modules.english_learning import difficulty, link_import, service_layer
from modules.english_learning.assistant_engine import sse
from modules.english_learning.english_assistant import (
    MODULE,
    EnglishAssistant,
    ScreenContext,
    TurnAction,
    TurnOutput,
    safe_error,
)
from modules.english_learning.jobs import card_jobs
from modules.english_learning.repository import AssistantMessage, AssistantThread
from modules.english_learning.srt_parser import SrtParseError
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

router = APIRouter(tags=["english-assistant"])

UI_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork
assistant_factory: Callable[[], EnglishAssistant] = lambda: EnglishAssistant(uow_factory)


class UiSettingModel(BaseModel):
    key: str
    value: Any = None


class UiSettingUpdate(BaseModel):
    value: Any


class ThreadModel(BaseModel):
    id: int
    module: str
    scope: str
    scope_id: int
    created_at: datetime


class ThreadCreate(BaseModel):
    module: Literal["english"] = MODULE
    scope: Literal["library", "episode"]
    scope_id: int = Field(0, ge=0)


class MessageModel(BaseModel):
    id: int
    role: str
    content: str
    meta: dict[str, Any] | None
    ts: datetime


class ContextModel(BaseModel):
    screen: Literal["library", "episode", "learn"] = "library"
    title_id: int | None = None
    episode_id: int | None = None
    card_id: int | None = None
    answered: bool = True
    direction: Literal["en_ru", "ru_en"] = "en_ru"
    mistake_card_ids: list[int] = Field(default_factory=list, max_length=200)


class ActionModel(BaseModel):
    type: Literal["difficulty_check", "difficulty_general"]
    title: str = Field("", max_length=200)
    year: int | None = None
    kind: str | None = None
    title_id: int | None = None


class MessageCreate(BaseModel):
    content: str = Field("", max_length=4000)
    context: ContextModel = Field(default_factory=ContextModel)
    action: ActionModel | None = None
    regenerate: bool = False


class AnalyzeBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    year: int | None = None
    kind: str | None = None


class AnalyzeResult(BaseModel):
    status: Literal["analyzed", "needs_input"]
    title_id: int | None = None
    message: str = ""
    options: list[str] = Field(default_factory=list)


class AboveLevelWord(BaseModel):
    lemma: str
    level: str
    count: int


class GenerateResult(BaseModel):
    jobs: int


def _thread_model(thread: AssistantThread) -> ThreadModel:
    return ThreadModel(
        id=thread.id, module=thread.module, scope=thread.scope, scope_id=thread.scope_id, created_at=thread.created_at
    )


def _message_model(message: AssistantMessage) -> MessageModel:
    return MessageModel(id=message.id, role=message.role, content=message.content, meta=message.meta, ts=message.ts)


@router.get("/ui-settings/{key}", response_model=UiSettingModel)
async def get_ui_setting(key: str = Path(..., pattern=UI_KEY_PATTERN)) -> UiSettingModel:
    def read() -> Any:
        with uow_factory() as uow:
            return uow.ui_settings.get(key)

    return UiSettingModel(key=key, value=await asyncio.to_thread(read))


@router.put("/ui-settings/{key}", response_model=UiSettingModel)
async def put_ui_setting(body: UiSettingUpdate, key: str = Path(..., pattern=UI_KEY_PATTERN)) -> UiSettingModel:
    def write() -> None:
        with uow_factory() as uow:
            uow.ui_settings.set(key, body.value)
            uow.commit()

    await asyncio.to_thread(write)
    return UiSettingModel(key=key, value=body.value)


@router.get("/assistant/threads", response_model=list[ThreadModel])
async def list_threads(module: str = MODULE, scope: str = "library", scope_id: int = 0) -> list[ThreadModel]:
    def read() -> list[AssistantThread]:
        with uow_factory() as uow:
            return uow.assistant.list_threads(module, scope, scope_id)

    return [_thread_model(thread) for thread in await asyncio.to_thread(read)]


@router.post("/assistant/threads", response_model=ThreadModel)
async def create_thread(body: ThreadCreate) -> ThreadModel:
    def write() -> AssistantThread:
        with uow_factory() as uow:
            thread = uow.assistant.create_thread(body.module, body.scope, body.scope_id)
            uow.commit()
            return thread

    return _thread_model(await asyncio.to_thread(write))


def _require_thread(uow: EnglishUnitOfWork, thread_id: int) -> AssistantThread:
    thread = uow.assistant.get_thread(thread_id)
    if thread is None:
        raise LookupError(f"Тред {thread_id} не найден")
    return thread


@router.get("/assistant/threads/{thread_id}/messages", response_model=list[MessageModel])
async def list_messages(thread_id: int) -> list[MessageModel]:
    def read() -> list[AssistantMessage]:
        with uow_factory() as uow:
            _require_thread(uow, thread_id)
            return uow.assistant.messages(thread_id)

    try:
        return [_message_model(message) for message in await asyncio.to_thread(read)]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _prepare_turn(thread_id: int, body: MessageCreate) -> list[AssistantMessage]:
    with uow_factory() as uow:
        _require_thread(uow, thread_id)
        messages = uow.assistant.messages(thread_id)
        if body.regenerate:
            last_user = max((message.id for message in messages if message.role == "user"), default=None)
            for message in messages:
                if message.role == "assistant" and (last_user is None or message.id > last_user):
                    uow.assistant.delete_message(message.id)
        elif body.content.strip():
            uow.assistant.add_message(thread_id, "user", body.content.strip())
        elif body.action is None:
            raise ValueError("Пустое сообщение")
        uow.commit()
        return uow.assistant.messages(thread_id)


def _save_reply(thread_id: int, output: TurnOutput, stopped: bool) -> int | None:
    if not output.text and not output.meta:
        return None
    meta = dict(output.meta)
    if stopped:
        meta["stopped"] = True
    with uow_factory() as uow:
        message = uow.assistant.add_message(thread_id, "assistant", output.text, meta or None)
        uow.commit()
        return message.id


@router.post("/assistant/threads/{thread_id}/messages")
async def post_message(thread_id: int, body: MessageCreate, request: Request) -> StreamingResponse:
    try:
        history = await asyncio.to_thread(_prepare_turn, thread_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assistant = assistant_factory()
    context = ScreenContext(**body.context.model_dump())

    async def events() -> AsyncIterator[str]:
        output = TurnOutput()
        stopped = False
        failed = False
        try:
            if body.action is not None:
                iterator = assistant.difficulty(TurnAction(**body.action.model_dump()), output)
            else:
                iterator = assistant.chat(history, context, output)
            async for event in iterator:
                if await request.is_disconnected():
                    stopped = True
                    break
                yield event
        except asyncio.CancelledError:
            stopped = True
            raise
        except Exception as exc:
            logger.exception("Assistant turn failed in thread %d", thread_id)
            failed = True
            yield sse("error", {"message": safe_error(exc)})
        finally:
            message_id = _save_reply(thread_id, output, stopped)
        if not stopped:
            yield sse("done", {"message_id": message_id, "failed": failed})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/assistant/analyze", response_model=AnalyzeResult)
async def analyze_title(body: AnalyzeBody) -> AnalyzeResult:
    try:
        outcome = await link_import.import_by_title(body.title, body.kind, body.year)
    except (SrtParseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(outcome, link_import.NeedsInput):
        options = [
            f"{option.name} ({option.year}, {'фильм' if option.kind == 'movie' else 'сериал'})" for option in outcome.options
        ]
        problems = "; ".join(outcome.problems)
        return AnalyzeResult(
            status="needs_input",
            message=outcome.message + (f" {problems}" if problems else ""),
            options=options,
        )
    return AnalyzeResult(status="analyzed", title_id=outcome.title.id, message=outcome.title.display_name)


@router.post("/assistant/titles/{title_id}/generate", response_model=GenerateResult)
async def generate_title_cards(title_id: int) -> GenerateResult:
    def episodes() -> list[int]:
        with uow_factory() as uow:
            if uow.titles.get(title_id) is None:
                raise LookupError(f"Тайтл {title_id} не найден")
            return [episode.id for episode in uow.episodes.list_for_title(title_id) if episode.id is not None]

    try:
        ids = await asyncio.to_thread(episodes)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for episode_id in ids:
        card_jobs.start(episode_id)
    return GenerateResult(jobs=len(ids))


@router.get("/assistant/titles/{title_id}/above-level", response_model=list[AboveLevelWord])
async def above_level(title_id: int) -> list[AboveLevelWord]:
    level = (await asyncio.to_thread(service_layer.get_module_settings, uow_factory)).user_level
    words = await asyncio.to_thread(difficulty.words_above_level, title_id, level, uow_factory)
    return [AboveLevelWord(lemma=lemma, level=word_level, count=count) for lemma, word_level, count in words]
