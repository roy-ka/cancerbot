"""Tests for source metadata tagging: evidence level derivation, publication
year coercion, publication-type normalisation, and the PubMed efetch parsing
used by scripts/backfill_source_metadata.py."""
import pytest

from src.routers.conversation_helper import (
    _coerce_pub_year,
    _derive_evidence_level,
    _normalise_pub_types,
    EXCLUDED_PUB_TYPES,
    EVIDENCE_LEVELS,
)


class TestDeriveEvidenceLevel:
    def test_meta_analysis_scores_highest(self):
        assert _derive_evidence_level(["Meta-Analysis"]) == 5
        assert _derive_evidence_level(["Systematic Review"]) == 5

    def test_rct_above_plain_review(self):
        assert _derive_evidence_level(["Randomized Controlled Trial"]) > _derive_evidence_level(["Review"])

    def test_case_report_below_journal_article(self):
        assert _derive_evidence_level(["Case Reports"]) < _derive_evidence_level(["Journal Article"])

    def test_takes_highest_of_multiple_types(self):
        # PubMed routinely tags one article with several types
        assert _derive_evidence_level(["Journal Article", "Meta-Analysis", "Review"]) == 5

    def test_case_insensitive(self):
        assert _derive_evidence_level(["mEtA-aNaLySiS"]) == 5

    def test_absent_or_empty_falls_back_to_default(self):
        default = _derive_evidence_level(None)
        assert _derive_evidence_level([]) == default
        assert _derive_evidence_level(["Journal Article"]) == default

    def test_unknown_type_does_not_sink_below_default(self):
        """An unrecognised type should never rank a source below an ordinary
        article — only explicitly weak types should."""
        default = _derive_evidence_level(None)
        assert _derive_evidence_level(["Some Future PubMed Type"]) == default

    def test_every_excluded_type_is_scored_zero(self):
        for pub_type in EXCLUDED_PUB_TYPES:
            assert EVIDENCE_LEVELS[pub_type] == 0


class TestNormalisePubTypes:
    def test_lowercases_and_dedupes(self):
        assert _normalise_pub_types(["Review", "review", "REVIEW"]) == ["review"]

    def test_strips_whitespace_and_drops_empties(self):
        assert _normalise_pub_types(["  Review  ", "", None]) == ["review"]

    def test_none_returns_empty_list(self):
        assert _normalise_pub_types(None) == []


class TestCoercePubYear:
    def test_parses_int_and_string(self):
        assert _coerce_pub_year(2021) == 2021
        assert _coerce_pub_year("2021") == 2021

    def test_parses_leading_year_of_longer_date(self):
        assert _coerce_pub_year("2019 Nov-Dec") == 2019

    def test_rejects_nonsense(self):
        assert _coerce_pub_year(None) is None
        assert _coerce_pub_year("") is None
        assert _coerce_pub_year("not a year") is None

    def test_rejects_out_of_range_years(self):
        assert _coerce_pub_year("0001") is None
        assert _coerce_pub_year("9999") is None


_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>A trial</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>67890</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><MedlineDate>2019 Nov-Dec</MedlineDate></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Only a MedlineDate</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Editorial</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


class TestParseEfetch:
    """_parse_efetch drives the backfill; it must survive the real shapes
    PubMed returns, including records that carry only a MedlineDate."""

    def _parse(self, xml):
        from scripts.backfill_source_metadata import _parse_efetch
        return _parse_efetch(xml)

    def test_extracts_year_and_pub_types(self):
        result = self._parse(_EFETCH_XML)
        assert result["12345"]["pub_year"] == 2021
        assert "randomized controlled trial" in result["12345"]["pub_types"]

    def test_falls_back_to_medline_date_for_year(self):
        result = self._parse(_EFETCH_XML)
        assert result["67890"]["pub_year"] == 2019

    def test_parses_all_articles_in_batch(self):
        assert set(self._parse(_EFETCH_XML)) == {"12345", "67890"}

    def test_malformed_xml_returns_empty_rather_than_raising(self):
        assert self._parse("<not-valid-xml") == {}

    def test_derived_level_matches_pub_types(self):
        result = self._parse(_EFETCH_XML)
        assert _derive_evidence_level(result["12345"]["pub_types"]) == 4   # RCT
        assert _derive_evidence_level(result["67890"]["pub_types"]) == 0   # Editorial


