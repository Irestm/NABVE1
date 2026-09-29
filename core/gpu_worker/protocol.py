from __future__ import annotations

import pickle
import struct
from dataclasses import dataclass, field
from typing import Any, BinaryIO

SHUTDOWN_OP = "__shutdown__"
GPU_ALLOWED_ENV = "ASSISTANT_GPU_WORKER_GPU"
PARENT_PID_ENV = "ASSISTANT_GPU_WORKER_PARENT_PID"
DISABLED_ENV = "ASSISTANT_GPU_WORKER_DISABLED"
CUDA_VISIBLE_DEVICES_ENV = "CUDA_VISIBLE_DEVICES"

_HEADER = struct.Struct(">Q")


class ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerRequest:
    request_id: int
    op: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerResponse:
    request_id: int
    ok: bool
    result: Any = None
    error: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class WorkerReady:
    pid: int
    device: str


def write_frame(stream: BinaryIO, message: object) -> None:
    payload = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def read_frame(stream: BinaryIO) -> object | None:
    header = _read_exact(stream, _HEADER.size)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    payload = _read_exact(stream, length)
    if payload is None:
        raise ProtocolError("Worker pipe closed in the middle of a message")
    return pickle.loads(payload)


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    if size == 0:
        return b""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if remaining == size:
                return None
            raise ProtocolError("Worker pipe closed in the middle of a message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return chunks[0] if len(chunks) == 1 else b"".join(chunks)
