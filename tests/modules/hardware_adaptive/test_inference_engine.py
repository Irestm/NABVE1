from __future__ import annotations

import json

import httpx
import pytest

from modules.hardware_adaptive import inference_engine
from modules.hardware_adaptive.inference_engine import LocalInferenceEngine, OllamaUnavailableError
from modules.hardware_adaptive.model_tiers import TIER_HIGH, TIER_MID, TIER_NONE


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        return iter(self._lines)


class _FakeStreamContext:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeStreamResponse:
        return self._response

    def __exit__(self, *args: object) -> None:
        return None


class _FakeClient:
    def __init__(self, stream_response: _FakeStreamResponse) -> None:
        self._stream_response = stream_response
        self.stream_calls: list[tuple[str, str, dict]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def stream(self, method: str, url: str, *, json: dict):
        self.stream_calls.append((method, url, json))
        return _FakeStreamContext(self._stream_response)


def _pull_line(**kwargs: object) -> str:
    return json.dumps(kwargs)


def _chat_line(*, content: str | None = None, done: bool = False) -> str:
    payload: dict = {"done": done}
    if content is not None:
        payload["message"] = {"content": content}
    return json.dumps(payload)


def test_load_model_raises_for_unknown_tier() -> None:
    engine = LocalInferenceEngine()

    with pytest.raises(ValueError):
        engine.load_model(TIER_NONE)

    with pytest.raises(ValueError):
        engine.load_model("bogus")


def test_load_model_pulls_when_not_already_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": []})
    )
    pulled: list[str] = []
    monkeypatch.setattr(engine, "_pull", lambda model_name: pulled.append(model_name))

    engine.load_model(TIER_MID)

    assert pulled == ["qwen2.5:3b"]
    assert engine.is_loaded is True
    assert engine.tier == TIER_MID


def test_load_model_skips_pull_when_already_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx,
        "get",
        lambda url, timeout: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]}),
    )
    pulled: list[str] = []
    monkeypatch.setattr(engine, "_pull", lambda model_name: pulled.append(model_name))

    engine.load_model(TIER_MID)

    assert pulled == []
    assert engine.is_loaded is True


def test_load_model_is_a_noop_when_already_loaded_for_the_same_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    calls: list[str] = []
    monkeypatch.setattr(
        inference_engine.httpx,
        "get",
        lambda url, timeout: (calls.append(1), _FakeResponse({"models": [{"name": "qwen2.5:3b"}]}))[1],
    )
    monkeypatch.setattr(engine, "_pull", lambda model_name: None)

    engine.load_model(TIER_MID)
    engine.load_model(TIER_MID)

    assert len(calls) == 1  # second call short-circuited before ever hitting /api/tags


def test_load_model_switches_tiers_when_a_different_one_is_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx,
        "get",
        lambda url, timeout: _FakeResponse({"models": [{"name": "qwen2.5:3b"}, {"name": "qwen2.5:7b"}]}),
    )
    monkeypatch.setattr(engine, "_pull", lambda model_name: None)

    engine.load_model(TIER_MID)
    engine.load_model(TIER_HIGH)

    assert engine.tier == TIER_HIGH


def test_load_model_raises_unavailable_when_ollama_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()

    def fake_get(url: str, timeout: float):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(inference_engine.httpx, "get", fake_get)

    with pytest.raises(OllamaUnavailableError):
        engine.load_model(TIER_MID)
    assert engine.is_loaded is False


def test_pull_raises_when_ollama_reports_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": []}))
    fake_client = _FakeClient(_FakeStreamResponse([_pull_line(error="model not found")]))
    monkeypatch.setattr(inference_engine.httpx, "Client", lambda timeout: fake_client)

    with pytest.raises(OllamaUnavailableError):
        engine.load_model(TIER_MID)
    assert engine.is_loaded is False


