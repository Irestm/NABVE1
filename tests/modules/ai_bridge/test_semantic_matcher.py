from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from core.gpu_worker.client import GpuWorkerOperationError, GpuWorkerUnavailable
from modules.ai_bridge import semantic_matcher


@pytest.fixture(autouse=True)
def _reset_shared_model_cache() -> None:
    semantic_matcher._models.clear()
    semantic_matcher._unavailable_reasons.clear()
    yield
    semantic_matcher._models.clear()
    semantic_matcher._unavailable_reasons.clear()


def _fake_model(vectors: dict[str, list[float]]) -> SimpleNamespace:
    def encode(texts: list[str], **kwargs: object) -> np.ndarray:
        return np.array([vectors[text] for text in texts])

    return SimpleNamespace(encode=encode)


class _FakeWorkerClient:
    def __init__(self, failure: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._failure = failure

    def call(self, op: str, args: dict[str, object], timeout: float) -> object:
        if not str(args.get("model_name", "")).endswith("-model"):
            raise GpuWorkerUnavailable("only test models are served here")
        self.calls.append((op, args))
        if self._failure is not None:
            raise self._failure
        if op == "embeddings.encode":
            return np.array([[float(len(text)), 1.0] for text in args["texts"]])  # type: ignore[union-attr]
        return None


def test_get_shared_model_returns_the_same_object_for_the_same_name(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeWorkerClient()
    monkeypatch.setattr(semantic_matcher, "_client", lambda: client)
    monkeypatch.setattr(semantic_matcher, "_package_installed", lambda package: True)

    first = semantic_matcher.get_shared_model("test-model")
    second = semantic_matcher.get_shared_model("test-model")

    assert first is second
    assert client.calls == [("embeddings.load", {"model_name": "test-model"})]


def test_shared_model_encodes_through_the_gpu_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeWorkerClient()
    monkeypatch.setattr(semantic_matcher, "_client", lambda: client)
    monkeypatch.setattr(semantic_matcher, "_package_installed", lambda package: True)

    model = semantic_matcher.get_shared_model("test-model")
    vectors = model.encode(["ab", "abc"], normalize_embeddings=True, convert_to_numpy=True)

    assert vectors.tolist() == [[2.0, 1.0], [3.0, 1.0]]
    assert client.calls[-1] == (
        "embeddings.encode",
        {"model_name": "test-model", "texts": ["ab", "abc"], "normalize": True},
    )


def test_failed_model_load_is_cached_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeWorkerClient(GpuWorkerOperationError("embeddings.load", "OSError", "no network"))
    monkeypatch.setattr(semantic_matcher, "_client", lambda: client)
    monkeypatch.setattr(semantic_matcher, "_package_installed", lambda package: True)

    assert semantic_matcher.get_shared_model("broken-model") is None
    assert semantic_matcher.get_shared_model("broken-model") is None
    assert semantic_matcher.unavailable_reason("broken-model") is not None
    assert len(client.calls) == 1


def test_unreachable_worker_is_not_cached_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeWorkerClient(GpuWorkerUnavailable("disabled"))
    monkeypatch.setattr(semantic_matcher, "_client", lambda: client)
    monkeypatch.setattr(semantic_matcher, "_package_installed", lambda package: True)

    assert semantic_matcher.get_shared_model("test-model") is None
    assert semantic_matcher.unavailable_reason("test-model") is None


def test_get_shared_model_returns_none_and_caches_reason_when_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", None)

    assert semantic_matcher.get_shared_model("missing-model") is None
    assert semantic_matcher.unavailable_reason("missing-model") is not None


def test_semantic_matcher_build_returns_false_when_model_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(semantic_matcher, "get_shared_model", lambda model_name: None)
    matcher = semantic_matcher.SemanticMatcher()

    assert matcher.build({"weight": ("я вешу 78",)}) is False
    assert matcher.best_match("я вешу 80") is None


def test_semantic_matcher_best_match_picks_closest_catalog_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {
        "я вешу 78": [1.0, 0.0],
        "я съел овсянку": [0.0, 1.0],
        "я сегодня вешу 80": [1.0, 0.0],
    }
    monkeypatch.setattr(semantic_matcher, "get_shared_model", lambda model_name: _fake_model(vectors))

    matcher = semantic_matcher.SemanticMatcher()
    assert matcher.build({"weight": ("я вешу 78",), "meal": ("я съел овсянку",)}) is True

    match = matcher.best_match("я сегодня вешу 80")
    assert match is not None
    label, score = match
    assert label == "weight"
    assert score == pytest.approx(1.0)


def test_semantic_matcher_build_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _get_shared_model(model_name: str) -> SimpleNamespace:
        calls["count"] += 1
        return _fake_model({"a": [1.0, 0.0]})

    monkeypatch.setattr(semantic_matcher, "get_shared_model", _get_shared_model)
    matcher = semantic_matcher.SemanticMatcher()

    matcher.build({"a": ("a",)})
    matcher.build({"a": ("a",)})

    assert calls["count"] == 1
