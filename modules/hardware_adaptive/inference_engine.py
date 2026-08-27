from __future__ import annotations

import json
import threading
from collections.abc import Iterator

import httpx

from core.logger import get_logger
from modules.ai_bridge.system_prompt import apply_system_prompt
from modules.hardware_adaptive.model_tiers import MODEL_TIERS, TIER_NONE

logger = get_logger(__name__)

_BASE_URL = "http://127.0.0.1:11434"
_REQUEST_TIMEOUT_SECONDS = 60.0
# A first-run model pull is a multi-GB download - generous on purpose, this
# only ever applies to that one-time request, not the ordinary chat calls
# below (_REQUEST_TIMEOUT_SECONDS covers those).
_PULL_TIMEOUT_SECONDS = 1800.0
_DEFAULT_CONTEXT_SIZE = 4096
_DEFAULT_MAX_TOKENS = 512


class OllamaUnavailableError(RuntimeError):
    pass


class LocalInferenceEngine:
    """Thin wrapper around a locally-running Ollama server
    (http://127.0.0.1:11434 by default — see https://ollama.com/download)
    instead of a raw llama-cpp-python model held in this process's own
    memory (the previous implementation). Ollama handles GPU offload and
    model download itself against just the NVIDIA driver — no separate
    CUDA toolkit compile step, which is what made the old backend fragile
    to set up in the first place (see AGENT_NOTES.md's entry on this
    switch). Model state (what's "loaded") now lives in Ollama's own
    server process, not here — this class only tracks which tag it last
    asked for."""

    def __init__(self, base_url: str = _BASE_URL) -> None:
        self._base_url = base_url
        self._model_name: str | None = None
        self._tier: str | None = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model_name is not None

    @property
    def tier(self) -> str | None:
        return self._tier

    def load_model(self, tier: str) -> None:
        if tier == TIER_NONE or tier not in MODEL_TIERS:
            raise ValueError(f"Cannot load local model for tier '{tier}'")

        with self._lock:
            if self._model_name is not None and self._tier == tier:
                return

            model_name = MODEL_TIERS[tier].model_name

            try:
                response = httpx.get(f"{self._base_url}/api/tags", timeout=_REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise OllamaUnavailableError(
                    f"Ollama is not reachable at {self._base_url}. Install and start it first: "
                    "https://ollama.com/download"
                ) from exc

            installed = {entry.get("name") for entry in response.json().get("models", [])}
            if model_name not in installed:
                logger.info("Pulling Ollama model '%s' (first run only, may take a while)", model_name)
                self._pull(model_name)

            self._model_name = model_name
            self._tier = tier

    def _pull(self, model_name: str) -> None:
        with httpx.Client(timeout=_PULL_TIMEOUT_SECONDS) as client:
            with client.stream("POST", f"{self._base_url}/api/pull", json={"name": model_name}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    payload = json.loads(line)
                    error = payload.get("error")
                    if error:
                        raise OllamaUnavailableError(f"Failed to pull Ollama model '{model_name}': {error}")

    def _require_model_name(self) -> str:
        with self._lock:
            if self._model_name is None:
                raise RuntimeError("No local model loaded; call load_model(tier) first")
            return self._model_name

    def generate(self, prompt: str, *, max_tokens: int = _DEFAULT_MAX_TOKENS) -> str:
        model_name = self._require_model_name()
        wrapped_prompt = apply_system_prompt(prompt)
        response = httpx.post(
            f"{self._base_url}/api/chat",
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": wrapped_prompt}],
                "stream": False,
                "options": {"num_ctx": _DEFAULT_CONTEXT_SIZE, "num_predict": max_tokens},
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()

    def generate_stream(self, prompt: str, *, max_tokens: int = _DEFAULT_MAX_TOKENS) -> Iterator[str]:
        """Same as generate(), but yields text deltas as Ollama produces
        them (newline-delimited JSON over a chunked HTTP response) instead
        of waiting for the full completion — lets the caller start speaking
        the first sentence long before the model has finished generating
        the rest of the reply."""
        model_name = self._require_model_name()
        wrapped_prompt = apply_system_prompt(prompt)
        with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": wrapped_prompt}],
                    "stream": True,
                    "options": {"num_ctx": _DEFAULT_CONTEXT_SIZE, "num_predict": max_tokens},
                },
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    payload = json.loads(line)
                    delta = payload.get("message", {}).get("content")
                    if delta:
                        yield delta
                    if payload.get("done"):
                        break

    def unload(self) -> None:
        with self._lock:
            model_name = self._model_name
            self._model_name = None
            self._tier = None
        if model_name is None:
            return
        # This class never held the model in its own memory to begin with
        # (Ollama's server does) — "unload" here means asking that server
        # to evict it from VRAM right away (keep_alive: 0) instead of
        # waiting out its own default keep-alive window, mirroring the old
        # backend's immediate-unload behavior. Best-effort: if this request
        # fails, Ollama's own keep-alive timeout still frees it eventually.
        try:
            httpx.post(
                f"{self._base_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            logger.debug("Failed to signal Ollama to unload '%s'", model_name, exc_info=True)