def test_pull_succeeds_through_progress_lines_with_no_error(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": []}))
    fake_client = _FakeClient(
        _FakeStreamResponse([_pull_line(status="pulling"), _pull_line(status="success")])
    )
    monkeypatch.setattr(inference_engine.httpx, "Client", lambda timeout: fake_client)

    engine.load_model(TIER_MID)

    assert engine.is_loaded is True
    assert fake_client.stream_calls[0][2]["name"] == "qwen2.5:3b"


def test_pull_skips_blank_keepalive_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ollama's NDJSON stream can include blank lines as a plain keep-alive,
    # not a progress update — must be skipped, not fail json.loads("").
    engine = LocalInferenceEngine()
    monkeypatch.setattr(inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": []}))
    fake_client = _FakeClient(
        _FakeStreamResponse(["", _pull_line(status="pulling"), "", _pull_line(status="success")])
    )
    monkeypatch.setattr(inference_engine.httpx, "Client", lambda timeout: fake_client)

    engine.load_model(TIER_MID)

    assert engine.is_loaded is True


def test_generate_raises_when_no_model_is_loaded() -> None:
    engine = LocalInferenceEngine()

    with pytest.raises(RuntimeError):
        engine.generate("привет")


def test_generate_sends_the_wrapped_prompt_and_returns_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    )
    monkeypatch.setattr(inference_engine, "apply_system_prompt", lambda text: f"SYSTEM\n\n{text}")
    captured: dict = {}

    def fake_post(url: str, *, json: dict, timeout: float):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"message": {"content": "  привет!  "}})

    engine.load_model(TIER_MID)
    monkeypatch.setattr(inference_engine.httpx, "post", fake_post)

    result = engine.generate("привет")

    assert result == "привет!"
    assert captured["url"] == f"{inference_engine._BASE_URL}/api/chat"
    assert captured["json"]["model"] == "qwen2.5:3b"
    assert captured["json"]["messages"] == [{"role": "user", "content": "SYSTEM\n\nпривет"}]
    assert captured["json"]["stream"] is False


def test_generate_stream_raises_when_no_model_is_loaded() -> None:
    engine = LocalInferenceEngine()

    with pytest.raises(RuntimeError):
        next(engine.generate_stream("привет"))


def test_generate_stream_yields_deltas_in_order_and_stops_on_done(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    )
    monkeypatch.setattr(engine, "_pull", lambda model_name: None)
    engine.load_model(TIER_MID)

    fake_client = _FakeClient(
        _FakeStreamResponse(
            [
                "",
                _chat_line(content="При"),
                _chat_line(content="вет"),
                _chat_line(content="!", done=True),
                _chat_line(content="unreachable after done"),
            ]
        )
    )
    monkeypatch.setattr(inference_engine.httpx, "Client", lambda timeout: fake_client)

    deltas = list(engine.generate_stream("привет"))

    assert deltas == ["При", "вет", "!"]
    assert fake_client.stream_calls[0][1] == f"{inference_engine._BASE_URL}/api/chat"
    assert fake_client.stream_calls[0][2]["stream"] is True


def test_unload_signals_ollama_with_keep_alive_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    )
    monkeypatch.setattr(engine, "_pull", lambda model_name: None)
    engine.load_model(TIER_MID)

    captured: dict = {}
    monkeypatch.setattr(
        inference_engine.httpx,
        "post",
        lambda url, *, json, timeout: captured.update(url=url, json=json) or _FakeResponse({}),
    )

    engine.unload()

    assert engine.is_loaded is False
    assert engine.tier is None
    assert captured["json"] == {"model": "qwen2.5:3b", "keep_alive": 0}


def test_unload_is_a_noop_when_nothing_was_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    calls: list[object] = []
    monkeypatch.setattr(inference_engine.httpx, "post", lambda *a, **k: calls.append(1))

    engine.unload()  # should not raise

    assert calls == []


def test_unload_swallows_a_failed_signal_to_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = LocalInferenceEngine()
    monkeypatch.setattr(
        inference_engine.httpx, "get", lambda url, timeout: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    )
    monkeypatch.setattr(engine, "_pull", lambda model_name: None)
    engine.load_model(TIER_MID)

    def fake_post(url: str, *, json: dict, timeout: float):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(inference_engine.httpx, "post", fake_post)

    engine.unload()  # should not raise even though the signal failed

    assert engine.is_loaded is False
