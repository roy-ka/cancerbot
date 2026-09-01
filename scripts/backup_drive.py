"""Upload backup files to Google Drive via a service account.

Auth uses a service account (not OAuth) since backups run unattended from
cron — no browser, no refreshable user token to keep alive. The service
account's JSON key is referenced by path via GOOGLE_SERVICE_ACCOUNT_FILE,
never committed. Uploads target a folder (GOOGLE_DRIVE_BACKUP_FOLDER_ID)
that must be pre-shared with the service account's email as Editor.

The google-api-python-client/google-auth imports are deliberately inside
the function, not at module level, so importing this module (and anything
that imports backup_db.py/backup_opensearch.py, which import this
unconditionally) doesn't require those packages installed unless a caller
actually invokes upload_to_drive() — see requirements-backup.txt.
"""

from pathlib import Path


def upload_to_drive(local_path: Path, folder_id: str, service_account_file: str) -> str:
    """Upload one file to a Drive folder. Returns the created file's Drive file ID."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=creds)

    media = MediaFileUpload(str(local_path), resumable=True)
    file_metadata = {"name": local_path.name, "parents": [folder_id]}
    result = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return result["id"]
