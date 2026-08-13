from __future__ import annotations

import json
import os
from typing import Any, NoReturn

from core.cli_ui import confirm_identity_mismatch, print_error_panel, print_identity_panel
from core.logger import get_logger
from modules.gmail.client import KEYRING_SERVICE, KEYRING_USERNAME, SCOPES, build_service, credentials_to_blob

logger = get_logger(__name__)


def _fail(title: str, message: str, hint: str | None = None) -> NoReturn:
    print_error_panel(title, message, hint)
    raise SystemExit(1)


def _get_email(creds: Any) -> str:
    service = build_service(creds)
    profile = service.users().getProfile(userId="me").execute()
    return str(profile["emailAddress"])


def _needs_confirmation(old_email: str | None, new_email: str) -> bool:
    """True only when there WAS a previously stored, inspectable account
    (old_email is not None) AND it's a different address than the one
    just authenticated. No prior account — nothing to compare against,
    never needs confirmation."""
    return old_email is not None and old_email.lower() != new_email.lower()


def _inspect_existing_account(data: dict[str, Any]) -> str | None:
    """Briefly re-authenticates with the ALREADY-STORED credentials purely
    to identify whose account it is, so a re-login with a different
    account can be caught before silently overwriting it. Best-effort: any
    failure here (revoked token, network hiccup) just means "couldn't
    determine the old identity", not a hard failure of the login flow
    itself — the new login can still proceed."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=data.get("token"),
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=SCOPES,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return _get_email(creds)
    except Exception:
        logger.warning("Could not inspect the existing stored Gmail credentials", exc_info=True)
        return None


def _run_login() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        _fail(
            "Gmail login failed",
            "google-auth-oauthlib is not installed.",
            "Install it with: pip install google-auth-oauthlib",
        )

    try:
        import keyring
    except ImportError:
        _fail("Gmail login failed", "keyring is not installed.", "Install it with: pip install keyring")

    client_id = os.environ.get("ASSISTANT_GMAIL_CLIENT_ID")
    client_secret = os.environ.get("ASSISTANT_GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        _fail(
            "Gmail login failed",
            "ASSISTANT_GMAIL_CLIENT_ID / ASSISTANT_GMAIL_CLIENT_SECRET are not set.",
            "Create an OAuth client (type: Desktop app) at "
            "https://console.cloud.google.com/apis/credentials and set both environment "
            "variables first.",
        )

    old_email: str | None = None
    existing_blob = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if existing_blob:
        old_email = _inspect_existing_account(json.loads(existing_blob))

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    try:
        creds = flow.run_local_server(port=0)
    except Exception as exc:
        # _fail's friendly panel only ever shows str(exc) to the user — if
        # the real cause is a code bug rather than a user-facing auth
        # problem (browser closed, network hiccup, ...), the traceback
        # would otherwise be gone for good the moment this process exits.
        logger.exception("Gmail login failed")
        _fail("Gmail login failed", str(exc))

    new_email = _get_email(creds)

    if _needs_confirmation(old_email, new_email):
        assert old_email is not None
        if not confirm_identity_mismatch("Gmail", {"Email": old_email}, {"Email": new_email}):
            print_error_panel(
                "Gmail login cancelled", "Keeping the existing stored credentials — nothing was changed."
            )
            return

    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, credentials_to_blob(creds))
    print_identity_panel("Gmail login successful", {"Email": new_email, "Stored in": "system keyring"})


def main() -> None:
    _run_login()


if __name__ == "__main__":
    main()
