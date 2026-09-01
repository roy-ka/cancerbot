"""Upload backup files to Google Drive under your own account via OAuth.

A bare service account has no Drive storage quota of its own on a personal
(non-Workspace) Google account — uploads fail with storageQuotaExceeded
even into a folder shared from your Drive. OAuth as your own account is
the workaround: uploads count against your normal Drive quota. The
one-time interactive browser consent happens locally via
scripts/generate_google_drive_token.py (run once on a machine with a
browser, not on the server); the resulting token file is then referenced
by GOOGLE_OAUTH_TOKEN_FILE and auto-refreshed here on every run, with the
refreshed token persisted back to the same file so cron never needs a
browser.

The google-auth imports are deliberately inside the function, not at
module level — see requirements-backup.txt.
"""

from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _load_credentials(token_file: str):
    """Load OAuth credentials from token_file, refreshing (and persisting
    the refreshed token) if the access token has expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(token_file).write_text(creds.to_json())
    return creds


def upload_to_drive(local_path: Path, folder_id: str, token_file: str) -> str:
    """Upload one file to a Drive folder. Returns the created file's Drive file ID."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _load_credentials(token_file)
    service = build("drive", "v3", credentials=creds)

    media = MediaFileUpload(str(local_path), resumable=True)
    file_metadata = {"name": local_path.name, "parents": [folder_id]}
    result = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return result["id"]
