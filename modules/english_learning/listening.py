from __future__ import annotations

import base64
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from core.config import DATA_DIR
from core.logger import get_logger
from modules.ai_bridge.providers.base import AIResult, ChatMessage
from modules.ai_bridge.providers.router import get_router
from modules.english_learning.domain import SubtitleCue
from modules.english_learning.srt_parser import parse_srt
from modules.english_learning.uow import EnglishUnitOfWork

logger = get_logger(__name__)

CLIPS_DIR: Path = DATA_DIR / "listening"
QUESTION_COUNT = 10
OPTION_COUNT = 4
CONTEXT_BEFORE = 3
CONTEXT_AFTER = 4
MIN_CUE_WORDS = 4
PAD_BEFORE_MS = 250
PAD_AFTER_MS = 450
_FFMPEG_TIMEOUT_SECONDS = 60
_QUESTION_MAX_TOKENS = 4000
VIDEO_SUFFIXES: frozenset[str] = frozenset({".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".ts", ".wmv", ".flv"})

QuestionKind = Literal["who", "meaning", "next"]

QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cue_index": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["who", "meaning", "next"]},
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "correct_index": {"type": "integer"},
                },
                "required": ["cue_index", "kind", "question", "options", "correct_index"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You write listening-comprehension questions for a Russian-speaking A2-B1 English learner who has just "
    "watched a TV episode. For each numbered target line, write one question in Russian of the given kind: "
    "'who' — кто это сказал (use character names you can infer from the context; if unsure, ask to whom it was "
    "said or about whom), 'meaning' — что говорящий имел в виду, 'next' — что произошло сразу после этой реплики "
    "(use the following lines). Give exactly 4 short Russian options, one correct, plausible distractors, and the "
    "0-based correct_index. Use cue_index exactly as given."
)


class ListeningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ListeningQuestion:
    cue_index: int
    kind: str
    question: str
    options: list[str]
    correct_index: int
    start_ms: int
    end_ms: int
    line: str


@dataclass(frozen=True)
class ListeningQuiz:
    episode_id: int
    video_path: str
    questions: list[ListeningQuestion]


Complete = Callable[[list[ChatMessage], dict[str, Any], int], Awaitable[AIResult]]


def _default_complete(messages: list[ChatMessage], schema: dict[str, Any], max_tokens: int) -> Awaitable[AIResult]:
    return get_router().complete(messages, json_schema=schema, max_tokens=max_tokens, kind="complex")


def validate_video(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise ListeningError("Видеофайл не найден")
    if path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ListeningError("Это не похоже на видеофайл")
    return path


def _cue_score(cue: SubtitleCue, focus_words: set[str]) -> tuple[int, int]:
    words = cue.text.lower().split()
    hits = sum(1 for word in words if word.strip(".,!?\"'") in focus_words)
    return hits, -abs(len(words) - 9)


def pick_cues(cues: list[SubtitleCue], focus_words: set[str], count: int = QUESTION_COUNT) -> list[SubtitleCue]:
    usable = [cue for cue in cues if len(cue.text.split()) >= MIN_CUE_WORDS]
    if len(usable) <= count:
        return usable
    bucket_size = len(usable) / count
    picked: list[SubtitleCue] = []
    for bucket in range(count):
        chunk = usable[int(bucket * bucket_size) : int((bucket + 1) * bucket_size)] or usable[-1:]
        picked.append(max(chunk, key=lambda cue: _cue_score(cue, focus_words)))
    return picked


def _context_block(cues: list[SubtitleCue], target: SubtitleCue) -> str:
    position = next(index for index, cue in enumerate(cues) if cue.index == target.index)
    before = cues[max(0, position - CONTEXT_BEFORE) : position]
    after = cues[position + 1 : position + 1 + CONTEXT_AFTER]
    lines = [f"  {cue.text}" for cue in before]
    lines.append(f"> [{target.index}] {target.text}")
    lines.extend(f"  {cue.text}" for cue in after)
    return "\n".join(lines)


def _kinds(count: int) -> list[QuestionKind]:
    cycle: tuple[QuestionKind, ...] = ("meaning", "who", "next")
    return [cycle[index % len(cycle)] for index in range(count)]


def parse_questions(parsed: Any, targets: list[SubtitleCue]) -> list[ListeningQuestion]:
    by_index = {cue.index: cue for cue in targets}
    items = parsed.get("questions") if isinstance(parsed, dict) else None
    questions: list[ListeningQuestion] = []
    seen: set[int] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        cue = by_index.get(item.get("cue_index")) if isinstance(item.get("cue_index"), int) else None
        options = [str(option).strip() for option in item.get("options") or [] if str(option).strip()]
        correct = item.get("correct_index")
        question = str(item.get("question") or "").strip()
        if (
            cue is None
            or cue.index in seen
            or not question
            or len(options) != OPTION_COUNT
            or len({option.lower() for option in options}) != OPTION_COUNT
            or not isinstance(correct, int)
            or not 0 <= correct < OPTION_COUNT
        ):
            continue
        seen.add(cue.index)
        questions.append(
            ListeningQuestion(
                cue_index=cue.index,
                kind=str(item.get("kind") or "meaning"),
                question=question,
                options=options,
                correct_index=correct,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                line=cue.text,
            )
        )
    questions.sort(key=lambda question: question.start_ms)
    return questions


def _load_episode_cues(uow: EnglishUnitOfWork, episode_id: int) -> tuple[list[SubtitleCue], set[str]]:
    episode = uow.episodes.get(episode_id)
    if episode is None:
        raise LookupError(f"Эпизод {episode_id} не найден")
    if episode.source == "ai_guess":
        raise ListeningError("Для этого эпизода нет настоящих субтитров — listening-квиз недоступен")
    if not episode.srt_path or not Path(episode.srt_path).is_file():
        raise ListeningError("Файл субтитров эпизода не найден")
    cues = parse_srt(Path(episode.srt_path).read_text(encoding="utf-8"))
    focus = {card.word.lower() for card in uow.cards.list_for_episode(episode_id)}
    focus |= {word.surface.lower() for word in uow.words.list_for_episode(episode_id)}
    return cues, focus


async def build_quiz(
    episode_id: int,
    video_path: str,
    *,
    complete: Complete = _default_complete,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
) -> ListeningQuiz:
    video = validate_video(video_path)
    with uow_factory() as uow:
        cues, focus = _load_episode_cues(uow, episode_id)
    targets = pick_cues(cues, focus)
    if not targets:
        raise ListeningError("В субтитрах слишком мало реплик для квиза")
    prompt = "\n\n".join(
        f"Target line {cue.index} — kind: {kind}\n{_context_block(cues, cue)}"
        for cue, kind in zip(targets, _kinds(len(targets)))
    )
    messages: list[ChatMessage] = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    result = await complete(messages, QUESTION_SCHEMA, _QUESTION_MAX_TOKENS)
    questions = parse_questions(result.parsed_json, targets)
    if not questions:
        raise ListeningError("ИИ не смог составить вопросы — попробуйте ещё раз")
    quiz = ListeningQuiz(episode_id=episode_id, video_path=str(video), questions=questions)
    with uow_factory() as uow:
        uow.listening.save(episode_id, quiz.video_path, [asdict(question) for question in questions])
        uow.commit()
    return quiz


def load_quiz(
    episode_id: int, uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork
) -> ListeningQuiz | None:
    with uow_factory() as uow:
        stored = uow.listening.get(episode_id)
    if stored is None:
        return None
    video_path, raw_questions = stored
    questions = [ListeningQuestion(**item) for item in raw_questions]  # type: ignore[arg-type]
    return ListeningQuiz(episode_id=episode_id, video_path=video_path, questions=questions)


def clip_path(episode_id: int, cue_index: int) -> Path:
    return CLIPS_DIR / str(episode_id) / f"{cue_index}.m4a"


def ffmpeg_command(video: Path, start_ms: int, end_ms: int, output: Path) -> list[str]:
    start = max(0, start_ms - PAD_BEFORE_MS) / 1000
    duration = (end_ms + PAD_AFTER_MS) / 1000 - start
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{duration:.3f}",
        "-vn", "-ac", "1", "-ar", "44100", "-c:a", "aac", "-b:a", "96k", str(output),
    ]


def extract_clip(
    episode_id: int,
    cue_index: int,
    uow_factory: Callable[[], EnglishUnitOfWork] = EnglishUnitOfWork,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> str:
    quiz = load_quiz(episode_id, uow_factory)
    if quiz is None:
        raise LookupError("Квиз для этого эпизода ещё не создан")
    question = next((item for item in quiz.questions if item.cue_index == cue_index), None)
    if question is None:
        raise LookupError("Такой реплики нет в квизе")
    output = clip_path(episode_id, cue_index)
    if not output.is_file() or output.stat().st_size == 0:
        if shutil.which("ffmpeg") is None:
            raise ListeningError("Не установлен ffmpeg")
        video = validate_video(quiz.video_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = run(
            ffmpeg_command(video, question.start_ms, question.end_ms, output),
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            logger.error("ffmpeg failed for episode %d cue %d: %s", episode_id, cue_index, completed.stderr[-500:])
            raise ListeningError("ffmpeg не смог вырезать реплику из видео")
    return base64.b64encode(output.read_bytes()).decode("ascii")
