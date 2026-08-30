from __future__ import annotations

from fastapi.testclient import TestClient

import core.main as main_module
from core.config import settings
from core.main import app

client = TestClient(app)
AUTH = {"X-Assistant-Token": settings.api_token}


def test_conversation_returns_recent_turns_newest_last() -> None:
    main_module.conversation_log.append("user", "какая погода в киеве", "voice")
    main_module.conversation_log.append("assistant", "Сегодня ясно, 20 градусов.", "voice")

    response = client.get("/api/conversation", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert [(turn["role"], turn["text"], turn["source"]) for turn in body] == [
        ("user", "какая погода в киеве", "voice"),
        ("assistant", "Сегодня ясно, 20 градусов.", "voice"),
    ]
    assert body[0]["timestamp"].endswith("+00:00")


def test_conversation_honours_the_limit_query_param() -> None:
    for index in range(5):
        main_module.conversation_log.append("user", f"реплика {index}", "text")

    response = client.get("/api/conversation?limit=2", headers=AUTH)

    assert response.status_code == 200
    assert [turn["text"] for turn in response.json()] == ["реплика 3", "реплика 4"]


def test_conversation_without_auth_is_rejected() -> None:
    assert client.get("/api/conversation").status_code == 401


def test_confirming_a_command_records_its_outcome_message(monkeypatch) -> None:
    from core.models import CommandResponse, CommandStatus

    async def fake_confirm(token: str, approved: bool) -> CommandResponse:
        return CommandResponse(status=CommandStatus.EXECUTED, command="shutdown", message="Компьютер выключается.")

    monkeypatch.setattr(main_module.dispatcher, "confirm", fake_confirm)

    response = client.post(
        "/api/command/confirm", headers=AUTH, json={"token": "abc", "approved": True}
    )

    assert response.status_code == 200
    log = client.get("/api/conversation", headers=AUTH).json()
    assert log[-1] == {
        "timestamp": log[-1]["timestamp"],
        "role": "assistant",
        "text": "Компьютер выключается.",
        "source": "text",
    }


def test_clear_endpoint_wipes_the_transcript_and_short_term_memory(monkeypatch) -> None:
    main_module.conversation_log.append("user", "первая реплика", "text")
    main_module.conversation_log.append("assistant", "первый ответ", "text")
    main_module.voice_loop._last_exchange = "Пользователь спросил ..."

    response = client.post("/api/conversation/clear", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    assert client.get("/api/conversation", headers=AUTH).json() == []
    assert main_module.voice_loop._last_exchange is None


def test_clear_endpoint_requires_auth() -> None:
    assert client.post("/api/conversation/clear").status_code == 401
