from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from core.gpu_worker.context import WorkerContext
from core.logger import get_logger
from core.voice.whisper_engine import (
    CPU_DEVICE,
    CUDA_DEVICE,
    WhisperEngine,
    import_faster_whisper,
    import_torch,
)

logger = get_logger(__name__)

WHISPER_NUM_WORKERS = 2
SILERO_THREADS = 4


def _ctranslate2_cuda_available(context: WorkerContext) -> bool:
    if not context.gpu_allowed:
        return False

    def probe() -> bool:
        try:
            import_faster_whisper(block_torch_import=True)
            import ctranslate2

            return int(ctranslate2.get_cuda_device_count()) > 0
        except Exception:
            logger.warning("Could not probe CUDA through ctranslate2; using CPU", exc_info=True)
            return False

    return context.cached("ctranslate2_cuda", probe)


def _torch_device(context: WorkerContext) -> str:
    if not context.gpu_allowed:
        return CPU_DEVICE

    def probe() -> str:
        try:
            return CUDA_DEVICE if import_torch().cuda.is_available() else CPU_DEVICE
        except Exception:
            logger.warning("Could not probe CUDA through torch; using CPU", exc_info=True)
            return CPU_DEVICE

    return context.cached("torch_device", probe)


def primary_device(context: WorkerContext) -> str:
    return CUDA_DEVICE if _ctranslate2_cuda_available(context) else CPU_DEVICE


def _whisper_device(context: WorkerContext, requested: str) -> str:
    if requested == CPU_DEVICE:
        return CPU_DEVICE
    return CUDA_DEVICE if _ctranslate2_cuda_available(context) else CPU_DEVICE


def _whisper_engine(context: WorkerContext, args: dict[str, Any]) -> WhisperEngine:
    model_size = str(args["model_size"])
    compute_type = str(args.get("compute_type", "int8"))
    device = _whisper_device(context, str(args.get("device", "auto")))
    return context.cached(
        ("whisper", model_size, device, compute_type),
        lambda: WhisperEngine(
            model_size,
            device,
            compute_type,
            num_workers=WHISPER_NUM_WORKERS,
            block_torch_import=True,
        ),
    )


def stt_load(context: WorkerContext, args: dict[str, Any]) -> dict[str, str]:
    engine = _whisper_engine(context, args)
    engine.load()
    return {"device": engine.device}


def stt_transcribe(context: WorkerContext, args: dict[str, Any]) -> dict[str, Any]:
    engine = _whisper_engine(context, args)
    audio = np.asarray(args["audio"], dtype=np.float32)
    result = engine.transcribe(audio, args.get("language"))
    return {**result.as_dict(), "device": engine.device}


def _silero_model(context: WorkerContext, model_path: str) -> Any:
    def load() -> Any:
        torch = import_torch()
        torch.set_num_threads(SILERO_THREADS)
        importer = torch.package.PackageImporter(str(Path(model_path)))
        model = importer.load_pickle("tts_models", "model")
        device = _torch_device(context)
        if device != CPU_DEVICE:
            model.to(torch.device(device))
        return model

    return context.cached(("silero", model_path), load)


def tts_silero_load(context: WorkerContext, args: dict[str, Any]) -> None:
    _silero_model(context, str(args["model_path"]))


def tts_silero(context: WorkerContext, args: dict[str, Any]) -> tuple[np.ndarray, int]:
    model = _silero_model(context, str(args["model_path"]))
    sample_rate = int(args["sample_rate"])
    audio = model.apply_tts(text=str(args["text"]), speaker=str(args["speaker"]), sample_rate=sample_rate)
    return audio.detach().cpu().numpy().astype(np.float32), sample_rate


def _embedding_model(context: WorkerContext, model_name: str) -> Any:
    def load() -> Any:
        import_torch()
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name, device=_torch_device(context))
        logger.info("GPU worker loaded embedding model '%s'", model_name)
        return model

    return context.cached(("embeddings", model_name), load)


def embeddings_load(context: WorkerContext, args: dict[str, Any]) -> None:
    _embedding_model(context, str(args["model_name"]))


def embeddings_encode(context: WorkerContext, args: dict[str, Any]) -> np.ndarray:
    model = _embedding_model(context, str(args["model_name"]))
    texts = [str(text) for text in args["texts"]]
    embeddings = model.encode(texts, normalize_embeddings=bool(args.get("normalize", False)), convert_to_numpy=True)
    return np.asarray(embeddings, dtype=np.float32)


OPERATIONS: dict[str, Callable[[WorkerContext, dict[str, Any]], Any]] = {
    "stt.load": stt_load,
    "stt.transcribe": stt_transcribe,
    "tts.silero_load": tts_silero_load,
    "tts.silero": tts_silero,
    "embeddings.load": embeddings_load,
    "embeddings.encode": embeddings_encode,
}