class TestCrossrefMetadataExtraction:
    @pytest.mark.asyncio
    async def test_requests_and_extracts_type_subject_and_year(self):
        import httpx
        from unittest.mock import AsyncMock, MagicMock
        from src.routers.conversation_helper import _search_crossref_sources

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "message": {
                "items": [{
                    "DOI": "10.1234/x",
                    "title": ["A study of glioblastoma treatment outcomes over time"],
                    "abstract": "An abstract long enough to survive the minimum word count filter "
                                "which requires at least twenty words of real content to be indexed.",
                    "URL": "https://doi.org/10.1234/x",
                    "type": "journal-article",
                    "subject": ["Oncology", "Cancer Research"],
                    "published": {"date-parts": [[2022, 5, 1]]},
                }]
            }
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = resp

        out = await _search_crossref_sources(client, ["glioblastoma"], max_results=4)

        # call_args_list[0] is the CrossRef query itself; later calls are the
        # Unpaywall open-access full-text supplement.
        _, kwargs = client.get.call_args_list[0]
        select = kwargs["params"]["select"]
        assert "type" in select and "subject" in select and "published" in select

        assert out[0]["year"] == 2022
        assert out[0]["pub_types"] == ["journal-article"]
        assert out[0]["subjects"] == ["Oncology", "Cancer Research"]

    @pytest.mark.asyncio
    async def test_missing_metadata_does_not_break_indexing(self):
        import httpx
        from unittest.mock import AsyncMock, MagicMock
        from src.routers.conversation_helper import _search_crossref_sources

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "message": {
                "items": [{
                    "DOI": "10.1234/y",
                    "title": ["Another glioblastoma paper with no metadata attached"],
                    "abstract": "An abstract long enough to survive the minimum word count filter "
                                "which requires at least twenty words of real content to be indexed.",
                    "URL": "https://doi.org/10.1234/y",
                }]
            }
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = resp

        out = await _search_crossref_sources(client, ["glioblastoma"], max_results=4)

        assert out[0]["year"] is None
        assert out[0]["pub_types"] is None
        assert out[0]["subjects"] is None


class TestIndexedDocumentTags:
    """_embed_and_index_sources must write the tag fields onto every chunk so
    search.py's boosts have something to match against."""

    def _index_one(self, source, entity_groups=None):
        from unittest.mock import patch, MagicMock
        from src.routers.conversation_helper import _embed_and_index_sources

        fake_db = MagicMock()
        fake_db.existing_base_source_ids.return_value = set()
        with patch("src.routers.conversation_helper.dbConnector", return_value=fake_db), \
             patch("src.routers.conversation_helper.OllamaConnector.embed_text", return_value=[0.1] * 768):
            _embed_and_index_sources([source], terms=["glioblastoma"], entity_groups=entity_groups)
        return [c.args[1] for c in fake_db.index_to_db.call_args_list]

    def _long_text(self):
        return " ".join(["glioblastoma"] * 40)

    def test_pubmed_metadata_written_to_every_chunk(self):
        docs = self._index_one({
            "source_type": "pubmed",
            "pmid": "12345",
            "title": "A trial",
            "content_for_embedding": self._long_text(),
            "year": "2021",
            "pub_types": ["Journal Article", "Randomized Controlled Trial"],
        })
        assert docs
        for doc in docs:
            assert doc["pub_year"] == 2021
            assert doc["evidence_level"] == 4
            assert "randomized controlled trial" in doc["pub_types"]

    def test_disease_areas_come_from_entity_groups(self):
        docs = self._index_one(
            {
                "source_type": "pubmed",
                "pmid": "999",
                "title": "GBM paper",
                "content_for_embedding": self._long_text(),
            },
            entity_groups=[
                {"term": "GBM", "category": "brain cancer"},
                {"term": "Mebendazole", "category": None},
            ],
        )
        assert docs
        for doc in docs:
            assert doc["disease_areas"] == ["brain cancer"]

    def test_source_without_metadata_still_indexes(self):
        """Wikipedia/URL sources have no pub metadata — they must still index,
        just with empty/default tag values rather than being dropped."""
        docs = self._index_one({
            "source_type": "wikipedia",
            "title": "Glioblastoma",
            "url": "https://en.wikipedia.org/wiki/Glioblastoma",
            "content_for_embedding": self._long_text(),
        })
        assert docs
        assert docs[0]["pub_year"] is None
        assert docs[0]["pub_types"] == []
        assert docs[0]["evidence_level"] == _derive_evidence_level(None)
