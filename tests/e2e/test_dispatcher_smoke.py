from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.bootstrap import compose
from core.models import CommandStatus


@pytest.fixture(scope="module")
def composed():
    return compose()


def test_expected_commands_are_registered(composed) -> None:
    names = {c.name for c in composed.dispatcher.list_commands()}
    assert {
        "profile_set",
        "profile_get",
        "profile_forget",
        "calendar_create_event",
        "calendar_delete_event",
        "shutdown",
        "restart",
    }.issubset(names)


async def test_profile_set_get_forget_roundtrip_through_the_dispatcher(composed) -> None:
    dispatcher = composed.dispatcher
    key = "test_e2e_smoke_key"
    try:
        response = await dispatcher.dispatch("profile_set", {"key": key, "value": "hello"})
        assert response.status == CommandStatus.EXECUTED

        response = await dispatcher.dispatch("profile_get", {"key": key})
        assert response.status == CommandStatus.EXECUTED
        assert response.result["value"] == "hello"
    finally:
        await dispatcher.dispatch("profile_forget", {"key": key})


async def test_calendar_create_and_delete_through_the_dispatcher(composed) -> None:
    dispatcher = composed.dispatcher
    event_time = (datetime.now() + timedelta(days=1)).isoformat()

    response = await dispatcher.dispatch(
        "calendar_create_event", {"title": "Smoke test event", "event_time": event_time}
    )
    assert response.status == CommandStatus.EXECUTED
    event_id = response.result["id"]

    response = await dispatcher.dispatch("calendar_delete_event", {"event_id": event_id})
    assert response.status == CommandStatus.EXECUTED
    assert response.result["deleted"] is True


async def test_dangerous_command_requires_confirmation(composed) -> None:
    response = await composed.dispatcher.dispatch("shutdown", {})
    assert response.status == CommandStatus.CONFIRMATION_REQUIRED
    assert response.token

    # Cancel rather than actually approve — this is a smoke test, not a
    # request to power off the machine running the suite.
    response = await composed.dispatcher.confirm(response.token, approved=False)
    assert response.status == CommandStatus.CANCELLED
