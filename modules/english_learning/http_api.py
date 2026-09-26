from __future__ import annotations

import asyncio

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.secret_store import SecretStoreUnavailableError
from modules.english_learning import credentials, link_import, service_layer
from modules.english_learning.cefr import CEFRJ_ATTRIBUTION, CefrUnavailableError
from modules.english_learning.domain import Card, Episode, EpisodeWord
from modules.english_learning.jobs import CardJob, card_jobs
from modules.english_learning.lemmatizer import LemmatizerUnavailableError
from modules.english_learning.service_layer import ImportResult
from modules.english_learning.srt_parser import SrtParseError

router = APIRouter(prefix="/api/english", tags=["english"])

MAX_SRT_BYTES = 5 * 1024 * 1024


class EpisodeModel(BaseModel):
    id: int
    series_id: int
    season: int
    episode: int
    code: str
    title: str | None
    source: str
    word_count: int = 0
    card_count: int = 0
    display_name: str = ""


class SeriesModel(BaseModel):
    id: int
    title: str
    imdb_id: str | None
    episodes: list[EpisodeModel]


class WordModel(BaseModel):
    id: int | None
    lemma: str
    pos: str
    cefr: str | None
    category: str
    count: int
    example: str
    timestamp_ms: int
    surface: str


class CardModel(BaseModel):
    id: int
    episode_id: int
    word: str
    lemma: str
    pos: str
    cefr: str | None
    translations_ru: list[str]
    definition_en: str
    example: str
    timestamp_ms: int
    category: str


class JobModel(BaseModel):
    id: int
    episode_id: int
    state: str
    done: int
    total: int
    created: int
    skipped: int
    error: str | None


class ImportResponse(BaseModel):
    series: SeriesModel
    episode: EpisodeModel
    words: list[WordModel]
    job: JobModel | None = None


class LibraryResponse(BaseModel):
    series: list[SeriesModel]
    cefr_attribution: str


def _episode_model(
    episode: Episode, word_count: int = 0, card_count: int = 0, display_name: str = ""
) -> EpisodeModel:
    if episode.id is None:
        raise ValueError("Episode has no id")
    return EpisodeModel(
        id=episode.id,
        series_id=episode.series_id,
        season=episode.season,
        episode=episode.episode,
        code=episode.code,
        title=episode.title,
        source=episode.source,
        word_count=word_count,
        card_count=card_count,
        display_name=display_name,
    )


def _card_model(card: Card) -> CardModel:
    if card.id is None:
        raise ValueError("Card has no id")
    return CardModel(
        id=card.id,
        episode_id=card.episode_id,
        word=card.word,
        lemma=card.lemma,
        pos=card.pos,
        cefr=card.cefr,
        translations_ru=card.translations_ru,
        definition_en=card.definition_en,
        example=card.example,
        timestamp_ms=card.timestamp_ms,
        category=card.category,
    )


def _job_model(job: CardJob) -> JobModel:
    return JobModel(
        id=job.id,
        episode_id=job.episode_id,
        state=job.state,
        done=job.done,
        total=job.total,
        created=job.created,
        skipped=job.skipped,
        error=job.error,
    )


def _word_model(word: EpisodeWord) -> WordModel:
    return WordModel(
        id=word.id,
        lemma=word.lemma,
        pos=word.pos,
        cefr=word.cefr,
        category=word.category,
        count=word.count,
        example=word.example,
        timestamp_ms=word.timestamp_ms,
        surface=word.surface,
    )


def _import_response(result: ImportResult) -> ImportResponse:
    job = card_jobs.start(result.episode.id) if result.episode.id is not None and result.words else None
    return ImportResponse(
        series=SeriesModel(
            id=result.series.id or 0, title=result.series.title, imdb_id=result.series.imdb_id, episodes=[]
        ),
        episode=_episode_model(result.episode, word_count=len(result.words)),
        words=[_word_model(word) for word in result.words],
        job=_job_model(job) if job is not None else None,
    )


@router.get("/library", response_model=LibraryResponse)
async def get_library() -> LibraryResponse:
    summaries = await asyncio.to_thread(service_layer.library)
    return LibraryResponse(
        series=[
            SeriesModel(
                id=summary.series.id or 0,
                title=summary.series.title,
                imdb_id=summary.series.imdb_id,
                episodes=[
                    _episode_model(item.episode, item.word_count, item.card_count, item.display_name)
                    for item in summary.episodes
                ],
            )
            for summary in summaries
        ],
        cefr_attribution=CEFRJ_ATTRIBUTION,
    )


@router.get("/episodes/{episode_id}/words", response_model=list[WordModel])
async def get_episode_words(episode_id: int) -> list[WordModel]:
    try:
        words = await asyncio.to_thread(service_layer.episode_words, episode_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_word_model(word) for word in words]


