from __future__ import annotations

import asyncio

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.secret_store import SecretStoreUnavailableError
from modules.english_learning import assistant_http, credentials, learn, link_import, listening, pipeline, service_layer
from modules.ai_bridge.providers.base import AllProvidersFailed
from modules.english_learning.cefr import CEFRJ_ATTRIBUTION, CefrUnavailableError
from modules.english_learning.domain import Card, Episode, EpisodeWord, FilterSettings, Title
from modules.english_learning.jobs import CardJob, card_jobs
from modules.english_learning.lemmatizer import LemmatizerUnavailableError
from modules.english_learning.lexicon import KAIKKI_ATTRIBUTION
from modules.english_learning.movie_parts import DEFAULT_PART_MINUTES, MAX_PART_MINUTES, MIN_PART_MINUTES
from modules.english_learning.service_layer import ImportResult
from modules.english_learning.srt_parser import SrtParseError

router = APIRouter(prefix="/api/english", tags=["english"])

MAX_SRT_BYTES = 5 * 1024 * 1024


class EpisodeModel(BaseModel):
    id: int
    title_id: int
    season: int | None
    episode: int | None
    part: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    code: str
    title: str | None
    source: str
    word_count: int = 0
    card_count: int = 0
    words: int = 0
    phrases: int = 0
    display_name: str = ""
    has_override: bool = False


class TitleModel(BaseModel):
    id: int
    kind: str
    name: str
    year: int | None
    imdb_id: str | None
    display_name: str
    words: int = 0
    phrases: int = 0
    has_override: bool = False
    episodes: list[EpisodeModel]


class ExampleModel(BaseModel):
    text: str
    timestamp_ms: int


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
    kind: str = "word"
    examples: list[ExampleModel] = []


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
    kind: str = "word"
    surface_form: str | None = None
    sense_label: str | None = None
    literal_translation: str | None = None
    cefr_source: str | None = None
    confidence: float | None = None
    archived: bool = False


class JobModel(BaseModel):
    id: int
    episode_id: int
    state: str
    done: int
    total: int
    created: int
    skipped: int
    error: str | None
    phase: str = "cards"


class ImportResponse(BaseModel):
    title: TitleModel
    episode: EpisodeModel
    episodes: list[EpisodeModel]
    words: list[WordModel]
    job: JobModel | None = None


class LibraryResponse(BaseModel):
    titles: list[TitleModel]
    cefr_attribution: str
    lexicon_attribution: str


def _episode_model(episode: Episode, summary: service_layer.EpisodeSummary | None = None) -> EpisodeModel:
    if episode.id is None:
        raise ValueError("Episode has no id")
    return EpisodeModel(
        id=episode.id,
        title_id=episode.title_id,
        season=episode.season,
        episode=episode.episode,
        part=episode.part,
        start_ms=episode.start_ms,
        end_ms=episode.end_ms,
        code=episode.code,
        title=episode.title,
        source=episode.source,
        word_count=summary.word_count if summary else 0,
        card_count=summary.card_count if summary else 0,
        words=summary.words if summary else 0,
        phrases=summary.phrases if summary else 0,
        display_name=summary.display_name if summary else "",
        has_override=summary.has_override if summary else False,
    )


def _title_model(title: Title, summary: service_layer.TitleSummary | None = None) -> TitleModel:
    return TitleModel(
        id=title.id or 0,
        kind=title.kind,
        name=title.name,
        year=title.year,
        imdb_id=title.imdb_id,
        display_name=summary.display_name if summary else title.display_name,
        words=summary.words if summary else 0,
        phrases=summary.phrases if summary else 0,
        has_override=summary.has_override if summary else False,
        episodes=[_episode_model(item.episode, item) for item in summary.episodes] if summary else [],
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
        kind=card.kind,
        surface_form=card.surface_form,
        sense_label=card.sense_label,
        literal_translation=card.literal_translation,
        cefr_source=card.cefr_source,
        confidence=card.confidence,
        archived=card.archived,
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
        phase=job.phase,
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
        kind=word.kind,
        examples=[ExampleModel(text=item.text, timestamp_ms=item.timestamp_ms) for item in word.examples],
    )


