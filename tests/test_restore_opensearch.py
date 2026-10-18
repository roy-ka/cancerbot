import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.restore_opensearch import (
    clean_settings,
    find_backups,
    restore_index,
    restore_opensearch,
)
from src.retrieval.db_connector import dbConnector

SOURCES = "v1.5_en_nomic-embed-text_index"
CLAIMS = "v1.5_claims_nomic-embed-text_index"

# What client.indices.get() returns for an index on the old two-node
# cluster, as backup_opensearch.py saved it.
BACKED_UP_SETTINGS = {
    "index": {
        "number_of_shards": "2",
        "number_of_replicas": "1",
        "knn": "true",
        "uuid": "abc123",
        "creation_date": "1760000000000",
        "provided_name": SOURCES,
        "version": {"created": "136407827"},
        "replication": {"type": "DOCUMENT"},
    }
}


def _write_backup(directory, index, time, docs):
    directory.mkdir(parents=True, exist_ok=True)
    mapping = directory / f"{index}_{time}.mapping.json"
    mapping.write_text(json.dumps({
        "mappings": {"properties": {"title": {"type": "text"}}},
        "settings": BACKED_UP_SETTINGS,
    }))
    with gzip.open(directory / f"{index}_{time}.jsonl.gz", "wt") as f:
        for doc in docs:
            f.write(json.dumps(doc) + "\n")
    return mapping, directory / f"{index}_{time}.jsonl.gz"


def _reset():
    dbConnector._initialized = False
    dbConnector.db_client = None
    dbConnector._model = None


class TestCleanSettings:
    def test_drops_read_only_fields(self):
        cleaned = clean_settings(BACKED_UP_SETTINGS)["index"]
        for key in ("uuid", "creation_date", "provided_name", "version"):
            assert key not in cleaned

    def test_keeps_real_settings(self):
        cleaned = clean_settings(BACKED_UP_SETTINGS)["index"]
        assert cleaned["number_of_shards"] == "2"
        assert cleaned["knn"] == "true"
        assert cleaned["replication"] == {"type": "DOCUMENT"}

    def test_forces_zero_replicas_for_the_single_node(self):
        assert clean_settings(BACKED_UP_SETTINGS)["index"]["number_of_replicas"] == "0"

    def test_handles_missing_settings(self):
        assert clean_settings({}) == {"index": {"number_of_replicas": "0"}}


class TestFindBackups:
    def test_finds_both_indices(self, tmp_path):
        _write_backup(tmp_path, SOURCES, "120000", [])
        _write_backup(tmp_path, CLAIMS, "120000", [])
        found = find_backups(tmp_path, [SOURCES, CLAIMS])
        assert set(found) == {SOURCES, CLAIMS}
        assert found[SOURCES][1].name == f"{SOURCES}_120000.jsonl.gz"

    def test_picks_the_latest_run_of_the_day(self, tmp_path):
        _write_backup(tmp_path, SOURCES, "030000", [])
        _write_backup(tmp_path, SOURCES, "150000", [])
        found = find_backups(tmp_path, [SOURCES])
        assert found[SOURCES][0].name == f"{SOURCES}_150000.mapping.json"

    def test_ignores_indices_the_app_does_not_use(self, tmp_path):
        _write_backup(tmp_path, "old_index_v0", "120000", [])
        assert find_backups(tmp_path, [SOURCES, CLAIMS]) == {}

    def test_skips_a_mapping_without_its_documents(self, tmp_path):
        mapping, docs = _write_backup(tmp_path, SOURCES, "120000", [])
        docs.unlink()
        assert find_backups(tmp_path, [SOURCES]) == {}


def _client(existing_count=None):
    client = MagicMock()
    client.indices.exists.return_value = existing_count is not None
    client.count.return_value = {"count": existing_count or 0}
    return client


