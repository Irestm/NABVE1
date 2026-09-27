from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from modules.ai_bridge.providers.base import AIResult
from modules.english_learning import listening
from modules.english_learning.domain import Episode, Title, SubtitleCue
from modules.english_learning.srt_parser import cues_to_srt
from modules.english_learning.uow import EnglishUnitOfWork

LINES = [
    "Hey, where have you been all night?",
    "I had to figure out what to do with the money.",
    "You promised me you would be honest this time.",
    "Okay.",
    "I know, I know. I decided to tell you everything.",
    "Then start talking before I call the police.",
    "We need to get rid of the evidence tonight.",
    "Fine, but we do it my way this time.",
]


def _cues() -> list[SubtitleCue]:
    return [SubtitleCue(i + 1, i * 3000, i * 3000 + 2500, text) for i, text in enumerate(LINES)]


def _seed(uow_factory: Callable[[], EnglishUnitOfWork], tmp_path: Path, source: str = "opensubtitles") -> int:
    srt = tmp_path / "ep.srt"
    srt.write_text(cues_to_srt(_cues()), encoding="utf-8")
    with uow_factory() as uow:
        series = Title(name="Breaking Bad")
        uow.titles.add(series)
        assert series.id is not None
        episode = Episode(title_id=series.id, season=1, episode=1, source=source, srt_path=str(srt))  # type: ignore[arg-type]
        uow.episodes.add(episode)
        uow.commit()
        assert episode.id is not None
        return episode.id


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "episode.mp4"
    video.write_bytes(b"not really a video")
    return video


def _answer(targets_prompt: str) -> dict[str, Any]:
    import re

    indexes = [int(value) for value in re.findall(r"Target line (\d+)", targets_prompt)]
    return {
        "questions": [
            {"cue_index": index, "kind": "meaning", "question": f"Вопрос {index}?", "options": ["а", "б", "в", "г"], "correct_index": 1}
            for index in indexes
        ]
        + [{"cue_index": 999, "kind": "who", "question": "лишний", "options": ["а", "б", "в", "г"], "correct_index": 0}]
    }


async def _complete(messages: Any, schema: Any, max_tokens: int) -> AIResult:
    return AIResult(text="{}", provider_name="fake", parsed_json=_answer(messages[-1]["content"]))


def test_pick_cues_spreads_across_episode_and_prefers_focus_words() -> None:
    cues = [SubtitleCue(i, i * 1000, i * 1000 + 900, f"line number {i} with some words") for i in range(1, 41)]
    cues[5] = SubtitleCue(6, 5000, 5900, "this line has the magic word evidence here")

    picked = listening.pick_cues(cues, {"evidence"}, count=4)

    assert len(picked) == 4
    assert picked[0].index == 6
    assert picked == sorted(picked, key=lambda cue: cue.start_ms)
    assert picked[-1].index > 30


def test_pick_cues_skips_too_short_lines() -> None:
    assert [cue.text for cue in listening.pick_cues(_cues(), set(), count=20)] == [line for line in LINES if line != "Okay."]


def test_parse_questions_validates_items() -> None:
    targets = _cues()[:3]
    parsed = {
        "questions": [
            {"cue_index": 1, "kind": "who", "question": "Кто?", "options": ["а", "б", "в", "г"], "correct_index": 0},
            {"cue_index": 1, "kind": "who", "question": "Повтор", "options": ["а", "б", "в", "г"], "correct_index": 0},
            {"cue_index": 2, "kind": "next", "question": "Что?", "options": ["а", "а", "в", "г"], "correct_index": 0},
            {"cue_index": 3, "kind": "meaning", "question": "Смысл?", "options": ["а", "б", "в"], "correct_index": 0},
            {"cue_index": 3, "kind": "meaning", "question": "Смысл?", "options": ["а", "б", "в", "г"], "correct_index": 7},
        ]
    }

    questions = listening.parse_questions(parsed, targets)

    assert [(question.cue_index, question.question) for question in questions] == [(1, "Кто?")]
    assert questions[0].line == LINES[0]


