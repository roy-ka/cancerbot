from unittest.mock import MagicMock, patch

import pytest


class TestLoadCredentials:
    def test_returns_credentials_unrefreshed_when_not_expired(self, tmp_path):
        pytest.importorskip("googleapiclient", reason="requirements-backup.txt not installed")
        from scripts.backup_drive import _load_credentials

        token_file = tmp_path / "token.json"
        token_file.write_text("{}")

        mock_creds = MagicMock(expired=False)
        with patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ) as mock_from_file:
            creds = _load_credentials(str(token_file))

        assert creds is mock_creds
        mock_from_file.assert_called_once_with(str(token_file), ["https://www.googleapis.com/auth/drive.file"])
        mock_creds.refresh.assert_not_called()

    def test_refreshes_and_persists_expired_token(self, tmp_path):
        pytest.importorskip("googleapiclient", reason="requirements-backup.txt not installed")
        from scripts.backup_drive import _load_credentials

        token_file = tmp_path / "token.json"
        token_file.write_text("{}")

        mock_creds = MagicMock(expired=True, refresh_token="a-refresh-token")
        mock_creds.to_json.return_value = '{"refreshed": true}'
        with patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ), patch("google.auth.transport.requests.Request") as mock_request:
            _load_credentials(str(token_file))

        mock_creds.refresh.assert_called_once_with(mock_request.return_value)
        assert token_file.read_text() == '{"refreshed": true}'

    def test_does_not_refresh_when_expired_but_no_refresh_token(self, tmp_path):
        pytest.importorskip("googleapiclient", reason="requirements-backup.txt not installed")
        from scripts.backup_drive import _load_credentials

        token_file = tmp_path / "token.json"
        token_file.write_text("{}")

        mock_creds = MagicMock(expired=True, refresh_token=None)
        with patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ):
            _load_credentials(str(token_file))

        mock_creds.refresh.assert_not_called()


class TestUploadToDrive:
    def test_uploads_file_and_returns_id(self, tmp_path):
        pytest.importorskip("googleapiclient", reason="requirements-backup.txt not installed")
        from scripts.backup_drive import upload_to_drive

        local_file = tmp_path / "backup.jsonl.gz"
        local_file.write_bytes(b"fake data")

        mock_creds = MagicMock()
        mock_service = MagicMock()
        mock_service.files.return_value.create.return_value.execute.return_value = {"id": "drive-file-123"}

        with patch("scripts.backup_drive._load_credentials", return_value=mock_creds) as mock_load, \
             patch("googleapiclient.discovery.build", return_value=mock_service) as mock_build, \
             patch("googleapiclient.http.MediaFileUpload") as mock_media:
            file_id = upload_to_drive(local_file, "folder-abc", "/fake/token.json")

        assert file_id == "drive-file-123"
        mock_load.assert_called_once_with("/fake/token.json")
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)
        mock_media.assert_called_once_with(str(local_file), resumable=True)

        create_kwargs = mock_service.files.return_value.create.call_args.kwargs
        assert create_kwargs["body"] == {"name": "backup.jsonl.gz", "parents": ["folder-abc"]}