class TestRestoreIndex:
    DOCS = [
        {"_id": "pmid:1:c0", "_source": {"title": "A"}},
        {"_id": "pmid:2:c0", "_source": {"title": "B"}},
    ]

    def _bulk(self):
        captured = {}

        def fake_bulk(client, actions, **kwargs):
            captured["actions"] = list(actions)
            captured["kwargs"] = kwargs
            return len(captured["actions"]), []

        return captured, fake_bulk

    def test_creates_the_index_with_clean_settings_and_loads_docs_with_their_ids(self, tmp_path):
        mapping, docs = _write_backup(tmp_path, SOURCES, "120000", self.DOCS)
        client = _client()
        client.count.return_value = {"count": 2}
        captured, fake_bulk = self._bulk()

        with patch("opensearchpy.helpers.bulk", fake_bulk):
            result = restore_index(client, SOURCES, mapping, docs, replace=False)

        body = client.indices.create.call_args.kwargs["body"]
        assert body["settings"]["index"]["number_of_replicas"] == "0"
        assert "uuid" not in body["settings"]["index"]
        assert body["mappings"] == {"properties": {"title": {"type": "text"}}}
        # Original ids, so a second run overwrites rather than duplicates.
        assert [a["_id"] for a in captured["actions"]] == ["pmid:1:c0", "pmid:2:c0"]
        assert all(a["_index"] == SOURCES for a in captured["actions"])
        client.indices.refresh.assert_called_once_with(index=SOURCES)
        assert result == {"loaded": 2, "errors": [], "count": 2}

    def test_refuses_to_overwrite_an_index_with_documents(self, tmp_path):
        mapping, docs = _write_backup(tmp_path, SOURCES, "120000", self.DOCS)
        client = _client(existing_count=40)

        with pytest.raises(RuntimeError, match="--replace"):
            restore_index(client, SOURCES, mapping, docs, replace=False)
        client.indices.delete.assert_not_called()
        client.indices.create.assert_not_called()

    def test_replace_deletes_an_index_with_documents(self, tmp_path):
        mapping, docs = _write_backup(tmp_path, SOURCES, "120000", self.DOCS)
        client = _client(existing_count=40)
        _, fake_bulk = self._bulk()

        with patch("opensearchpy.helpers.bulk", fake_bulk):
            restore_index(client, SOURCES, mapping, docs, replace=True)
        client.indices.delete.assert_called_once_with(index=SOURCES)
        client.indices.create.assert_called_once()

    def test_an_empty_existing_index_is_recreated_without_replace(self, tmp_path):
        """The backend creates empty indices on startup; the restore must
        not need --replace for those."""
        mapping, docs = _write_backup(tmp_path, SOURCES, "120000", self.DOCS)
        client = _client(existing_count=0)
        _, fake_bulk = self._bulk()

        with patch("opensearchpy.helpers.bulk", fake_bulk):
            restore_index(client, SOURCES, mapping, docs, replace=False)
        client.indices.delete.assert_called_once_with(index=SOURCES)

    def test_failed_documents_are_reported(self, tmp_path):
        mapping, docs = _write_backup(tmp_path, SOURCES, "120000", self.DOCS)
        client = _client()

        with patch("opensearchpy.helpers.bulk", return_value=(1, [{"index": {"_id": "pmid:2:c0", "error": "bad"}}])):
            result = restore_index(client, SOURCES, mapping, docs, replace=False)
        assert result["loaded"] == 1
        assert len(result["errors"]) == 1


class TestRestoreOpensearch:
    def setup_method(self):
        _reset()
        dbConnector._initialized = True
        dbConnector._model = {"sources_index": SOURCES, "claims_index": CLAIMS}
        dbConnector.db_client = _client()

    def teardown_method(self):
        _reset()

    def test_dry_run_counts_documents_and_writes_nothing(self, tmp_path):
        _write_backup(tmp_path, SOURCES, "120000", TestRestoreIndex.DOCS)
        with patch("scripts.restore_opensearch.restore_index") as restore:
            results = restore_opensearch(tmp_path, dry_run=True)
        restore.assert_not_called()
        dbConnector.db_client.indices.create.assert_not_called()
        assert results == {SOURCES: {"docs": 2}}

    def test_restores_each_index_found(self, tmp_path):
        _write_backup(tmp_path, SOURCES, "120000", [])
        _write_backup(tmp_path, CLAIMS, "120000", [])
        with patch(
            "scripts.restore_opensearch.restore_index",
            return_value={"loaded": 0, "errors": [], "count": 0},
        ) as restore:
            results = restore_opensearch(tmp_path, replace=True)
        assert set(results) == {SOURCES, CLAIMS}
        assert all(call.kwargs["replace"] is True for call in restore.call_args_list)

    def test_errors_when_the_directory_has_no_backups(self, tmp_path):
        with pytest.raises(RuntimeError, match="no backups"):
            restore_opensearch(tmp_path)

    def test_errors_when_the_directory_does_not_exist(self, tmp_path):
        with pytest.raises(RuntimeError, match="not a directory"):
            restore_opensearch(tmp_path / "missing")

    def test_errors_when_opensearch_is_not_configured(self, tmp_path, monkeypatch):
        _reset()
        monkeypatch.setattr(dbConnector, "_initialize", classmethod(lambda cls: None))
        with pytest.raises(RuntimeError, match="not configured"):
            restore_opensearch(tmp_path)
