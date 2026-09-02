from unittest.mock import MagicMock, patch

from scripts.remove_duplicate_doi_sources import group_duplicates_by_doi, main


class TestGroupDuplicatesByDoi:
    def test_doi_with_single_base_id_is_omitted(self):
        assert group_duplicates_by_doi({"10.1/a": {"pmid:1"}}) == {}

    def test_pmid_kept_over_doi(self):
        result = group_duplicates_by_doi({"10.1/a": {"pmid:1", "doi:10.1/a"}})
        assert result == {"10.1/a": ("pmid:1", {"doi:10.1/a"})}

    def test_doi_kept_over_nct(self):
        result = group_duplicates_by_doi({"10.1/a": {"doi:10.1/a", "nct:NCT1"}})
        assert result == {"10.1/a": ("doi:10.1/a", {"nct:NCT1"})}

    def test_nct_kept_over_url(self):
        result = group_duplicates_by_doi({"10.1/a": {"nct:NCT1", "url:abc"}})
        assert result == {"10.1/a": ("nct:NCT1", {"url:abc"})}

    def test_three_way_duplicate_keeps_highest_priority(self):
        result = group_duplicates_by_doi({"10.1/a": {"url:abc", "pmid:1", "doi:10.1/a"}})
        assert result == {"10.1/a": ("pmid:1", {"doi:10.1/a", "url:abc"})}

    def test_multiple_dois_handled_independently(self):
        result = group_duplicates_by_doi({
            "10.1/a": {"pmid:1", "doi:10.1/a"},
            "10.1/b": {"pmid:2"},  # single base_id — not a duplicate
            "10.1/c": {"doi:10.1/c", "nct:NCT9"},
        })
        assert result == {
            "10.1/a": ("pmid:1", {"doi:10.1/a"}),
            "10.1/c": ("doi:10.1/c", {"nct:NCT9"}),
        }

    def test_same_prefix_tiebreak_is_deterministic(self):
        """Shouldn't normally happen (pmid values are unique per article),
        but the tie-break must not crash or be nondeterministic."""
        result = group_duplicates_by_doi({"10.1/a": {"pmid:2", "pmid:1"}})
        assert result == {"10.1/a": ("pmid:1", {"pmid:2"})}


def _scroll_hits(hits):
    def _fake_search(index, scroll=None, body=None):
        return {"_scroll_id": None, "hits": {"hits": hits}}
    return _fake_search


class TestMain:
    """End-to-end through main(): scroll -> group -> delete, with the
    OpenSearch client mocked."""

    def _setup_client(self, hits):
        mock_client = MagicMock()
        mock_client.search.side_effect = _scroll_hits(hits)
        return mock_client

    def test_dry_run_deletes_nothing(self, monkeypatch, caplog):
        hits = [
            {"_source": {"id": "pmid:1:c0", "source_id": "pmid:1", "doi": "10.1/a"}},
            {"_source": {"id": "doi:10.1/a:c0", "source_id": "doi:10.1/a", "doi": "10.1/a"}},
        ]
        mock_client = self._setup_client(hits)
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = mock_client
            mock_db._model = {"sources_index": "sources_v1"}
            with caplog.at_level("INFO"):
                main(limit=None, execute=False)
            mock_db.delete_chunks_by_source_id.assert_not_called()
            mock_db.delete_source_by_id.assert_not_called()
        assert "would keep pmid:1, delete doi:10.1/a" in caplog.text

    def test_execute_deletes_the_loser_via_chunked_deletion(self, monkeypatch):
        hits = [
            {"_source": {"id": "pmid:1:c0", "source_id": "pmid:1", "doi": "10.1/a"}},
            {"_source": {"id": "doi:10.1/a:c0", "source_id": "doi:10.1/a", "doi": "10.1/a"}},
        ]
        mock_client = self._setup_client(hits)
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = mock_client
            mock_db._model = {"sources_index": "sources_v1"}
            mock_db.delete_chunks_by_source_id.return_value = 3
            main(limit=None, execute=True)
            mock_db.delete_chunks_by_source_id.assert_called_once_with("doi:10.1/a")
            mock_db.delete_source_by_id.assert_not_called()

    def test_execute_deletes_legacy_doc_via_exact_id(self, monkeypatch):
        """A duplicate base_id with no source_id field (pre-chunked-schema
        doc) is deleted via delete_source_by_id, not delete_chunks_by_source_id."""
        hits = [
            {"_source": {"id": "pmid:1:c0", "source_id": "pmid:1", "doi": "10.1/a"}},
            {"_source": {"id": "doi:10.1/a", "doi": "10.1/a"}},  # no source_id — legacy
        ]
        mock_client = self._setup_client(hits)
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = mock_client
            mock_db._model = {"sources_index": "sources_v1"}
            mock_db.delete_source_by_id.return_value = 1
            main(limit=None, execute=True)
            mock_db.delete_source_by_id.assert_called_once_with("doi:10.1/a")
            mock_db.delete_chunks_by_source_id.assert_not_called()

    def test_no_duplicates_deletes_nothing(self, monkeypatch):
        hits = [
            {"_source": {"id": "pmid:1:c0", "source_id": "pmid:1", "doi": "10.1/a"}},
            {"_source": {"id": "pmid:2:c0", "source_id": "pmid:2", "doi": "10.1/b"}},
        ]
        mock_client = self._setup_client(hits)
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = mock_client
            mock_db._model = {"sources_index": "sources_v1"}
            main(limit=None, execute=True)
            mock_db.delete_chunks_by_source_id.assert_not_called()
            mock_db.delete_source_by_id.assert_not_called()

    def test_docs_without_doi_are_ignored(self, monkeypatch):
        hits = [
            {"_source": {"id": "pmid:1:c0", "source_id": "pmid:1", "doi": None}},
            {"_source": {"id": "pmid:2:c0", "source_id": "pmid:2"}},  # no doi key at all
        ]
        mock_client = self._setup_client(hits)
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = mock_client
            mock_db._model = {"sources_index": "sources_v1"}
            main(limit=None, execute=True)
            mock_db.delete_chunks_by_source_id.assert_not_called()

    def test_limit_caps_number_of_deletions(self, monkeypatch):
        hits = [
            {"_source": {"id": "pmid:1:c0", "source_id": "pmid:1", "doi": "10.1/a"}},
            {"_source": {"id": "doi:10.1/a:c0", "source_id": "doi:10.1/a", "doi": "10.1/a"}},
            {"_source": {"id": "pmid:2:c0", "source_id": "pmid:2", "doi": "10.1/b"}},
            {"_source": {"id": "doi:10.1/b:c0", "source_id": "doi:10.1/b", "doi": "10.1/b"}},
        ]
        mock_client = self._setup_client(hits)
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = mock_client
            mock_db._model = {"sources_index": "sources_v1"}
            mock_db.delete_chunks_by_source_id.return_value = 1
            main(limit=1, execute=True)
            mock_db.delete_chunks_by_source_id.assert_called_once()

    def test_aborts_when_opensearch_unavailable(self):
        with patch("scripts.remove_duplicate_doi_sources.dbConnector") as mock_db:
            mock_db.db_client = None
            try:
                main(limit=None, execute=False)
                assert False, "expected SystemExit"
            except SystemExit as e:
                assert e.code == 1
