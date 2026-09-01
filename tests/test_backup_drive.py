from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestUploadToDrive:
    def test_uploads_file_and_returns_id(self, tmp_path):
        pytest.importorskip("googleapiclient", reason="requirements-backup.txt not installed")
        from scripts.backup_drive import upload_to_drive

        local_file = tmp_path / "backup.jsonl.gz"
        local_file.write_bytes(b"fake data")

        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_service.files.return_value.create.return_value.execute.return_value = {"id": "drive-file-123"}

        with patch("google.oauth2.service_account.Credentials.from_service_account_file", return_value=mock_creds) as mock_from_file, \
             patch("googleapiclient.discovery.build", return_value=mock_service) as mock_build, \
             patch("googleapiclient.http.MediaFileUpload") as mock_media:
            file_id = upload_to_drive(local_file, "folder-abc", "/fake/service-account.json")

        assert file_id == "drive-file-123"
        mock_from_file.assert_called_once_with(
            "/fake/service-account.json",
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)
        mock_media.assert_called_once_with(str(local_file), resumable=True)

        create_kwargs = mock_service.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"] == {"name": "backup.jsonl.gz", "parents": ["folder-abc"]}
