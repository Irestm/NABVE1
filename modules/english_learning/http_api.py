from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from modules.english_learning import service_layer
from modules.english_learning.cefr import CEFRJ_ATTRIBUTION, CefrUnavailableError
from modules.english_learning.domain import Episode, EpisodeWord
from modules.english_learning.lemmatizer import LemmatizerUnavailableError
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


class ImportResponse(BaseModel):
    series: SeriesModel
    episode: EpisodeModel
    words: list[WordModel]


class LibraryResponse(BaseModel):
    series: list[SeriesModel]
    cefr_attribution: str


def _episode_model(episode: Episode, word_count: int = 0, card_count: int = 0) -> EpisodeModel:
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


@router.get("/library", response_model=LibraryResponse)
async def get_library() -> LibraryResponse:
    summaries = await asyncio.to_thread(service_layer.library)
    return LibraryResponse(
        series=[
            SeriesModel(
                id=summary.series.id or 0,
                title=summary.series.title,
                imdb_id=summary.series.imdb_id,
                episodes=[_episode_model(item.episode, item.word_count, item.card_count) for item in summary.episodes],
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
    return ImportResponse(
        series=SeriesModel(
            id=result.series.id or 0, title=result.series.title, imdb_id=result.series.imdb_id, episodes=[]
        ),
        episode=_episode_model(result.episode, word_count=len(result.words)),
        words=[_word_model(word) for word in result.words],
    )
