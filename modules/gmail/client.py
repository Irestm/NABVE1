from __future__ import annotations

import json
import os
import re
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

KEYRING_SERVICE = "assistant-gmail"
KEYRING_USERNAME = "token"

# read-only by design — see modules/messaging's original constraint that
# email stays a notify-only source, never dictate-and-send like Telegram.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailHistoryExpired(Exception):
    """Raised when the stored historyId cursor is no longer valid (Gmail
    only retains history for a limited window). The caller (GmailPoller)
    should treat this the same as a first-ever run with no cursor at all —
    resync from "now", not a hard failure."""


def get_oauth_client_credentials() -> tuple[str, str]:
    """App-identity credentials (env vars, not keyring) — mirrors
    modules.telegram.client's ASSISTANT_TELEGRAM_API_ID/_API_HASH split:
    these identify the OAuth *application*, not any individual user."""
    client_id = os.environ.get("ASSISTANT_GMAIL_CLIENT_ID")
    client_secret = os.environ.get("ASSISTANT_GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Gmail API credentials are missing. Set the ASSISTANT_GMAIL_CLIENT_ID and "
            "ASSISTANT_GMAIL_CLIENT_SECRET environment variables (create an OAuth client at "
            "https://console.cloud.google.com/apis/credentials)."
        )
    return client_id, client_secret


def _load_stored_credentials() -> Any:
    """Rebuilds a google.oauth2.credentials.Credentials from the JSON blob
    stored in keyring by modules.gmail.login. Unlike Telethon's single
    opaque session string, Google's client needs the refresh token plus
    client id/secret/token URI together to refresh an expired access
    token, so all of it travels as one JSON blob rather than separate
    keyring entries."""
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("keyring is not installed. Install it with: pip install keyring") from exc

    from google.oauth2.credentials import Credentials

    blob = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if not blob:
        raise RuntimeError(
            "No stored Gmail credentials found. Run the interactive login helper once with: "
            "python -m modules.gmail.login"
        )
    data = json.loads(blob)
    missing = [key for key in ("refresh_token", "token_uri", "client_id", "client_secret") if not data.get(key)]
    if missing:
        # A malformed/partial blob (hand-edited, corrupted, or written by an
        # older format) would otherwise surface as a bare KeyError here —
        # same "run the login helper" guidance as the missing-blob case
        # above, rather than a confusing raw traceback several layers
        # removed from the actual problem.
        raise RuntimeError(
            f"Stored Gmail credentials are incomplete (missing: {', '.join(missing)}). "
            "Run the interactive login helper again with: python -m modules.gmail.login"
        )
    return Credentials(
        token=data.get("token"),
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=SCOPES,
    )


def _store_credentials(creds: Any) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, credentials_to_blob(creds))


def credentials_to_blob(creds: Any) -> str:
    return json.dumps(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
        }
    )


def ensure_credentials() -> Any:
    """Loads the stored credentials, refreshing (and re-persisting) the
    access token if it has expired. Raises RuntimeError with the same
    "run the login helper" guidance as modules.telegram.client's
    equivalent if nothing is stored yet."""
    from google.auth.transport.requests import Request

    creds = _load_stored_credentials()
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _store_credentials(creds)
    return creds


def build_service(creds: Any) -> Any:
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_current_history_id(service: Any) -> str:
    profile = service.users().getProfile(userId="me").execute()
    return str(profile["historyId"])


def get_current_email(service: Any) -> str:
    profile = service.users().getProfile(userId="me").execute()
    return str(profile["emailAddress"])


def _extract_header(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _parse_sender(raw_from: str) -> tuple[str, str]:
    """'Ira Petrova <ira@example.com>' -> ("ira@example.com", "Ira Petrova"),
    falling back to the email itself as the label when there's no display
    name (a bare 'ira@example.com' From header)."""
    match = _EMAIL_RE.search(raw_from)
    email = match.group(0) if match else raw_from.strip()
    name = raw_from.replace(f"<{email}>", "").strip().strip('"') or email
    return email, name


def list_new_messages(service: Any, start_history_id: str) -> tuple[list[dict[str, str]], str]:
    """Returns (messages, new_history_id). Each message dict has
    from_email/from_name/subject/snippet. Raises GmailHistoryExpired if
    Gmail no longer has history back to start_history_id."""
    from googleapiclient.errors import HttpError

    try:
        response = (
            service.users()
            .history()
            .list(userId="me", startHistoryId=start_history_id, historyTypes=["messageAdded"])
            .execute()
        )
    except HttpError as exc:
        if getattr(exc, "resp", None) is not None and exc.resp.status == 404:
            raise GmailHistoryExpired(str(exc)) from exc
        raise

    message_ids: list[str] = []
    for history_record in response.get("history", []):
        for added in history_record.get("messagesAdded", []):
            message_ids.append(added["message"]["id"])

    # history.list can paginate too, but a local single-user assistant
    # polling every minute will essentially never accumulate enough new
    # mail in one interval to hit a second page — not worth a pageToken
    # loop for this use case.

    messages: list[dict[str, str]] = []
    for message_id in dict.fromkeys(message_ids):  # de-dup, preserve order
        detail = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["From", "Subject"])
            .execute()
        )
        headers = detail.get("payload", {}).get("headers", [])
        email, name = _parse_sender(_extract_header(headers, "From"))
        messages.append(
            {
                "id": message_id,
                "from_email": email,
                "from_name": name,
                "subject": _extract_header(headers, "Subject"),
                "snippet": detail.get("snippet", ""),
            }
        )

    new_history_id = str(response.get("historyId", start_history_id))
    return messages, new_history_id
