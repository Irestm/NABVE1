from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from core.lifecycle.shutdown import request_process_shutdown

router = APIRouter(prefix="/api/system", tags=["system"])

SHUTDOWN_DELAY_SECONDS = 0.2


class ShutdownAccepted(BaseModel):
    ok: bool


def schedule_shutdown(delay_seconds: float = SHUTDOWN_DELAY_SECONDS) -> None:
    asyncio.get_running_loop().call_later(delay_seconds, request_process_shutdown)


@router.post("/shutdown", response_model=ShutdownAccepted, status_code=202)
async def shutdown() -> ShutdownAccepted:
    schedule_shutdown()
    return ShutdownAccepted(ok=True)
