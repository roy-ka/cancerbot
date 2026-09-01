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


def _get_or_create_subfolder(service, name: str, parent_id: str) -> str:
    """Find a child folder of parent_id named `name`, creating it if absent.

    The search only needs to see folders this app itself created (any
    earlier run's date folder), not arbitrary contents of parent_id — that
    stays within the drive.file scope even though parent_id itself was
    created by the user, not this app.
    """
    query = (
        f"name = '{name}' and '{parent_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    existing = results.get("files", [])
    if existing:
        return existing[0]["id"]

    folder_metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def upload_to_drive(local_path: Path, folder_id: str, token_file: str, subfolder: str | None = None) -> str:
    """Upload one file to a Drive folder. Returns the created file's Drive file ID.

    If `subfolder` is given (e.g. a date like "2026-09-01"), the file is
    placed in a child folder of that name under folder_id, creating it on
    first use and reusing it on later calls the same day.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _load_credentials(token_file)
    service = build("drive", "v3", credentials=creds)

    target_folder_id = folder_id
    if subfolder:
        target_folder_id = _get_or_create_subfolder(service, subfolder, folder_id)

    media = MediaFileUpload(str(local_path), resumable=True)
    file_metadata = {"name": local_path.name, "parents": [target_folder_id]}
    result = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return result["id"]