def test_build_quiz_persists_and_reloads(uow_factory: Callable[[], EnglishUnitOfWork], tmp_path: Path) -> None:
    episode_id = _seed(uow_factory, tmp_path)

    quiz = asyncio.run(listening.build_quiz(episode_id, str(_video(tmp_path)), complete=_complete, uow_factory=uow_factory))
    reloaded = listening.load_quiz(episode_id, uow_factory)

    assert len(quiz.questions) == len(LINES) - 1
    assert all(question.cue_index != 999 for question in quiz.questions)
    assert reloaded is not None and reloaded.questions == quiz.questions
    assert reloaded.video_path == str(tmp_path / "episode.mp4")


def test_build_quiz_rejects_ai_guess_and_bad_video(uow_factory: Callable[[], EnglishUnitOfWork], tmp_path: Path) -> None:
    guessed = _seed(uow_factory, tmp_path, source="ai_guess")

    with pytest.raises(listening.ListeningError):
        asyncio.run(listening.build_quiz(guessed, str(_video(tmp_path)), complete=_complete, uow_factory=uow_factory))
    with pytest.raises(listening.ListeningError):
        listening.validate_video(str(tmp_path / "missing.mp4"))
    text_file = tmp_path / "notes.txt"
    text_file.write_text("x")
    with pytest.raises(listening.ListeningError):
        listening.validate_video(str(text_file))


def test_ffmpeg_command_pads_and_clamps() -> None:
    command = listening.ffmpeg_command(Path("/v.mkv"), 100, 2000, Path("/out.m4a"))

    assert command[command.index("-ss") + 1] == "0.000"
    assert command[command.index("-t") + 1] == "2.450"
    assert "-vn" in command and command[-1] == "/out.m4a"


def test_extract_clip_caches_and_reports_ffmpeg_failures(uow_factory: Callable[[], EnglishUnitOfWork], tmp_path: Path) -> None:
    episode_id = _seed(uow_factory, tmp_path)
    quiz = asyncio.run(listening.build_quiz(episode_id, str(_video(tmp_path)), complete=_complete, uow_factory=uow_factory))
    cue_index = quiz.questions[0].cue_index
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        Path(command[-1]).write_bytes(b"AUDIO")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    first = listening.extract_clip(episode_id, cue_index, uow_factory, run=fake_run)
    second = listening.extract_clip(episode_id, cue_index, uow_factory, run=fake_run)

    assert base64.b64decode(first) == b"AUDIO" == base64.b64decode(second)
    assert len(calls) == 1

    def failing_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, b"", b"boom")

    with pytest.raises(listening.ListeningError):
        listening.extract_clip(episode_id, quiz.questions[1].cue_index, uow_factory, run=failing_run)
    with pytest.raises(LookupError):
        listening.extract_clip(episode_id, 4242, uow_factory, run=fake_run)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_extract_clip_with_real_ffmpeg(uow_factory: Callable[[], EnglishUnitOfWork], tmp_path: Path) -> None:
    video = tmp_path / "tone.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:a", "aac", str(video)],
        check=True,
        timeout=60,
    )
    srt = tmp_path / "tone.srt"
    srt.write_text(cues_to_srt([SubtitleCue(1, 1000, 2000, "This is a real test line.")]), encoding="utf-8")
    with uow_factory() as uow:
        series = Title(name="Tone")
        uow.titles.add(series)
        assert series.id is not None
        episode = Episode(title_id=series.id, season=1, episode=1, source="manual", srt_path=str(srt))
        uow.episodes.add(episode)
        uow.commit()
        assert episode.id is not None
        episode_id = episode.id

    asyncio.run(listening.build_quiz(episode_id, str(video), complete=_complete, uow_factory=uow_factory))
    audio = base64.b64decode(listening.extract_clip(episode_id, 1, uow_factory))

    assert len(audio) > 1000
    assert audio[4:8] == b"ftyp"