def _import_response(result: ImportResult, *, generate: bool = True) -> ImportResponse:
    episodes = result.episodes or [result.episode]
    jobs = [card_jobs.start(item.id) for item in episodes if item.id is not None and generate and result.words]
    first_job = next((job for job in jobs if job.episode_id == result.episode.id), jobs[0] if jobs else None)
    counts: dict[int, int] = {}
    for word in result.words:
        counts[word.episode_id] = counts.get(word.episode_id, 0) + 1
    models = [
        _episode_model(
            item,
            service_layer.EpisodeSummary(item, counts.get(item.id or 0, 0), 0, item.code),
        )
        for item in episodes
    ]
    return ImportResponse(
        title=_title_model(result.title),
        episode=models[0] if result.episode.id == episodes[0].id else _episode_model(result.episode),
        episodes=models,
        words=[_word_model(word) for word in result.words],
        job=_job_model(first_job) if first_job is not None else None,
    )


@router.get("/library", response_model=LibraryResponse)
async def get_library() -> LibraryResponse:
    summaries = await asyncio.to_thread(service_layer.library)
    return LibraryResponse(
        titles=[_title_model(summary.title, summary) for summary in summaries],
        cefr_attribution=CEFRJ_ATTRIBUTION,
        lexicon_attribution=KAIKKI_ATTRIBUTION,
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
    season: int | None = Form(None, ge=0),
    episode: int | None = Form(None, ge=0),
    episode_title: str | None = Form(None),
    kind: Literal["series", "movie"] = Form("series"),
    year: int | None = Form(None, ge=1870, le=2100),
    split_movie: bool = Form(True),
    part_minutes: int = Form(DEFAULT_PART_MINUTES, ge=MIN_PART_MINUTES, le=MAX_PART_MINUTES),
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
            kind=kind,
            year=year,
            split=split_movie,
            part_minutes=part_minutes,
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
    kind: Literal["series", "movie"] | None = None
    year: int | None = Field(None, ge=1870, le=2100)
    split_movie: bool = True
    part_minutes: int = Field(DEFAULT_PART_MINUTES, ge=MIN_PART_MINUTES, le=MAX_PART_MINUTES)


class GuessModel(BaseModel):
    series_title: str | None
    season: int | None
    episode: int | None
    is_youtube: bool
    page_title: str | None
    kind: str | None = None
    year: int | None = None


class ShowOptionModel(BaseModel):
    tmdb_id: int
    name: str
    year: int | None
    kind: str = "series"
    poster_url: str | None = None


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
            kind=needs.guess.kind,
            year=needs.guess.year,
        ),
        missing=needs.missing,
        options=[
            ShowOptionModel(
                tmdb_id=item.tmdb_id, name=item.name, year=item.year, kind=item.kind, poster_url=item.poster_url
            )
            for item in needs.options
        ],
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
async def get_episode_cards(episode_id: int, include_archived: bool = False) -> list[CardModel]:
    try:
        cards = await asyncio.to_thread(
            lambda: service_layer.episode_cards(episode_id, include_archived=include_archived)
            if include_archived
            else service_layer.episode_cards(episode_id)
        )
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


class DeletedModel(BaseModel):
    deleted: bool


@router.delete("/cards/{card_id}", response_model=DeletedModel)
async def delete_card(card_id: int) -> DeletedModel:
    if not await asyncio.to_thread(service_layer.delete_card, card_id):
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    return DeletedModel(deleted=True)


class SessionStartBody(BaseModel):
    shuffle: bool = True
    direction: Literal["en_ru", "ru_en"] = "en_ru"
    mode: Literal["choice", "input", "mixed"] = "mixed"


class SessionModel(BaseModel):
    id: int
    episode_id: int
    settings: dict[str, object]


class AnswerBody(BaseModel):
    card_id: int
    mode: Literal["choice", "input"]
    answer: str = Field(..., max_length=200)


class AnswerModel(BaseModel):
    correct: bool
    exact: bool
    matched: str | None
    expected: list[str]


class HardWordModel(BaseModel):
    card: CardModel
    mistakes: int


class SummaryModel(BaseModel):
    session_id: int
    mistakes: int
    hard_words: list[HardWordModel]


