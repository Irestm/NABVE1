from __future__ import annotations

import pytest

from modules.ai_bridge.providers.base import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderUnavailable,
    flatten_messages,
    health_from_error,
    parse_json_reply,
    split_system,
    with_schema_instruction,
)


def test_parse_json_reply_accepts_plain_fenced_and_wrapped_json() -> None:
    assert parse_json_reply("p", '{"a": 1}') == {"a": 1}
    assert parse_json_reply("p", '```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json_reply("p", 'Вот ответ: {"a": 3} — готово') == {"a": 3}


def test_parse_json_reply_raises_bad_response_on_garbage() -> None:
    with pytest.raises(ProviderBadResponse):
        parse_json_reply("p", "не json")


def test_split_system_separates_and_joins_system_messages() -> None:
    system, rest = split_system(
        [
            {"role": "system", "content": "A"},
            {"role": "user", "content": "q"},
            {"role": "system", "content": "B"},
        ]
    )

    assert system == "A\n\nB"
    assert rest == [{"role": "user", "content": "q"}]


def test_split_system_without_system_messages() -> None:
    assert split_system([{"role": "user", "content": "q"}]) == (None, [{"role": "user", "content": "q"}])


def test_schema_instruction_goes_first_and_flatten_joins_everything() -> None:
    messages = with_schema_instruction([{"role": "user", "content": "q"}], {"type": "object"})

    assert messages[0]["role"] == "system"
    assert '"type": "object"' in messages[0]["content"]
    assert flatten_messages(messages).endswith("\n\nq")


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderAuthError("p", "x"), "auth_error"),
        (ProviderRateLimited("p", "x"), "rate_limited"),
        (ProviderUnavailable("p", "x"), "unavailable"),
    ],
)
def test_health_from_error_maps_status(error: Exception, status: str) -> None:
    assert health_from_error("p", error).status == status  # type: ignore[arg-type]
