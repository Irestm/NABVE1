from __future__ import annotations

import importlib.util
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.gpu_worker.client import (
    GpuWorkerClient,
    GpuWorkerError,
    GpuWorkerOperationError,
    get_gpu_worker_client,
)
from core.logger import get_logger

logger = get_logger(__name__)

# Multilingual (not the smaller English-only all-MiniLM-L6-v2), same
# reasoning as modules.hardware_adaptive.command_classifier's original
# module docstring: real usage is Russian/Ukrainian/English voice commands.
# CPU-only, ~470MB, downloaded from HuggingFace on first use and cached
# under ~/.cache/torch/sentence_transformers after that.
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

_LOAD_TIMEOUT_SECONDS = 600.0
_ENCODE_TIMEOUT_SECONDS = 180.0

_models: dict[str, Any] = {}
_unavailable_reasons: dict[str, str] = {}
_models_lock = threading.Lock()


def _client() -> GpuWorkerClient:
    return get_gpu_worker_client()


def _package_installed(package: str) -> bool:
    try:
        return importlib.util.find_spec(package) is not None
    except (ValueError, ImportError):
        return sys.modules.get(package) is not None


class RemoteEmbeddingModel:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def encode(
        self,
        texts: list[str],
        normalize_embeddings: bool = False,
        convert_to_numpy: bool = True,
    ) -> np.ndarray:
        result = _client().call(
            "embeddings.encode",
            {"model_name": self.model_name, "texts": list(texts), "normalize": normalize_embeddings},
            _ENCODE_TIMEOUT_SECONDS,
        )
        return np.asarray(result)


def get_shared_model(model_name: str = DEFAULT_MODEL_NAME) -> Any | None:
    """Returns one shared embedding model handle per `model_name` for the
    whole process. modules.hardware_adaptive.command_classifier and
    modules.fitness_tracker.intent_parser both ask for the same
    DEFAULT_MODEL_NAME and share the exact same model (loaded once, inside
    the GPU worker) instead of each holding its own copy. Never raises: a
    missing package or a failed load is cached and returned as None so
    callers degrade the same way command_classifier already did; a worker
    that could not start is reported as None without being cached."""
    with _models_lock:
        if model_name in _models:
            return _models[model_name]
        if model_name in _unavailable_reasons:
            return None

        if not _package_installed("sentence_transformers"):
            _unavailable_reasons[model_name] = "sentence-transformers is not installed"
            logger.warning(_unavailable_reasons[model_name])
            return None

        try:
            _client().call("embeddings.load", {"model_name": model_name}, _LOAD_TIMEOUT_SECONDS)
        except GpuWorkerOperationError as exc:
            _unavailable_reasons[model_name] = f"Failed to load embedding model '{model_name}': {exc}"
            logger.warning(_unavailable_reasons[model_name], exc_info=True)
            return None
        except GpuWorkerError:
            logger.warning("GPU worker unavailable for embedding model '%s'", model_name, exc_info=True)
            return None

        model = RemoteEmbeddingModel(model_name)
        _models[model_name] = model
        logger.info("Loaded shared embedding model '%s' in the GPU worker", model_name)
        return model


def unavailable_reason(model_name: str = DEFAULT_MODEL_NAME) -> str | None:
    return _unavailable_reasons.get(model_name)


def warm_up(model_name: str = DEFAULT_MODEL_NAME) -> None:
    """Kicks off model load on a background thread — call once at startup so
    the model is already warm by the time the first real request needs it.
    Safe to call more than once (get_shared_model is itself idempotent) and
    safe to call for a model already loaded by an earlier warm_up/first use."""
    threading.Thread(target=get_shared_model, args=(model_name,), daemon=True, name="semantic-matcher-warmup").start()


@dataclass
class SemanticMatcher:
    """Encodes a fixed catalog of (label -> example phrases) once via
    build(), then scores an arbitrary query against every phrase by cosine
    similarity in best_match() — the exact algorithm
    modules.hardware_adaptive.command_classifier used privately before this
    was extracted, generalized so a second catalog (e.g.
    modules.fitness_tracker.intent_parser's intent categories) can reuse it
    against the same shared model rather than loading its own copy."""

    model_name: str = DEFAULT_MODEL_NAME
    _phrase_embeddings: Any = field(default=None, init=False, repr=False)
    _phrase_labels: list[str] = field(default_factory=list, init=False, repr=False)
    _built: bool = field(default=False, init=False, repr=False)

    def build(self, catalog: dict[str, tuple[str, ...]]) -> bool:
        """`catalog` maps a label (a command name, an intent category, ...)
        to its example phrases. Returns whether the matcher is usable —
        False if the shared model failed to load, in which case
        best_match() always returns None afterward. Safe to call more than
        once; only the first call does any work."""
        if self._built:
            return self._phrase_embeddings is not None
        self._built = True

        model = get_shared_model(self.model_name)
        if model is None:
            return False

        phrases: list[str] = []
        labels: list[str] = []
        for label, phrase_list in catalog.items():
            for phrase in phrase_list:
                phrases.append(phrase)
                labels.append(label)

        self._phrase_embeddings = model.encode(phrases, normalize_embeddings=True, convert_to_numpy=True)
        self._phrase_labels = labels
        return True

    def best_match(self, query: str) -> tuple[str, float] | None:
        """(label, score) of the catalog phrase closest to `query`, or None
        if the matcher never built successfully. Callers compare `score`
        against their own threshold — different catalogs have different
        false-positive costs (an immediately-executed system command vs. a
        fitness intent category that only ever leads to a follow-up
        question), so the threshold stays the caller's decision, never baked
        in here."""
        if not self._built or self._phrase_embeddings is None:
            return None
        model = get_shared_model(self.model_name)
        if model is None:
            return None

        query_embedding = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
        similarities = self._phrase_embeddings @ query_embedding
        best_idx = int(similarities.argmax())
        return self._phrase_labels[best_idx], float(similarities[best_idx])
