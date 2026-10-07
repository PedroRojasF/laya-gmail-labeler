"""Minimal Gmail API adapter with desktop OAuth and no message logging."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .credential_store import CredentialStoreError, credential_backend

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
KEYRING_SERVICE = "LayaGmailLabeler"
KEYRING_ACCOUNT = "gmail-oauth-token"


class GmailAPIError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        self.safe_code = safe_code
        super().__init__("Gmail API operation failed")


class GmailHistoryExpired(GmailAPIError):
    def __init__(self) -> None:
        super().__init__("history_expired")


class OAuthSetupError(RuntimeError):
    pass


class CredentialStoreAccessError(OAuthSetupError):
    pass


def _credential_backend() -> Any:
    try:
        return credential_backend()
    except CredentialStoreError as error:
        raise CredentialStoreAccessError(str(error)) from None


def _save_credentials(credentials: Any) -> None:
    backend = _credential_backend()
    serialized = credentials.to_json()
    try:
        backend.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, serialized)
        if backend.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) != serialized:
            raise CredentialStoreAccessError(
                "Could not verify the OAuth token in the secure operating-system credential store."
            )
    except CredentialStoreAccessError:
        raise
    except Exception:
        raise CredentialStoreAccessError(
            "Could not save the OAuth token in the secure operating-system credential store."
        ) from None


def _load_credentials() -> Any | None:
    backend = _credential_backend()
    try:
        serialized = backend.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        raise CredentialStoreAccessError(
            "Could not read the OAuth token from the secure operating-system credential store."
        ) from None
    if not serialized:
        return None

    try:
        from google.oauth2.credentials import Credentials

        credentials = Credentials.from_authorized_user_info(json.loads(serialized), [GMAIL_MODIFY_SCOPE])
    except Exception:
        raise OAuthSetupError("The saved OAuth token is invalid; run setup again.") from None

    scopes = set(credentials.scopes or [])
    if scopes and GMAIL_MODIFY_SCOPE not in scopes:
        raise OAuthSetupError("The saved OAuth token does not include the required Gmail permission; run setup again.")
    if credentials.expired and credentials.refresh_token:
        try:
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
            _save_credentials(credentials)
        except OAuthSetupError:
            raise
        except Exception:
            raise OAuthSetupError("Google authorization expired or was revoked; run setup again.") from None
    if not credentials.valid:
        raise OAuthSetupError("Google authorization is missing or expired; run setup again.")
    return credentials


def authorize_user(credentials_file: Path, interactive: bool = False) -> Any:
    """Load or refresh local authorization, opening a browser only during setup."""
    try:
        saved = _load_credentials()
    except CredentialStoreAccessError:
        raise
    except OAuthSetupError:
        if not interactive:
            raise
        saved = None
    if saved is not None and saved.refresh_token:
        return saved
    if not interactive:
        raise OAuthSetupError("Run the setup command to authorize Gmail before polling.")
    if not credentials_file.is_file():
        raise OAuthSetupError("Local OAuth client file is missing. Place credentials.json in the app data folder.")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), [GMAIL_MODIFY_SCOPE])
        # The dependency logs local callback paths at INFO, including the short-lived
        # authorization code. Keep that third-party logger disabled during the flow.
        oauth_logger = logging.getLogger("google_auth_oauthlib.flow")
        was_disabled = oauth_logger.disabled
        oauth_logger.disabled = True
        try:
            credentials = flow.run_local_server(
                host="localhost",
                port=0,
                open_browser=True,
                access_type="offline",
                prompt="consent",
                authorization_prompt_message="Open this URL in your browser to authorize local Gmail access: {url}",
                success_message="Authorization complete. You can close this browser tab.",
            )
        finally:
            oauth_logger.disabled = was_disabled
    except Exception:
        raise OAuthSetupError("Google OAuth did not complete. Check the local client file and try setup again.") from None
    if not credentials.refresh_token:
        raise OAuthSetupError("Google did not return a refresh token. Run setup again and approve offline access.")
    _save_credentials(credentials)
    return credentials


def build_gmail_client(credentials_file: Path, interactive: bool = False) -> "GmailClient":
    credentials = authorize_user(credentials_file, interactive=interactive)
    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    except Exception:
        raise OAuthSetupError("Could not initialize the Gmail API client.") from None
    return GmailClient(service)


class GmailClient:
    def __init__(self, service: Any) -> None:
        self._service = service

    @staticmethod
    def _execute(request: Any, *, history_request: bool = False) -> dict[str, Any]:
        from google.auth.exceptions import RefreshError
        from googleapiclient.errors import HttpError

        try:
            result = request.execute()
            return result if isinstance(result, dict) else {}
        except RefreshError:
            raise GmailAPIError("oauth_refresh_failed") from None
        except HttpError as error:
            status = int(getattr(getattr(error, "resp", None), "status", 0) or 0)
            if history_request and status == 404:
                raise GmailHistoryExpired() from None
            if status in {408, 429} or status >= 500:
                code = f"http_{status}" if status else "http_error"
            else:
                code = f"http_{status}" if status else "gmail_api_error"
            raise GmailAPIError(code) from None
        except (TimeoutError, OSError, ConnectionError):
            raise GmailAPIError("network_error") from None
        except Exception:
            raise GmailAPIError("gmail_api_error") from None

    def current_history_id(self) -> str:
        result = self._execute(
            self._service.users().getProfile(userId="me", fields="historyId")
        )
        value = result.get("historyId")
        if not value:
            raise GmailAPIError("missing_history_id")
        return str(value)

    def list_history_page(self, start_history_id: str, page_token: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "userId": "me",
            "startHistoryId": str(start_history_id),
            "historyTypes": ["messageAdded"],
            "maxResults": 500,
            "fields": "historyId,nextPageToken,history(id,messagesAdded(message(id)))",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return self._execute(
            self._service.users().history().list(**kwargs), history_request=True
        )

    def search_inbox_after(self, internal_date_ms: int) -> list[str]:
        """Search a day before the exact watermark; callers filter by internalDate."""
        timestamp = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)
        start_date = (timestamp - timedelta(days=1)).strftime("%Y/%m/%d")
        query = f"in:inbox after:{start_date}"
        found: list[str] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "q": query,
                "maxResults": 100,
                "fields": "messages(id),nextPageToken",
            }
            if page_token:
                kwargs["pageToken"] = page_token
            response = self._execute(self._service.users().messages().list(**kwargs))
            found.extend(str(message["id"]) for message in response.get("messages", []) if message.get("id"))
            page_token = response.get("nextPageToken")
            if not page_token:
                return found

    def message_metadata(self, message_id: str) -> dict[str, Any]:
        """Fetch labels and internal date only, before deciding whether to read a body."""
        return self._execute(
            self._service.users().messages().get(
                userId="me",
                id=message_id,
                format="metadata",
                fields="id,labelIds,internalDate",
            )
        )

    def message_for_classification(
        self,
        message_id: str,
        skip_label_ids: set[str] | None = None,
        minimum_internal_date_ms: int | None = None,
    ) -> dict[str, Any]:
        """Read minimal metadata first; fetch a body only for an eligible new Inbox message."""
        metadata = self._execute(
            self._service.users().messages().get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Content-Type"],
                fields="id,labelIds,internalDate,payload(headers(name,value))",
            )
        )
        labels = set(metadata.get("labelIds") or [])
        if "INBOX" not in labels or labels.intersection(skip_label_ids or set()):
            return metadata
        try:
            message_date = int(metadata.get("internalDate", 0))
        except (TypeError, ValueError):
            return metadata
        if minimum_internal_date_ms is not None and message_date <= minimum_internal_date_ms:
            return metadata

        full = self._execute(
            self._service.users().messages().get(
                userId="me",
                id=message_id,
                format="full",
                fields="id,labelIds,internalDate,payload(mimeType,filename,body,parts)",
            )
        )
        payload = full.get("payload")
        if isinstance(payload, dict):
            payload["headers"] = (metadata.get("payload") or {}).get("headers", [])
        return full
    def message_headers(self, message_id: str) -> dict[str, Any]:
        return self._execute(
            self._service.users().messages().get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject"],
                fields="id,payload(headers(name,value))",
            )
        )

    def user_labels(self) -> dict[str, str]:
        response = self._execute(
            self._service.users().labels().list(userId="me", fields="labels(id,name,type)")
        )
        return {
            str(label["name"]): str(label["id"])
            for label in response.get("labels", [])
            if label.get("id") and label.get("name") and label.get("type") == "user"
        }

    def ensure_user_labels(self, labels: dict[str, str]) -> dict[str, str]:
        """Create only approved user labels. Call only in explicit apply mode."""
        from .settings import LABELS
        if labels != LABELS:
            raise ValueError("Only the six approved IA labels may be created.")
        ids_by_name = self.user_labels()
        for category, name in labels.items():
            if name in ids_by_name:
                continue
            created = self._execute(
                self._service.users().labels().create(
                    userId="me",
                    body={
                        "name": name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
            )
            if not created.get("id"):
                raise GmailAPIError("label_create_failed")
            ids_by_name[name] = str(created["id"])
        return {category: ids_by_name[name] for category, name in labels.items()}

    def add_label(self, message_id: str, label_id: str) -> None:
        """Add one label only; no removal or other Gmail operation is exposed."""
        self._execute(
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            )
        )


def initialize_account(client: GmailClient, state: Any, labels: dict[str, str], apply_labels: bool) -> bool:
    """Record the activation boundary without enumerating the existing Inbox."""
    if state.history_id():
        if apply_labels:
            client.ensure_user_labels(labels)
        return False
    history_id = client.current_history_id()
    activated_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    if apply_labels:
        client.ensure_user_labels(labels)
    return state.initialize_activation(history_id, activated_at_ms)
