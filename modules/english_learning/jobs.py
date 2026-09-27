from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Literal

from core.logger import get_logger
from modules.english_learning.card_generation import GenerationProgress
from modules.english_learning.pipeline import process_episode

logger = get_logger(__name__)

JobState = Literal["running", "done", "failed"]


@dataclass(frozen=True)
class CardJob:
    id: int
    episode_id: int
    state: JobState
    done: int = 0
    total: int = 0
    created: int = 0
    skipped: int = 0
    error: str | None = None
    phase: str = "cards"


Generator = Callable[..., Awaitable[GenerationProgress]]


class CardJobRegistry:
    def __init__(self, generator: Generator = process_episode) -> None:
        self._generator = generator
        self._gate: asyncio.Semaphore | None = None
        self._jobs: dict[int, CardJob] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._ids = itertools.count(1)

    def get(self, job_id: int) -> CardJob | None:
        return self._jobs.get(job_id)

    def running_for(self, episode_id: int) -> CardJob | None:
        return next(
            (job for job in self._jobs.values() if job.episode_id == episode_id and job.state == "running"), None
        )

    def start(self, episode_id: int) -> CardJob:
        running = self.running_for(episode_id)
        if running is not None:
            return running
        job = CardJob(id=next(self._ids), episode_id=episode_id, state="running")
        self._jobs[job.id] = job
        self._tasks[job.id] = asyncio.get_running_loop().create_task(self._run(job.id))
        return job

    def _update(self, job_id: int, progress: GenerationProgress) -> None:
        self._jobs[job_id] = replace(
            self._jobs[job_id],
            done=progress.done,
            total=progress.total,
            created=progress.created,
            skipped=progress.skipped,
            phase=progress.phase,
        )

    async def _run(self, job_id: int) -> None:
        job = self._jobs[job_id]
        if self._gate is None:
            self._gate = asyncio.Semaphore(1)
        try:
            async with self._gate:
                await self._generator(job.episode_id, on_progress=lambda progress: self._update(job_id, progress))
        except Exception as exc:
            logger.exception("Card generation job %d for episode %d failed", job_id, job.episode_id)
            self._jobs[job_id] = replace(self._jobs[job_id], state="failed", error=str(exc))
        else:
            self._jobs[job_id] = replace(self._jobs[job_id], state="done")
        finally:
            self._tasks.pop(job_id, None)

    async def wait(self, job_id: int) -> CardJob | None:
        task = self._tasks.get(job_id)
        if task is not None:
            await task
        return self.get(job_id)


card_jobs = CardJobRegistry()
