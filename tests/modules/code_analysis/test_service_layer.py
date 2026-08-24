from __future__ import annotations

import pytest

from core.os_adapter.base import ActiveWindow
from modules.code_analysis import service_layer


class _FakeAdapter:
    def __init__(self, name: str, reply: str | None = None, should_raise: bool = False) -> None:
        self.name = name
        self._reply = reply
        self._should_raise = should_raise

    async def send_prompt(self, text: str, *, fast_mode: bool = True) -> str:
        if self._should_raise:
            raise RuntimeError("adapter down")
        return self._reply or ""


# --- analyze_code -------------------------------------------------------------


async def test_analyze_code_returns_the_first_adapters_reply(monkeypatch) -> None:
    adapter = _FakeAdapter("gemini_api", reply="Это функция сортировки.")
    monkeypatch.setattr(service_layer, "candidate_chain", lambda text: [adapter])

    result = await service_layer.analyze_code("def f(): pass", "объясни")

    assert result == "Это функция сортировки."


async def test_analyze_code_raises_when_every_adapter_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        service_layer, "candidate_chain", lambda text: [_FakeAdapter("a", should_raise=True)]
    )

    with pytest.raises(service_layer.CodeAnalysisError):
        await service_layer.analyze_code("code", "объясни")


# --- fetch_github_file ---------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_headers: dict | None = None

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.last_url = url
        self.last_headers = headers
        return self._response


def _install(monkeypatch, response: _FakeResponse) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(response)
    monkeypatch.setattr(service_layer.httpx, "AsyncClient", lambda timeout: fake_client)
    return fake_client


async def test_fetch_github_file_converts_to_a_raw_url(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    response = _FakeResponse(200, text="print('hi')")
    fake_client = _install(monkeypatch, response)

    code = await service_layer.fetch_github_file(
        "https://github.com/owner/repo/blob/main/src/app.py"
    )

    assert code == "print('hi')"
    assert fake_client.last_url == "https://raw.githubusercontent.com/owner/repo/main/src/app.py"


async def test_fetch_github_file_sends_no_auth_header_without_a_pat(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    response = _FakeResponse(200, text="print('hi')")
    fake_client = _install(monkeypatch, response)

    await service_layer.fetch_github_file("https://github.com/owner/repo/blob/main/a.py")

    assert fake_client.last_headers == {}


async def test_fetch_github_file_sends_the_pat_as_a_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: "my-token")
    response = _FakeResponse(200, text="print('hi')")
    fake_client = _install(monkeypatch, response)

    await service_layer.fetch_github_file("https://github.com/owner/repo/blob/main/a.py")

    assert fake_client.last_headers == {"Authorization": "token my-token"}


async def test_fetch_github_file_404_mentions_private_repos(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    response = _FakeResponse(404)
    _install(monkeypatch, response)

    with pytest.raises(service_layer.CodeAnalysisError, match="приватный"):
        await service_layer.fetch_github_file("https://github.com/owner/repo/blob/main/a.py")


async def test_fetch_github_file_rejects_a_non_blob_url() -> None:
    with pytest.raises(service_layer.CodeAnalysisError):
        await service_layer.fetch_github_file("https://github.com/owner/repo")


async def test_fetch_github_file_raises_on_http_error(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)
    response = _FakeResponse(500)
    _install(monkeypatch, response)

    with pytest.raises(service_layer.CodeAnalysisError):
        await service_layer.fetch_github_file("https://github.com/owner/repo/blob/main/missing.py")


# --- analyze_active_editor ------------------------------------------------------


async def test_analyze_active_editor_reads_the_file_directly_for_pycharm(monkeypatch, tmp_path) -> None:
    code_file = tmp_path / "app.py"
    code_file.write_text("def f(): pass", encoding="utf-8")
    active = ActiveWindow(title=f"app.py — {code_file} — PyCharm", pid=1, wm_class="jetbrains-pycharm")

    class _FakeOsAdapter:
        def get_active_window(self) -> ActiveWindow:
            return active

    monkeypatch.setattr(service_layer, "get_os_adapter", lambda: _FakeOsAdapter())

    async def fake_analyze_code(code: str, instruction: str) -> str:
        assert code == "def f(): pass"
        return "Простая функция-заглушка."

    monkeypatch.setattr(service_layer, "analyze_code", fake_analyze_code)

    result = await service_layer.analyze_active_editor("объясни")

    assert result == "Простая функция-заглушка."


async def test_analyze_active_editor_falls_back_to_screenshot_for_non_pycharm(monkeypatch) -> None:
    active = ActiveWindow(title="main.rs - Visual Studio Code", pid=1, wm_class="code")

    class _FakeOsAdapter:
        def get_active_window(self) -> ActiveWindow:
            return active

    monkeypatch.setattr(service_layer, "get_os_adapter", lambda: _FakeOsAdapter())

    async def fake_capture_screenshot_png() -> bytes:
        return b"fake-png"

    async def fake_analyze_image(image_bytes: bytes, instruction: str) -> str:
        assert image_bytes == b"fake-png"
        return "Код на Rust, объявляет main."

    monkeypatch.setattr(service_layer, "_capture_screenshot_png", fake_capture_screenshot_png)
    monkeypatch.setattr(service_layer, "_analyze_image", fake_analyze_image)

    result = await service_layer.analyze_active_editor("объясни")

    assert result == "Код на Rust, объявляет main."


async def test_analyze_active_editor_falls_back_when_pycharm_title_has_no_real_path(
    monkeypatch,
) -> None:
    active = ActiveWindow(title="app.py — MyProject — PyCharm", pid=1, wm_class="jetbrains-pycharm")

    class _FakeOsAdapter:
        def get_active_window(self) -> ActiveWindow:
            return active

    monkeypatch.setattr(service_layer, "get_os_adapter", lambda: _FakeOsAdapter())

    async def fake_capture_screenshot_png() -> bytes:
        return b"fake-png"

    async def fake_analyze_image(image_bytes: bytes, instruction: str) -> str:
        return "Проанализировано по скриншоту."

    monkeypatch.setattr(service_layer, "_capture_screenshot_png", fake_capture_screenshot_png)
    monkeypatch.setattr(service_layer, "_analyze_image", fake_analyze_image)

    result = await service_layer.analyze_active_editor("объясни")

    assert result == "Проанализировано по скриншоту."


async def test_analyze_active_editor_raises_when_no_active_window(monkeypatch) -> None:
    class _FakeOsAdapter:
        def get_active_window(self) -> None:
            return None

    monkeypatch.setattr(service_layer, "get_os_adapter", lambda: _FakeOsAdapter())

    with pytest.raises(service_layer.CodeAnalysisError):
        await service_layer.analyze_active_editor("объясни")


async def test_analyze_image_raises_without_a_gemini_key(monkeypatch) -> None:
    monkeypatch.setattr(service_layer, "get_secret", lambda name: None)

    with pytest.raises(service_layer.CodeAnalysisError):
        await service_layer._analyze_image(b"fake-png", "объясни")
