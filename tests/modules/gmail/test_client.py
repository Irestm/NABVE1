from __future__ import annotations

import json

import keyring
import pytest

from modules.gmail import client as gmail_client


def test_parse_sender_extracts_email_and_display_name() -> None:
    email, name = gmail_client._parse_sender('"Ira Petrova" <ira@example.com>')
    assert email == "ira@example.com"
    assert name == "Ira Petrova"


def test_parse_sender_falls_back_to_email_when_no_display_name() -> None:
    email, name = gmail_client._parse_sender("ira@example.com")
    assert email == "ira@example.com"
    assert name == "ira@example.com"


def test_extract_header_is_case_insensitive() -> None:
    headers = [{"name": "Subject", "value": "Hello"}]
    assert gmail_client._extract_header(headers, "subject") == "Hello"


def test_extract_header_missing_returns_empty_string() -> None:
    assert gmail_client._extract_header([], "From") == ""


class _FakeExecutable:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeMessages:
    def __init__(self, details_by_id: dict[str, dict]) -> None:
        self._details_by_id = details_by_id

    def get(self, userId, id, format, metadataHeaders):
        return _FakeExecutable(self._details_by_id[id])


class _FakeHistory:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    def list(self, userId, startHistoryId, historyTypes):
        return _FakeExecutable(self._response, self._error)


class _FakeUsers:
    def __init__(self, history: _FakeHistory, messages: _FakeMessages) -> None:
        self._history = history
        self._messages = messages

    def history(self):
        return self._history

    def messages(self):
        return self._messages


class _FakeService:
    def __init__(self, history: _FakeHistory, messages: _FakeMessages) -> None:
        self._users = _FakeUsers(history, messages)

    def users(self):
        return self._users


def test_list_new_messages_returns_messages_and_new_cursor() -> None:
    history_response = {
        "history": [{"messagesAdded": [{"message": {"id": "m1"}}, {"message": {"id": "m2"}}]}],
        "historyId": "999",
    }
    details = {
        "m1": {
            "payload": {"headers": [{"name": "From", "value": "Ira <ira@example.com>"}, {"name": "Subject", "value": "Hi"}]},
            "snippet": "hello there",
        },
        "m2": {
            "payload": {"headers": [{"name": "From", "value": "bob@example.com"}, {"name": "Subject", "value": ""}]},
            "snippet": "yo",
        },
    }
    service = _FakeService(_FakeHistory(history_response), _FakeMessages(details))

    messages, new_cursor = gmail_client.list_new_messages(service, "100")

    assert new_cursor == "999"
    assert messages == [
        {
            "id": "m1",
            "from_email": "ira@example.com",
            "from_name": "Ira",
            "subject": "Hi",
            "snippet": "hello there",
        },
        {
            "id": "m2",
            "from_email": "bob@example.com",
            "from_name": "bob@example.com",
            "subject": "",
            "snippet": "yo",
        },
    ]


def test_list_new_messages_dedupes_repeated_message_ids() -> None:
    history_response = {
        "history": [
            {"messagesAdded": [{"message": {"id": "m1"}}]},
            {"messagesAdded": [{"message": {"id": "m1"}}]},
        ],
        "historyId": "999",
    }
    details = {
        "m1": {
            "payload": {"headers": [{"name": "From", "value": "ira@example.com"}]},
            "snippet": "hello",
        }
    }
    service = _FakeService(_FakeHistory(history_response), _FakeMessages(details))

    messages, _ = gmail_client.list_new_messages(service, "100")

    assert len(messages) == 1


def test_list_new_messages_no_history_returns_empty() -> None:
    service = _FakeService(_FakeHistory({"historyId": "100"}), _FakeMessages({}))

    messages, new_cursor = gmail_client.list_new_messages(service, "100")

    assert messages == []
    assert new_cursor == "100"


def test_list_new_messages_raises_history_expired_on_404() -> None:
    import httplib2
    from googleapiclient.errors import HttpError

    error = HttpError(httplib2.Response({"status": 404}), b"not found")
    service = _FakeService(_FakeHistory(error=error), _FakeMessages({}))

    with pytest.raises(gmail_client.GmailHistoryExpired):
        gmail_client.list_new_messages(service, "stale-cursor")


def test_list_new_messages_reraises_non_404_http_error() -> None:
    import httplib2
    from googleapiclient.errors import HttpError

    error = HttpError(httplib2.Response({"status": 500}), b"server error")
    service = _FakeService(_FakeHistory(error=error), _FakeMessages({}))

    with pytest.raises(HttpError):
        gmail_client.list_new_messages(service, "cursor")


def test_credentials_to_blob_round_trips_expected_fields() -> None:
    class _FakeCreds:
        token = "access-token"
        refresh_token = "refresh-token"
        token_uri = "https://oauth2.googleapis.com/token"
        client_id = "client-id"
        client_secret = "client-secret"

    import json

    blob = gmail_client.credentials_to_blob(_FakeCreds())
    data = json.loads(blob)
    assert data == {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }


def test_get_oauth_client_credentials_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("ASSISTANT_GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("ASSISTANT_GMAIL_CLIENT_SECRET", raising=False)

    with pytest.raises(RuntimeError):
        gmail_client.get_oauth_client_credentials()


def test_get_oauth_client_credentials_returns_env_values(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_ID", "id")
    monkeypatch.setenv("ASSISTANT_GMAIL_CLIENT_SECRET", "secret")

    assert gmail_client.get_oauth_client_credentials() == ("id", "secret")


def test_load_stored_credentials_missing_blob_raises_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)

    with pytest.raises(RuntimeError, match="python -m modules.gmail.login"):
        gmail_client._load_stored_credentials()


def test_load_stored_credentials_incomplete_blob_raises_actionable_error(monkeypatch) -> None:
    """Regression: a malformed/partial stored blob (hand-edited, corrupted,
    or written by an older format) used to surface as a bare KeyError from
    `data["refresh_token"]` — a confusing raw traceback instead of the same
    clear "run the login helper" guidance every other missing-credentials
    path in this module already gives."""
    incomplete = json.dumps({"token": "abc", "client_id": "id"})  # missing refresh_token/token_uri/client_secret
    monkeypatch.setattr(keyring, "get_password", lambda service, username: incomplete)

    with pytest.raises(RuntimeError, match="incomplete"):
        gmail_client._load_stored_credentials()


def test_load_stored_credentials_complete_blob_succeeds(monkeypatch) -> None:
    complete = json.dumps(
        {
            "token": "abc",
            "refresh_token": "refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "id",
            "client_secret": "secret",
        }
    )
    monkeypatch.setattr(keyring, "get_password", lambda service, username: complete)

    creds = gmail_client._load_stored_credentials()

    assert creds.refresh_token == "refresh"
    assert creds.client_id == "id"
