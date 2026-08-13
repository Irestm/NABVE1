from __future__ import annotations

import threading
from collections.abc import Iterator

from core.config import DATA_DIR
from core.logger import get_logger
from modules.ai_bridge.system_prompt import apply_system_prompt
from modules.hardware_adaptive.model_tiers import MODEL_TIERS, TIER_NONE

logger = get_logger(__name__)

MODELS_DIR = DATA_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# GGUF filenames expected under MODELS_DIR for each tier. The weights
# themselves aren't part of the repo and must be downloaded separately (e.g.
# from Hugging Face) into that directory before load_model() can succeed.
_MODEL_FILENAMES: dict[str, str] = {
    "mid": "qwen2.5-3b-instruct-q4_k_m.gguf",
    "high": "qwen2.5-7b-instruct-q4_k_m.gguf",
}

_DEFAULT_CONTEXT_SIZE = 4096
_DEFAULT_MAX_TOKENS = 512


class LocalInferenceEngine:
    """Thin wrapper around llama-cpp-python with full CUDA GPU offload
    (n_gpu_layers=-1). One instance holds at most one loaded GGUF model,
    matching the tier picked by modules.hardware_adaptive.model_tiers."""

    def __init__(self) -> None:
        self._llm: object | None = None
        self._tier: str | None = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    @property
    def tier(self) -> str | None:
        return self._tier

    def load_model(self, tier: str) -> None:
        if tier == TIER_NONE or tier not in MODEL_TIERS:
            raise ValueError(f"Cannot load local model for tier '{tier}'")

        with self._lock:
            if self._llm is not None and self._tier == tier:
                return

            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise RuntimeError(
                    "llama-cpp-python is not installed. Install a CUDA-enabled build, e.g.: "
                    "CMAKE_ARGS='-DGGML_CUDA=on' pip install llama-cpp-python"
                ) from exc

            model_path = MODELS_DIR / _MODEL_FILENAMES[tier]
            if not model_path.exists():
                raise FileNotFoundError(
                    f"Model file for tier '{tier}' not found at {model_path}. "
                    "Download the matching GGUF file into data/models/ first."
                )

            logger.info("Loading local model tier='%s' from %s (CUDA GPU offload)", tier, model_path)
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=_DEFAULT_CONTEXT_SIZE,
                n_gpu_layers=-1,
                verbose=False,
            )
            self._tier = tier

    def generate(self, prompt: str, *, max_tokens: int = _DEFAULT_MAX_TOKENS) -> str:
        wrapped_prompt = apply_system_prompt(prompt)
        with self._lock:
            # Checked inside the lock, not before it: unload() takes the
            # same lock, so checking is_loaded first and calling
            # create_chat_completion() second (two separate steps) left a
            # window where unload() could run in between and this would
            # crash on a None self._llm instead of raising the clean
            # RuntimeError callers (LocalEngineAdapter) already handle.
            if self._llm is None:
                raise RuntimeError("No local model loaded; call load_model(tier) first")
            response = self._llm.create_chat_completion(  # type: ignore[attr-defined]
                messages=[{"role": "user", "content": wrapped_prompt}],
                max_tokens=max_tokens,
            )
        return response["choices"][0]["message"]["content"].strip()

    def generate_stream(self, prompt: str, *, max_tokens: int = _DEFAULT_MAX_TOKENS) -> Iterator[str]:
        """Same as generate(), but yields text deltas as llama.cpp produces
        them instead of waiting for the full completion — lets the caller
        start speaking the first sentence long before the model has finished
        generating the rest of the reply. Holds the engine lock for the
        entire generation, same as generate(): only one generation (streamed
        or not) may run against this single loaded model at a time."""
        wrapped_prompt = apply_system_prompt(prompt)
        with self._lock:
            # See the comment in generate() above — same check-inside-lock
            # reasoning applies here.
            if self._llm is None:
                raise RuntimeError("No local model loaded; call load_model(tier) first")
            stream = self._llm.create_chat_completion(  # type: ignore[attr-defined]
                messages=[{"role": "user", "content": wrapped_prompt}],
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk["choices"][0]["delta"].get("content")
                if delta:
                    yield delta

    def unload(self) -> None:
        with self._lock:
            self._llm = None
            self._tier = None
