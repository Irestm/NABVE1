from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TranscriptionPort(Protocol):
    def transcribe_file(self, path: str, export_txt: bool = True) -> dict[str, Any]: ...
