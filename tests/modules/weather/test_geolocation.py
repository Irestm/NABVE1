from __future__ import annotations

from modules.weather import geolocation


class _FakeResponse:
    def __init__(self, payload: dict, *, raise_on_status: bool = False) -> None:
        self._payload = payload
        self._raise_on_status = raise_on_status

    def raise_for_status(self) -> None:
        if self._raise_on_status:
            raise RuntimeError("HTTP error")

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _install_fake_client(monkeypatch, response: _FakeResponse | Exception) -> None:
    monkeypatch.setattr(geolocation.httpx, "AsyncClient", lambda timeout: _FakeAsyncClient(response))


async def test_detect_city_from_ip_returns_the_city(monkeypatch) -> None:
    _install_fake_client(monkeypatch, _FakeResponse({"city": "Kyiv", "country": "Ukraine"}))

    assert await geolocation.detect_city_from_ip() == "Kyiv"


async def test_detect_city_from_ip_returns_none_when_city_missing(monkeypatch) -> None:
    _install_fake_client(monkeypatch, _FakeResponse({"country": "Ukraine"}))

    assert await geolocation.detect_city_from_ip() is None


async def test_detect_city_from_ip_returns_none_on_http_error(monkeypatch) -> None:
    _install_fake_client(monkeypatch, _FakeResponse({}, raise_on_status=True))

    assert await geolocation.detect_city_from_ip() is None


async def test_detect_city_from_ip_returns_none_when_provider_reports_failure(monkeypatch) -> None:
    _install_fake_client(monkeypatch, _FakeResponse({"success": False, "message": "invalid IP"}))

    assert await geolocation.detect_city_from_ip() is None


async def test_detect_city_from_ip_returns_none_on_network_failure(monkeypatch) -> None:
    _install_fake_client(monkeypatch, ConnectionError("offline"))

    assert await geolocation.detect_city_from_ip() is None
