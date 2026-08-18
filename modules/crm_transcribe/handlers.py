from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.crm_transcribe import service_layer
from modules.crm_transcribe.ports import TranscriptionPort
from modules.crm_transcribe.transcriber import LocalWhisperTranscriber

_transcriber: TranscriptionPort = LocalWhisperTranscriber()


async def _handle_transcribe_recording(params: dict[str, Any]) -> dict[str, Any]:
    export_txt = bool(params.get("export_txt", True))
    return await asyncio.to_thread(service_layer.transcribe, _transcriber, params.get("path"), export_txt)


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "transcribe_recording",
        _handle_transcribe_recording,
        dangerous=False,
        description="Расшифровать запись звонка CRM в текст через локальный faster-whisper (path, опционально export_txt).",
    )
