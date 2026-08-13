from __future__ import annotations

from typing import Any

from modules.crm_transcribe.ports import TranscriptionPort


def transcribe(transcriber: TranscriptionPort, path: str | None, export_txt: bool) -> dict[str, Any]:
    if not path:
        raise ValueError("Missing required parameter 'path'")
    return transcriber.transcribe_file(path, export_txt)