@router.post("/import/srt", response_model=ImportResponse)
async def import_srt(
    series_title: str = Form(..., min_length=1),
    season: int = Form(..., ge=0),
    episode: int = Form(..., ge=0),
    episode_title: str | None = Form(None),
    file: UploadFile = File(...),
) -> ImportResponse:
    raw = await file.read(MAX_SRT_BYTES + 1)
    if len(raw) > MAX_SRT_BYTES:
        raise HTTPException(status_code=413, detail="Файл субтитров слишком большой")
    try:
        result = await asyncio.to_thread(
            service_layer.import_srt_file,
            series_title=series_title,
            season=season,
            episode=episode,
            raw=raw,
            episode_title=episode_title,
        )
    except (SrtParseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CefrUnavailableError, LemmatizerUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _import_response(result)


class LinkImportBody(BaseModel):
    url: str = Field(..., min_length=4, max_length=2048)
    series_title: str | None = None
    season: int | None = Field(None, ge=0)
    episode: int | None = Field(None, ge=0)
    tmdb_id: int | None = None
    allow_ai_guess: bool = False


class GuessModel(BaseModel):
    series_title: str | None
    season: int | None
    episode: int | None
    is_youtube: bool
    page_title: str | None


class ShowOptionModel(BaseModel):
    tmdb_id: int
    name: str
    year: int | None


class NeedsInputModel(BaseModel):
    kind: str
    message: str
    guess: GuessModel
    missing: list[str]
    options: list[ShowOptionModel]
    alternatives: list[str]
    problems: list[str]


class LinkImportResponse(BaseModel):
    status: Literal["imported", "needs_input"]
    imported: ImportResponse | None = None
    needs_input: NeedsInputModel | None = None


class CredentialsStatusModel(BaseModel):
    tmdb: bool
    opensubtitles_api_key: bool
    opensubtitles_account: bool


class CredentialsUpdate(BaseModel):
    tmdb_api_key: str | None = None
    opensubtitles_api_key: str | None = None
    opensubtitles_username: str | None = None
    opensubtitles_password: str | None = None


def _needs_input_model(needs: link_import.NeedsInput) -> NeedsInputModel:
    return NeedsInputModel(
        kind=needs.kind,
        message=needs.message,
        guess=GuessModel(
            series_title=needs.guess.series_title,
            season=needs.guess.season,
            episode=needs.guess.episode,
            is_youtube=needs.guess.is_youtube,
            page_title=needs.guess.page_title,
        ),
        missing=needs.missing,
        options=[ShowOptionModel(tmdb_id=item.tmdb_id, name=item.name, year=item.year) for item in needs.options],
        alternatives=needs.alternatives,
        problems=needs.problems,
    )


@router.post("/import", response_model=LinkImportResponse)
async def import_from_link(body: LinkImportBody) -> LinkImportResponse:
    request = link_import.LinkImportRequest(**body.model_dump())
    try:
        outcome = await link_import.import_from_link(request)
    except (SrtParseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (CefrUnavailableError, LemmatizerUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(outcome, link_import.NeedsInput):
        return LinkImportResponse(status="needs_input", needs_input=_needs_input_model(outcome))
    return LinkImportResponse(status="imported", imported=_import_response(outcome))


def _credentials_model(status: credentials.CredentialsStatus) -> CredentialsStatusModel:
    return CredentialsStatusModel(
        tmdb=status.tmdb,
        opensubtitles_api_key=status.opensubtitles_api_key,
        opensubtitles_account=status.opensubtitles_account,
    )


@router.get("/credentials", response_model=CredentialsStatusModel)
async def get_credentials_status() -> CredentialsStatusModel:
    return _credentials_model(await asyncio.to_thread(credentials.status))


@router.put("/credentials", response_model=CredentialsStatusModel)
async def put_credentials(update: CredentialsUpdate) -> CredentialsStatusModel:
    values = {
        credentials.TMDB_API_KEY: update.tmdb_api_key,
        credentials.OPENSUBTITLES_API_KEY: update.opensubtitles_api_key,
        credentials.OPENSUBTITLES_USERNAME: update.opensubtitles_username,
        credentials.OPENSUBTITLES_PASSWORD: update.opensubtitles_password,
    }
    try:
        status = await asyncio.to_thread(credentials.update, values)
    except SecretStoreUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _credentials_model(status)


@router.get("/episodes/{episode_id}/cards", response_model=list[CardModel])
async def get_episode_cards(episode_id: int) -> list[CardModel]:
    try:
        cards = await asyncio.to_thread(service_layer.episode_cards, episode_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_card_model(card) for card in cards]


@router.post("/episodes/{episode_id}/cards", response_model=JobModel)
async def start_card_generation(episode_id: int) -> JobModel:
    try:
        await asyncio.to_thread(service_layer.episode_words, episode_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_model(card_jobs.start(episode_id))


@router.get("/jobs/{job_id}", response_model=JobModel)
async def get_job(job_id: int) -> JobModel:
    job = card_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return _job_model(job)


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(card_id: int) -> None:
    if not await asyncio.to_thread(service_layer.delete_card, card_id):
        raise HTTPException(status_code=404, detail="Карточка не найдена")
