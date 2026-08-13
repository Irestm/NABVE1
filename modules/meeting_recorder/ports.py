from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class AudioConverterPort(Protocol):
    def convert_to_ogg(self, raw_path: Path, output_path: Path) -> None: ...

    def probe_duration_seconds(self, path: Path) -> float: ...


@runtime_checkable
class TranscriberPort(Protocol):
    def transcribe(self, audio_path: Path, *, on_progress: Callable[[float], None]) -> str: ...


@runtime_checkable
class SummarizerPort(Protocol):
    async def summarize(self, transcript_text: str) -> str: ...