@router.post("/episodes/{episode_id}/sessions", response_model=SessionModel)
async def start_session(episode_id: int, body: SessionStartBody) -> SessionModel:
    settings = learn.LearnSettings(shuffle=body.shuffle, direction=body.direction, mode=body.mode)
    try:
        session = await asyncio.to_thread(learn.start_session, episode_id, settings)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SessionModel(id=session.id or 0, episode_id=session.episode_id, settings=session.settings)


@router.post("/sessions/{session_id}/answers", response_model=AnswerModel)
async def post_answer(session_id: int, body: AnswerBody) -> AnswerModel:
    try:
        outcome = await asyncio.to_thread(learn.answer, session_id, body.card_id, body.mode, body.answer)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnswerModel(
        correct=outcome.result.correct,
        exact=outcome.result.exact,
        matched=outcome.result.matched,
        expected=outcome.expected,
    )


@router.post("/sessions/{session_id}/finish", response_model=SummaryModel)
async def finish_session(session_id: int) -> SummaryModel:
    try:
        summary = await asyncio.to_thread(learn.finish, session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SummaryModel(
        session_id=session_id,
        mistakes=summary.mistakes,
        hard_words=[HardWordModel(card=_card_model(item.card), mistakes=item.mistakes) for item in summary.hard_words],
    )


class ListeningStartBody(BaseModel):
    video_path: str = Field(..., min_length=1, max_length=4096)


class ListeningQuestionModel(BaseModel):
    cue_index: int
    kind: str
    question: str
    options: list[str]
    correct_index: int
    start_ms: int
    end_ms: int
    line: str


class ListeningQuizModel(BaseModel):
    episode_id: int
    video_name: str
    questions: list[ListeningQuestionModel]


class ClipModel(BaseModel):
    audio_base64: str
    mime: str


def _quiz_model(quiz: listening.ListeningQuiz) -> ListeningQuizModel:
    return ListeningQuizModel(
        episode_id=quiz.episode_id,
        video_name=quiz.video_path.rsplit("/", 1)[-1],
        questions=[
            ListeningQuestionModel(
                cue_index=question.cue_index,
                kind=question.kind,
                question=question.question,
                options=question.options,
                correct_index=question.correct_index,
                start_ms=question.start_ms,
                end_ms=question.end_ms,
                line=question.line,
            )
            for question in quiz.questions
        ],
    )


@router.post("/episodes/{episode_id}/listening", response_model=ListeningQuizModel)
async def create_listening_quiz(episode_id: int, body: ListeningStartBody) -> ListeningQuizModel:
    try:
        quiz = await listening.build_quiz(episode_id, body.video_path)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except listening.ListeningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(status_code=503, detail=f"Ни один ИИ-провайдер не ответил: {exc}") from exc
    return _quiz_model(quiz)


@router.get("/episodes/{episode_id}/listening", response_model=ListeningQuizModel)
async def get_listening_quiz(episode_id: int) -> ListeningQuizModel:
    quiz = await asyncio.to_thread(listening.load_quiz, episode_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Квиз ещё не создан")
    return _quiz_model(quiz)


@router.get("/episodes/{episode_id}/listening/clips/{cue_index}", response_model=ClipModel)
async def get_listening_clip(episode_id: int, cue_index: int) -> ClipModel:
    try:
        audio = await asyncio.to_thread(listening.extract_clip, episode_id, cue_index)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except listening.ListeningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ClipModel(audio_base64=audio, mime="audio/mp4")


class ReanalyzeModel(BaseModel):
    candidates: int
    archived: int
    restored: int
    job: JobModel | None = None


class ReanalyzeAllModel(BaseModel):
    candidates: int
    archived: int
    restored: int
    failed: list[str]


class StatsModel(BaseModel):
    episode_id: int
    token_count: int
    lemma_count: int
    tokens_by_level: dict[str, int]
    lemmas_by_level: dict[str, int]
    expressions_per_1000: float
    words_per_minute: float
    non_english_share: float
    off_list_share: float
    top_above_b2: list[tuple[str, int]]


@router.post("/episodes/{episode_id}/reanalyze", response_model=ReanalyzeModel)
async def reanalyze_episode(episode_id: int) -> ReanalyzeModel:
    try:
        result = await asyncio.to_thread(pipeline.rebuild, episode_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CefrUnavailableError, LemmatizerUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    job = card_jobs.start(episode_id)
    return ReanalyzeModel(
        candidates=sum(len(words) for words in result.words.values()),
        archived=result.archived,
        restored=result.restored,
        job=_job_model(job),
    )


@router.post("/reanalyze", response_model=ReanalyzeAllModel)
async def reanalyze_library() -> ReanalyzeAllModel:
    try:
        summary = await asyncio.to_thread(pipeline.rebuild_all)
    except (CefrUnavailableError, LemmatizerUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ReanalyzeAllModel(
        candidates=summary.episodes, archived=summary.archived, restored=summary.restored, failed=summary.failed
    )


@router.get("/episodes/{episode_id}/stats", response_model=StatsModel)
async def get_episode_stats(episode_id: int) -> StatsModel:
    stats = await asyncio.to_thread(service_layer.episode_stats, episode_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Статистика эпизода ещё не посчитана")
    return StatsModel(
        episode_id=episode_id,
        token_count=stats.token_count,
        lemma_count=stats.lemma_count,
        tokens_by_level=stats.tokens_by_level,
        lemmas_by_level=stats.lemmas_by_level,
        expressions_per_1000=stats.expressions_per_1000,
        words_per_minute=stats.words_per_minute,
        non_english_share=stats.non_english_share,
        off_list_share=stats.off_list_share,
        top_above_b2=stats.top_above_b2,
    )


class FilterModel(BaseModel):
    levels: list[Literal["A1", "A2", "B1", "B2"]]
    include_unleveled: bool
    mwe_mode: Literal["follow_levels", "always"]


class FilterViewModel(FilterModel):
    source: str


class ModuleSettingsModel(BaseModel):
    user_level: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    allow_answer_hints: bool


class ModuleSettingsUpdate(BaseModel):
    user_level: Literal["A1", "A2", "B1", "B2", "C1", "C2"] | None = None
    allow_answer_hints: bool | None = None


FilterScopeParam = Literal["global", "title", "episode"]


def _filter_view(view: service_layer.FilterView) -> FilterViewModel:
    return FilterViewModel(
        levels=list(view.settings.levels),  # type: ignore[arg-type]
        include_unleveled=view.settings.include_unleveled,
        mwe_mode=view.settings.mwe_mode,
        source=view.source,
    )


@router.get("/filters/{scope}", response_model=FilterViewModel)
async def get_filter(scope: FilterScopeParam, scope_id: int | None = None) -> FilterViewModel:
    try:
        return _filter_view(await asyncio.to_thread(service_layer.get_filter, scope, scope_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/filters/{scope}", response_model=FilterViewModel)
async def put_filter(scope: FilterScopeParam, body: FilterModel, scope_id: int | None = None) -> FilterViewModel:
    settings = FilterSettings(levels=tuple(body.levels), include_unleveled=body.include_unleveled, mwe_mode=body.mwe_mode)
    try:
        return _filter_view(await asyncio.to_thread(service_layer.save_filter, scope, scope_id, settings))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/filters/{scope}", response_model=FilterViewModel)
async def delete_filter(scope: FilterScopeParam, scope_id: int | None = None) -> FilterViewModel:
    try:
        return _filter_view(await asyncio.to_thread(service_layer.reset_filter, scope, scope_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/settings", response_model=ModuleSettingsModel)
async def get_module_settings() -> ModuleSettingsModel:
    settings = await asyncio.to_thread(service_layer.get_module_settings)
    return ModuleSettingsModel(user_level=settings.user_level, allow_answer_hints=settings.allow_answer_hints)  # type: ignore[arg-type]


@router.put("/settings", response_model=ModuleSettingsModel)
async def put_module_settings(body: ModuleSettingsUpdate) -> ModuleSettingsModel:
    settings = await asyncio.to_thread(
        lambda: service_layer.save_module_settings(user_level=body.user_level, allow_answer_hints=body.allow_answer_hints)
    )
    return ModuleSettingsModel(user_level=settings.user_level, allow_answer_hints=settings.allow_answer_hints)  # type: ignore[arg-type]


router.include_router(assistant_http.router)
