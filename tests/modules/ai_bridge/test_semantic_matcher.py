from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

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


def test_get_shared_model_returns_the_same_object_for_the_same_name(monkeypatch: pytest.MonkeyPatch) -> None:
    built = {"count": 0}

    def _fake_sentence_transformer(name: str) -> SimpleNamespace:
        built["count"] += 1
        return SimpleNamespace(name=name)

    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_fake_sentence_transformer),
    )

    first = semantic_matcher.get_shared_model("test-model")
    second = semantic_matcher.get_shared_model("test-model")

    assert first is second
    assert built["count"] == 1


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
