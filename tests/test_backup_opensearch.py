import gzip
import json
from unittest.mock import MagicMock, patch

from scripts.backup_opensearch import backup_index, backup_opensearch, prune_backups
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
            results = backup_opensearch(tmp_path)

        assert list(results.keys()) == ["sources_v1"]
        mock_backup.assert_called_once()
        assert mock_backup.call_args[0][0] == "sources_v1"

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
    def test_keeps_only_the_last_n_runs(self, tmp_path):
        for ts in ["20260101_000000", "20260102_000000", "20260103_000000"]:
            (tmp_path / f"sources_v1_{ts}.mapping.json").write_text("{}")
            (tmp_path / f"sources_v1_{ts}.jsonl.gz").write_bytes(b"")
            (tmp_path / f"claims_v1_{ts}.mapping.json").write_text("{}")
            (tmp_path / f"claims_v1_{ts}.jsonl.gz").write_bytes(b"")

        prune_backups(tmp_path, keep_count=1)

        remaining = sorted(f.name for f in tmp_path.glob("*"))
        assert all("20260103_000000" in f for f in remaining)
        assert len(remaining) == 4

    def test_noop_when_fewer_runs_than_keep_count(self, tmp_path):
        (tmp_path / "sources_v1_20260101_000000.mapping.json").write_text("{}")

        prune_backups(tmp_path, keep_count=7)

        assert len(list(tmp_path.glob("*"))) == 1
