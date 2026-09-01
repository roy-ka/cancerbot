import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from scripts.backup_opensearch import backup_index, backup_opensearch, backup_to_drive, prune_backups
from src.retrieval.db_connector import dbConnector


def _reset():
    dbConnector._initialized = False
    dbConnector.db_client = None
    dbConnector._model = None


class TestBackupIndex:
    def teardown_method(self):
        _reset()

    def test_writes_mapping_and_gzipped_docs(self, tmp_path, monkeypatch):
        _reset()
        dbConnector._initialized = True
        mock_client = MagicMock()
        mock_client.indices.get.return_value = {
            "my_index": {"mappings": {"properties": {"title": {"type": "text"}}}, "settings": {"index": {}}}
        }
        dbConnector.db_client = mock_client

        fake_hits = [
            {"_id": "doc1", "_source": {"title": "A"}},
            {"_id": "doc2", "_source": {"title": "B"}},
        ]
        with patch("opensearchpy.helpers.scan", return_value=iter(fake_hits)):
            result = backup_index("my_index", tmp_path, "20260101_000000")

        assert result["docs"] == 2
        mapping = json.loads(result["mapping_path"].read_text())
        assert mapping["mappings"]["properties"]["title"]["type"] == "text"

        with gzip.open(result["docs_path"], "rt") as f:
            lines = [json.loads(line) for line in f]
        assert lines == fake_hits

    def test_raises_when_client_not_initialized(self, tmp_path, monkeypatch):
        _reset()
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        dbConnector.db_client = None

        try:
            backup_index("my_index", tmp_path, "20260101_000000")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "not initialized" in str(e)


class TestBackupOpensearch:
    def teardown_method(self):
        _reset()

    def test_skips_missing_indices_and_backs_up_existing(self, tmp_path, monkeypatch):
        _reset()
        dbConnector._initialized = True
        dbConnector._model = {"sources_index": "sources_v1", "claims_index": "claims_v1"}
        mock_client = MagicMock()
        mock_client.indices.exists.side_effect = lambda index: index == "sources_v1"
        dbConnector.db_client = mock_client

        with patch(
            "scripts.backup_opensearch.backup_index",
            return_value={"docs": 3, "mapping_path": tmp_path / "m.json", "docs_path": tmp_path / "d.jsonl.gz"},
        ) as mock_backup:
            (tmp_path / "d.jsonl.gz").write_bytes(b"")
            results = backup_opensearch(tmp_path, date_str="2026-09-01")

        assert list(results.keys()) == ["sources_v1"]
        mock_backup.assert_called_once()
        assert mock_backup.call_args[0][0] == "sources_v1"
        assert mock_backup.call_args[0][1] == tmp_path / "2026-09-01"

    def test_raises_when_no_model_configured(self, tmp_path, monkeypatch):
        _reset()
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        dbConnector._model = None

        try:
            backup_opensearch(tmp_path)
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "not configured" in str(e)


class TestPruneBackups:
    def test_keeps_only_the_last_n_dates(self, tmp_path):
        for date in ["2026-08-30", "2026-08-31", "2026-09-01"]:
            date_dir = tmp_path / date
            date_dir.mkdir()
            (date_dir / "sources_v1_120000.mapping.json").write_text("{}")
            (date_dir / "sources_v1_120000.jsonl.gz").write_bytes(b"")
            (date_dir / "claims_v1_120000.mapping.json").write_text("{}")
            (date_dir / "claims_v1_120000.jsonl.gz").write_bytes(b"")

        prune_backups(tmp_path, keep_count=1)

        remaining = sorted(d.name for d in tmp_path.iterdir())
        assert remaining == ["2026-09-01"]
        assert len(list((tmp_path / "2026-09-01").iterdir())) == 4

    def test_noop_when_fewer_dates_than_keep_count(self, tmp_path):
        date_dir = tmp_path / "2026-09-01"
        date_dir.mkdir()
        (date_dir / "sources_v1_120000.mapping.json").write_text("{}")

        prune_backups(tmp_path, keep_count=7)

        assert (tmp_path / "2026-09-01").exists()


class TestBackupToDrive:
    def test_exits_when_not_configured(self, monkeypatch, capsys):
        monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_FILE", raising=False)
        monkeypatch.delenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", raising=False)

        try:
            backup_to_drive({}, "2026-09-01")
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert e.code == 1
        assert "not set" in capsys.readouterr().out

    def test_uploads_every_file_from_every_index_result(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", "/fake/sa.json")
        monkeypatch.setenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", "folder-abc")

        results = {
            "sources_v1": {"docs": 3, "mapping_path": Path("m1.json"), "docs_path": Path("d1.jsonl.gz")},
            "claims_v1": {"docs": 1, "mapping_path": Path("m2.json"), "docs_path": Path("d2.jsonl.gz")},
        }
        mock_upload = Mock(return_value="file-id")
        with patch("scripts.backup_drive.upload_to_drive", mock_upload):
            backup_to_drive(results, "2026-09-01")

        assert mock_upload.call_count == 4
        uploaded_paths = {call.args[0] for call in mock_upload.call_args_list}
        assert uploaded_paths == {Path("m1.json"), Path("d1.jsonl.gz"), Path("m2.json"), Path("d2.jsonl.gz")}
        for call in mock_upload.call_args_list:
            assert call.kwargs["subfolder"] == "2026-09-01"
