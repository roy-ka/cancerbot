"""Tests for entity-group-aware search query construction.

Covers the fix for a heavily-synonymed entity (e.g. 5 GBM synonyms) drowning
out a single-term entity (e.g. one drug name) in PubMed/CrossRef/Wikipedia
search queries built from a flat extracted-terms list.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from src.routers.conversation_helper import (
    _merge_entity_groups,
    _representative_terms,
    _search_pubmed_sources,
    _search_crossref_sources,
    search_and_embed,
)


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# _merge_entity_groups
# ---------------------------------------------------------------------------

class TestMergeEntityGroups:
    def test_merges_synonyms_across_messages_case_insensitively(self):
        groups_per_message = [
            [{"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme"]}],
            [{"term": "gbm", "synonyms": ["glioblastoma", "high-grade glioma"]}],
        ]
        merged = _merge_entity_groups(groups_per_message)
        assert len(merged) == 1
        assert merged[0]["term"] == "GBM"
        assert set(merged[0]["synonyms"]) == {"glioblastoma", "glioblastoma multiforme", "high-grade glioma"}

    def test_keeps_distinct_entities_separate(self):
        groups_per_message = [
            [
                {"term": "Mebendazole", "synonyms": []},
                {"term": "GBM", "synonyms": ["glioblastoma"]},
            ]
        ]
        merged = _merge_entity_groups(groups_per_message)
        terms = {g["term"] for g in merged}
        assert terms == {"Mebendazole", "GBM"}

    def test_empty_input_returns_empty_list(self):
        assert _merge_entity_groups([]) == []
        assert _merge_entity_groups([[]]) == []


# ---------------------------------------------------------------------------
# _representative_terms
# ---------------------------------------------------------------------------

class TestRepresentativeTerms:
    def test_falls_back_to_flat_terms_when_no_groups(self):
        fallback = ["Mebendazole", "GBM", "glioblastoma"]
        assert _representative_terms([], fallback) == fallback
        assert _representative_terms(None, fallback) == fallback

    def test_returns_one_term_per_group_ignoring_synonyms(self):
        groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme", "grade IV glioma", "high-grade glioma"]},
        ]
        result = _representative_terms(groups, ["fallback"])
        assert result == ["Mebendazole", "GBM"]


# ---------------------------------------------------------------------------
# _search_pubmed_sources — AND-of-groups query with fallback
# ---------------------------------------------------------------------------

class TestPubmedEntityGroupQuery:
    @pytest.mark.asyncio
    async def test_uses_and_query_when_entity_groups_given(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        # AND-grouped query returns a hit — efetch returns no articles (empty XML) is fine,
        # we only assert on the esearch query string used.
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": ["123"]}}),
            _mock_response(200, text="<PubmedArticleSet></PubmedArticleSet>"),
        ]
        entity_groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme"]},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma", "glioblastoma multiforme"]
        await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        first_call_url = client.get.call_args_list[0].args[0]
        assert "AND" in first_call_url or "%20AND%20" in first_call_url

    @pytest.mark.asyncio
    async def test_falls_back_to_flat_or_query_when_and_query_returns_nothing(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": []}}),  # AND query — nothing
            _mock_response(200, json_data={"esearchresult": {"idlist": ["456"]}}),  # flat OR query — hit
            _mock_response(200, text="<PubmedArticleSet></PubmedArticleSet>"),  # efetch
        ]
        entity_groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma"]},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma"]
        await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        assert client.get.call_count == 3
        second_call_url = client.get.call_args_list[1].args[0]
        assert "AND" not in second_call_url and "%20AND%20" not in second_call_url

    @pytest.mark.asyncio
    async def test_and_query_includes_group_category_as_extra_alternative(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": ["123"]}}),
            _mock_response(200, text="<PubmedArticleSet></PubmedArticleSet>"),
        ]
        entity_groups = [
            {"term": "Mebendazole", "synonyms": [], "category": None},
            {"term": "GBM", "synonyms": ["glioblastoma"], "category": "brain cancer"},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma"]
        await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        first_call_url = client.get.call_args_list[0].args[0]
        assert "brain+cancer" in first_call_url or "brain%20cancer" in first_call_url

    @pytest.mark.asyncio
    async def test_and_query_skips_category_already_present_as_synonym(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": ["123"]}}),
            _mock_response(200, text="<PubmedArticleSet></PubmedArticleSet>"),
        ]
        entity_groups = [
            {"term": "Mebendazole", "synonyms": [], "category": None},
            {"term": "brain cancer", "synonyms": ["glioblastoma"], "category": "brain cancer"},
        ]
        terms = ["Mebendazole", "brain cancer", "glioblastoma"]
        await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        first_call_url = client.get.call_args_list[0].args[0]
        # "brain cancer" should appear exactly once in the group's OR-clause, not duplicated
        assert first_call_url.count("brain") == 1

    @pytest.mark.asyncio
    async def test_single_entity_group_skips_and_query(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            _mock_response(200, json_data={"esearchresult": {"idlist": []}}),
        ]
        entity_groups = [{"term": "GBM", "synonyms": ["glioblastoma"]}]
        terms = ["GBM", "glioblastoma"]
        result = await _search_pubmed_sources(client, terms, max_results=4, entity_groups=entity_groups)

        assert result == []
        assert client.get.call_count == 1  # only the flat query, no AND attempt


# ---------------------------------------------------------------------------
# _search_crossref_sources — representative-term query
# ---------------------------------------------------------------------------

class TestCrossrefEntityGroupQuery:
    @pytest.mark.asyncio
    async def test_query_uses_one_term_per_entity_not_all_synonyms(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(200, json_data={"message": {"items": []}})
        entity_groups = [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme", "grade IV glioma", "high-grade glioma"]},
        ]
        terms = ["Mebendazole", "GBM", "glioblastoma", "glioblastoma multiforme", "grade IV glioma", "high-grade glioma"]
        await _search_crossref_sources(client, terms, max_results=4, entity_groups=entity_groups)

        _, kwargs = client.get.call_args
        query = kwargs["params"]["query.bibliographic"]
        assert query == "Mebendazole GBM"


# ---------------------------------------------------------------------------
# search_and_embed — the current message must be freshly extracted even
# when conversations.py already cached a flat extracted_terms on it.
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content, extracted_terms=None, role="user"):
        self.content = content
        self.extracted_terms = extracted_terms
        self.role = role
        self.id = "msg-id"


class _FakeConversation:
    def __init__(self, messages):
        self.messages = messages
        self.id = "conv-id"


class TestSearchAndEmbedUsesFreshGroupsForCurrentMessage:
    @pytest.mark.asyncio
    async def test_current_message_extracted_fresh_despite_cached_flat_terms(self):
        # Simulates conversations.py having already saved a flat
        # extracted_terms cache on the current (last) message before
        # search_and_embed runs — this must NOT stop entity_groups from
        # being computed for it.
        current_msg = _FakeMessage(
            "can Mebendazole help against GBM?",
            extracted_terms=["Mebendazole", "GBM", "glioblastoma", "glioblastoma multiforme", "grade IV glioma"],
        )
        conversation = _FakeConversation([current_msg])

        async def fake_extract_term_groups(text):
            return (
                ["Mebendazole", "GBM", "glioblastoma"],
                [
                    {"term": "Mebendazole", "synonyms": []},
                    {"term": "GBM", "synonyms": ["glioblastoma"]},
                ],
            )

        with patch("src.routers.conversation_helper._extract_term_groups_from_message", side_effect=fake_extract_term_groups), \
             patch("src.routers.conversation_helper._extract_urls_from_texts", return_value=[]), \
             patch("src.routers.conversation_helper._search_pubmed_sources", new_callable=AsyncMock) as mock_pubmed, \
             patch("src.routers.conversation_helper._search_crossref_sources", new_callable=AsyncMock) as mock_crossref, \
             patch("src.routers.conversation_helper._search_wikipedia_sources", new_callable=AsyncMock) as mock_wiki, \
             patch("src.routers.conversation_helper._embed_and_index_sources", return_value=(0, 0)):
            mock_pubmed.return_value = []
            mock_crossref.return_value = []
            mock_wiki.return_value = []

            await search_and_embed(conversation)

        _, pubmed_kwargs = mock_pubmed.call_args
        assert pubmed_kwargs["entity_groups"] == [
            {"term": "Mebendazole", "synonyms": []},
            {"term": "GBM", "synonyms": ["glioblastoma"]},
        ]


# ---------------------------------------------------------------------------
# search_and_embed — a context-dependent follow-up ("what can block these
# pathways?") must be rewritten against recent history before NLP extraction
# runs, or extraction has nothing to find and retrieval comes back empty.
# ---------------------------------------------------------------------------

class TestSearchAndEmbedRewritesFollowUpQuery:
    @pytest.mark.asyncio
    async def test_extraction_runs_on_rewritten_text_not_raw_message(self):
        conversation = _FakeConversation([
            _FakeMessage("what are the Glioma pathways", role="user"),
            _FakeMessage(
                "Glioma communicates via Notch, JAK/STAT3, and PI3K/AKT signaling...",
                role="assistant",
            ),
            _FakeMessage("what can block these pathways?", role="user"),
        ])

        rewritten = "What can block Notch, JAK/STAT3, and PI3K/AKT signaling in glioma?"

        async def fake_extract_term_groups(text):
            assert text == rewritten, f"NLP extraction ran on {text!r}, expected the rewritten query"
            return (["Notch", "JAK/STAT3", "PI3K/AKT"], [{"term": "Notch", "synonyms": []}])

        with patch(
            "src.classes.ollama_connector.OllamaConnector.rewrite_query_with_history",
            new_callable=AsyncMock,
        ) as mock_rewrite, \
             patch("src.routers.conversation_helper._extract_term_groups_from_message", side_effect=fake_extract_term_groups), \
             patch("src.routers.conversation_helper._extract_urls_from_texts", return_value=[]), \
             patch("src.routers.conversation_helper._search_pubmed_sources", new_callable=AsyncMock) as mock_pubmed, \
             patch("src.routers.conversation_helper._search_crossref_sources", new_callable=AsyncMock) as mock_crossref, \
             patch("src.routers.conversation_helper._search_wikipedia_sources", new_callable=AsyncMock) as mock_wiki, \
             patch("src.routers.conversation_helper._embed_and_index_sources", return_value=(0, 0)):
            mock_rewrite.return_value = rewritten
            mock_pubmed.return_value = []
            mock_crossref.return_value = []
            mock_wiki.return_value = []

            result = await search_and_embed(conversation)

        # The two prior messages (user question + assistant answer), in order,
        # are what the rewrite is grounded on.
        history_arg, text_arg = mock_rewrite.call_args[0]
        assert text_arg == "what can block these pathways?"
        assert history_arg == [
            ("user", "what are the Glioma pathways"),
            ("assistant", "Glioma communicates via Notch, JAK/STAT3, and PI3K/AKT signaling..."),
        ]

        assert result["rewritten_query"] == rewritten

    @pytest.mark.asyncio
    async def test_first_message_in_conversation_skips_rewrite(self):
        """No history yet — nothing to resolve against, and no Groq call to pay for."""
        conversation = _FakeConversation([_FakeMessage("what are the Glioma pathways", role="user")])

        async def fake_extract_term_groups(text):
            return (["Glioma"], [{"term": "Glioma", "synonyms": []}])

        with patch(
            "src.classes.ollama_connector.OllamaConnector.rewrite_query_with_history",
            new_callable=AsyncMock,
        ) as mock_rewrite, \
             patch("src.routers.conversation_helper._extract_term_groups_from_message", side_effect=fake_extract_term_groups), \
             patch("src.routers.conversation_helper._extract_urls_from_texts", return_value=[]), \
             patch("src.routers.conversation_helper._search_pubmed_sources", new_callable=AsyncMock) as mock_pubmed, \
             patch("src.routers.conversation_helper._search_crossref_sources", new_callable=AsyncMock) as mock_crossref, \
             patch("src.routers.conversation_helper._search_wikipedia_sources", new_callable=AsyncMock) as mock_wiki, \
             patch("src.routers.conversation_helper._embed_and_index_sources", return_value=(0, 0)):
            mock_pubmed.return_value = []
            mock_crossref.return_value = []
            mock_wiki.return_value = []

            result = await search_and_embed(conversation)

        mock_rewrite.assert_not_called()
        assert result["rewritten_query"] == "what are the Glioma pathways"


# ---------------------------------------------------------------------------
# search_and_embed — latest_text_override replaces the newest message's text
# for search (the general half of a mixed personal + general question).
# ---------------------------------------------------------------------------

class TestSearchAndEmbedLatestTextOverride:
    @pytest.mark.asyncio
    async def test_extraction_runs_on_override_not_saved_message(self):
        conversation = _FakeConversation([
            _FakeMessage("What stage am I, and what is the Warburg effect?", role="user"),
        ])
        seen = []

        async def fake_extract_term_groups(text):
            seen.append(text)
            return (["Warburg effect"], [{"term": "Warburg effect", "synonyms": []}])

        with patch("src.routers.conversation_helper._extract_term_groups_from_message", side_effect=fake_extract_term_groups), \
             patch("src.routers.conversation_helper._extract_urls_from_texts", return_value=[]), \
             patch("src.routers.conversation_helper._search_pubmed_sources", new_callable=AsyncMock, return_value=[]), \
             patch("src.routers.conversation_helper._search_crossref_sources", new_callable=AsyncMock, return_value=[]), \
             patch("src.routers.conversation_helper._search_wikipedia_sources", new_callable=AsyncMock, return_value=[]), \
             patch("src.routers.conversation_helper._embed_and_index_sources", return_value=(0, 0)):
            await search_and_embed(conversation, latest_text_override="What is the Warburg effect?")

        assert seen == ["What is the Warburg effect?"]
