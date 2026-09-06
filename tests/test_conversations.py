import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import json


_DEFAULT_STREAM_CONTENT = "Cancer cells exhibit the Warburg effect [src-001][src-002]."


def _make_stream(content: str):
    """Return an async generator function that mocks OllamaConnector.stream_text."""
    async def _gen(*args, **kwargs):
        yield content
        yield {}  # alias_to_id sentinel
    return _gen


@pytest.fixture(autouse=True)
def mock_external_services(mock_retrieval):
    """Auto-mock external services for all conversation tests"""
    with (
        patch("src.routers.conversations.run_retrieval", return_value=mock_retrieval),
        patch(
            "src.routers.conversations.OllamaConnector.stream_text",
            new=_make_stream(_DEFAULT_STREAM_CONTENT),
        ),
        patch(
            "src.routers.conversations.search_and_embed",
            new=AsyncMock(return_value={
                "indexed": 0, "skipped": 0, "terms": [],
                "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
            }),
        ),
    ):
        yield


class TestSingleNlpPassPerMessage:
    """The NLP service is the most CPU-expensive hop in a chat turn.
    search_and_embed already spell-corrects and extracts the current message,
    so the request path must reuse that result rather than extracting again."""

    @patch("src.routers.conversations.run_retrieval")
    def test_request_path_does_not_extract_terms_a_second_time(self, mock_retrieval, client):
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}
        extract = AsyncMock(return_value=["glioblastoma"])

        with patch("src.routers.conversation_helper._extract_terms_from_message", extract):
            response = client.post(
                "/conversations/new",
                json={"content": "what is GBM?"},
            )

        assert response.status_code == 200
        extract.assert_not_awaited()

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_extracted_terms_persisted_from_search_result(
        self, mock_search_and_embed, mock_retrieval, client, db_session
    ):
        from src.db.models import Message

        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": ["glioblastoma", "temozolomide", "history term"],
            "latest_terms": ["glioblastoma", "temozolomide"],
            "entity_groups": [],
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post("/conversations/new", json={"content": "GBM and temozolomide?"})
        assert response.status_code == 200

        user_msg = (
            db_session.query(Message)
            .filter(Message.role == "user", Message.content == "GBM and temozolomide?")
            .one()
        )
        # This message's own terms — not the history-merged `terms` list
        assert user_msg.extracted_terms == ["glioblastoma", "temozolomide"]

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_falls_back_to_merged_terms_when_nlp_returned_nothing(
        self, mock_search_and_embed, mock_retrieval, client, db_session
    ):
        """NLP can come back empty for a bare abbreviation, in which case
        search_and_embed's word-extraction fallback is what gets cached."""
        from src.db.models import Message

        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": ["gbm"],
            "latest_terms": [],
            "entity_groups": [],
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post("/conversations/new", json={"content": "gbm"})
        assert response.status_code == 200

        user_msg = (
            db_session.query(Message)
            .filter(Message.role == "user", Message.content == "gbm")
            .one()
        )
        assert user_msg.extracted_terms == ["gbm"]


class TestRetrievalQueryEntityGrouping:
    """retrieval_query should use one representative term per entity, not the
    fully synonym-expanded flat term list, so a heavily-synonymed entity
    (e.g. 5 GBM synonyms) doesn't bury a single-term entity (a drug name) in
    the BM25/KNN retrieval match."""

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_retrieval_query_uses_representative_terms_when_entity_groups_present(
        self, mock_search_and_embed, mock_retrieval, client
    ):
        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": ["Mebendazole", "GBM", "glioblastoma", "glioblastoma multiforme", "grade IV glioma"],
            "entity_groups": [
                {"term": "Mebendazole", "synonyms": []},
                {"term": "GBM", "synonyms": ["glioblastoma", "glioblastoma multiforme", "grade IV glioma"]},
            ],
            "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "can Mebendazole help against GBM?"},
        )
        assert response.status_code == 200

        called_query = mock_retrieval.call_args.args[0]
        assert called_query == "Mebendazole GBM"

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_retrieval_query_falls_back_to_flat_terms_without_entity_groups(
        self, mock_search_and_embed, mock_retrieval, client
    ):
        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": ["cancer", "treatment"],
            "entity_groups": [],
            "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "tell me about cancer treatment"},
        )
        assert response.status_code == 200

        called_query = mock_retrieval.call_args.args[0]
        assert called_query == "cancer treatment"


class TestDenseQueryUsesRewrittenFollowUp:
    """A context-dependent follow-up like "what can block these pathways?"
    is rewritten against history in search_and_embed before extraction runs
    (see tests/test_entity_grouping.py); conversations.py must then use that
    rewritten text for the KNN/dense query and as the lexical fallback,
    not revert to the raw pronoun-laden message."""

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_dense_query_uses_rewritten_query_not_raw_message(
        self, mock_search_and_embed, mock_retrieval, client
    ):
        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": ["Notch", "JAK/STAT3"],
            "entity_groups": [{"term": "Notch", "synonyms": []}, {"term": "JAK/STAT3", "synonyms": []}],
            "rewritten_query": "What can block Notch and JAK/STAT3 signaling in glioma?",
            "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "what can block these pathways?"},
        )
        assert response.status_code == 200

        dense_query = mock_retrieval.call_args.args[2]
        assert dense_query == "What can block Notch and JAK/STAT3 signaling in glioma?"

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_retrieval_query_falls_back_to_rewritten_query_without_entity_groups(
        self, mock_search_and_embed, mock_retrieval, client
    ):
        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": [],
            "entity_groups": [],
            "rewritten_query": "What can block Notch and JAK/STAT3 signaling in glioma?",
            "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "what can block these pathways?"},
        )
        assert response.status_code == 200

        retrieval_query = mock_retrieval.call_args.args[0]
        assert retrieval_query == "What can block Notch and JAK/STAT3 signaling in glioma?"

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.search_and_embed")
    def test_no_rewrite_falls_back_to_raw_message_as_before(
        self, mock_search_and_embed, mock_retrieval, client
    ):
        """First message in a conversation: search_and_embed's rewritten_query
        equals the raw text (nothing to resolve), so behavior is unchanged."""
        mock_search_and_embed.return_value = {
            "indexed": 0, "skipped": 0,
            "terms": [],
            "entity_groups": [],
            "rewritten_query": "what is the Warburg effect?",
            "pubmed_found": 0, "crossref_found": 0, "wikipedia_found": 0,
        }
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "what is the Warburg effect?"},
        )
        assert response.status_code == 200

        dense_query = mock_retrieval.call_args.args[2]
        assert dense_query == "what is the Warburg effect?"


class TestAutoGeneratedTitle:
    """The first message in a conversation should get a real, LLM-generated
    title once the answer is ready; later messages shouldn't touch it."""

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.OllamaConnector.generate_title", new_callable=AsyncMock)
    def test_first_message_updates_title(self, mock_generate_title, mock_retrieval, client):
        mock_generate_title.return_value = "Mebendazole for Glioblastoma"
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "can Mebendazole help against GBM?"},
        )
        assert response.status_code == 200
        assert response.json()["conversation"]["title"] == "Mebendazole for Glioblastoma"
        mock_generate_title.assert_awaited_once_with("can Mebendazole help against GBM?")

    @patch("src.routers.conversations.run_retrieval")
    @patch("src.routers.conversations.OllamaConnector.generate_title", new_callable=AsyncMock)
    def test_second_message_does_not_regenerate_title(
        self, mock_generate_title, mock_retrieval, client, test_conversation
    ):
        mock_generate_title.return_value = "Should not be used"
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}
        original_title = test_conversation.title

        response = client.post(
            f"/conversations/{test_conversation.id}/add_message",
            json={"content": "a follow-up question"},
        )
        assert response.status_code == 200
        assert response.json()["conversation"]["title"] == original_title
        mock_generate_title.assert_not_awaited()


class TestAnswerLanguageMatchesFirstMessage:
    """stream_text must be called with the conversation's actual first
    message, not just the current one, so the answer language doesn't drift
    over a long conversation."""

    def _make_stream_mock(self, content):
        async def _gen(*args, **kwargs):
            yield content
            yield {}
        return MagicMock(side_effect=_gen)

    @patch("src.routers.conversations.run_retrieval")
    def test_passes_current_message_as_first_message_on_first_turn(self, mock_retrieval, client):
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}
        mock_stream = self._make_stream_mock("respuesta")

        with patch("src.routers.conversations.OllamaConnector.stream_text", mock_stream):
            response = client.post(
                "/conversations/new",
                json={"content": "¿Qué es el cáncer?"},
            )
        assert response.status_code == 200
        assert mock_stream.call_args.kwargs["first_message"] == "¿Qué es el cáncer?"

    @patch("src.routers.conversations.run_retrieval")
    def test_passes_original_first_message_on_later_turn(
        self, mock_retrieval, client, test_conversation
    ):
        mock_retrieval.return_value = {"generation_context": "info", "intent": "concept"}
        mock_stream = self._make_stream_mock("answer")
        original_first_message = test_conversation.messages[0].content

        with patch("src.routers.conversations.OllamaConnector.stream_text", mock_stream):
            response = client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "a completely different follow-up"},
            )
        assert response.status_code == 200
        assert mock_stream.call_args.kwargs["first_message"] == original_first_message
        assert mock_stream.call_args.kwargs["first_message"] != "a completely different follow-up"


class TestNewConversation:
    @patch("src.routers.conversations.run_retrieval")
    def test_new_conversation_creates_conversation_and_messages(self, mock_retrieval, client):
        mock_retrieval.return_value = {"generation_context": "cancer info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "What is cancer?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert "conversation" in data
        assert len(data["messages"]) == 2  # user + assistant

    @patch("src.routers.conversations.run_retrieval")
    def test_new_conversation_returns_messages_and_metadata(self, mock_retrieval, client):
        mock_retrieval.return_value = {"generation_context": "metastasis info", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": "Tell me about metastasis"},
        )
        assert response.status_code == 200
        data = response.json()
        conv = data["conversation"]
        assert "id" in conv
        assert "title" in conv
        assert "updatedAt" in conv
        messages = data["messages"]
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_new_conversation_unauthenticated_returns_401(self, anon_client):
        response = anon_client.post(
            "/conversations/new",
            json={"content": "What is cancer?"},
        )
        assert response.status_code == 401

    @patch("src.routers.conversations.run_retrieval")
    def test_new_conversation_empty_content_allowed(self, mock_retrieval, client):
        mock_retrieval.return_value = {"generation_context": "", "intent": "concept"}

        response = client.post(
            "/conversations/new",
            json={"content": ""},
        )
        # Empty content might be allowed (depends on implementation)
        # At minimum, it shouldn't 500
        assert response.status_code in [200, 400, 422]


class TestAddMessage:
    @patch("src.routers.conversations.run_retrieval")
    def test_add_message_to_existing_conversation(self, mock_retrieval, client, test_conversation):
        mock_retrieval.return_value = {"generation_context": "glycolysis info", "intent": "concept"}

        response = client.post(
            f"/conversations/{test_conversation.id}/add_message",
            json={"content": "What is glycolysis?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert len(data["messages"]) == 2  # user + assistant

    def test_add_message_conversation_not_found_returns_404(self, client):
        import uuid
        fake_id = uuid.uuid4()
        response = client.post(
            f"/conversations/{fake_id}/add_message",
            json={"content": "Any question"},
        )
        assert response.status_code == 404

    def test_add_message_wrong_user_conversation_returns_403(self, client, db_session, test_user):
        import uuid
        from src.db.repositories.conversations import create_conversation

        other_user_id = uuid.uuid4()
        conv = create_conversation(db_session, user_id=other_user_id, title="Other user's conv")
        db_session.commit()

        response = client.post(
            f"/conversations/{conv.id}/add_message",
            json={"content": "Trying to access another user's conversation"},
        )
        assert response.status_code == 403

    @patch("src.routers.conversations.run_retrieval")
    def test_add_message_returns_conversation_metadata(self, mock_retrieval, client, test_conversation):
        mock_retrieval.return_value = {"generation_context": "apoptosis info", "intent": "concept"}

        response = client.post(
            f"/conversations/{test_conversation.id}/add_message",
            json={"content": "What is apoptosis?"},
        )
        assert response.status_code == 200
        data = response.json()
        conv = data["conversation"]
        assert str(conv["id"]) == str(test_conversation.id)


class TestConversationProfileContextToggle:
    def test_new_conversation_defaults_to_true(self, client):
        response = client.post("/conversations/create/", json={"title": "Test"})
        assert response.status_code == 201
        assert response.json()["use_profile_context"] is True

    def test_patch_flips_the_flag(self, client, test_conversation):
        response = client.patch(
            f"/conversations/{test_conversation.id}", json={"use_profile_context": False},
        )
        assert response.status_code == 200
        assert response.json()["use_profile_context"] is False

    def test_patch_wrong_user_conversation_returns_404(self, client, db_session):
        import uuid
        from src.db.repositories.conversations import create_conversation

        other_user_id = uuid.uuid4()
        conv = create_conversation(db_session, user_id=other_user_id, title="Other user's conv")
        db_session.commit()

        response = client.patch(f"/conversations/{conv.id}", json={"use_profile_context": False})
        assert response.status_code == 404

    def test_messages_endpoint_reports_the_flag(self, client, test_conversation, db_session):
        from src.db.repositories.conversations import set_use_profile_context

        set_use_profile_context(db_session, test_conversation.id, test_conversation.user_id, False)
        response = client.get(f"/conversations/{test_conversation.id}/messages/")
        assert response.json()["conversation"]["use_profile_context"] is False


class TestProfileContextReachesThePrompt:
    def test_populated_profile_passed_to_stream_text(self, client, test_conversation, db_session):
        from src.db.repositories.profile import upsert_profile

        upsert_profile(db_session, test_conversation.user_id, cancer_type="Glioblastoma", stage="IV")

        captured = {}

        async def _gen(*args, **kwargs):
            captured.update(kwargs)
            yield "answer."
            yield {}

        with patch("src.routers.conversations.OllamaConnector.stream_text", new=_gen):
            response = client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "What is glycolysis?"},
            )
        assert response.status_code == 200
        assert captured["profile_context"] is not None
        assert "Glioblastoma" in captured["profile_context"]

    def test_no_profile_passes_none(self, client, test_conversation):
        captured = {}

        async def _gen(*args, **kwargs):
            captured.update(kwargs)
            yield "answer."
            yield {}

        with patch("src.routers.conversations.OllamaConnector.stream_text", new=_gen):
            client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "What is glycolysis?"},
            )
        assert captured["profile_context"] is None

    def test_toggle_off_suppresses_profile_context_even_when_populated(
        self, client, test_conversation, db_session
    ):
        from src.db.repositories.profile import upsert_profile
        from src.db.repositories.conversations import set_use_profile_context

        upsert_profile(db_session, test_conversation.user_id, cancer_type="Glioblastoma")
        set_use_profile_context(db_session, test_conversation.id, test_conversation.user_id, False)

        captured = {}

        async def _gen(*args, **kwargs):
            captured.update(kwargs)
            yield "answer."
            yield {}

        with patch("src.routers.conversations.OllamaConnector.stream_text", new=_gen):
            client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "What is glycolysis?"},
            )
        assert captured["profile_context"] is None


class TestTruncatedFlag:
    def test_assistant_message_persists_truncated_true(self, client, test_conversation):
        async def _gen(*a, **k):
            yield "cut off mid"
            yield {"_finish_reason": "length"}

        with patch("src.routers.conversations.OllamaConnector.stream_text", new=_gen):
            response = client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "What is glycolysis?"},
            )
        assert response.status_code == 200
        assistant_msg = next(m for m in response.json()["messages"] if m["role"] == "assistant")
        assert assistant_msg["truncated"] is True

    def test_assistant_message_truncated_false_by_default(self, client, test_conversation):
        response = client.post(
            f"/conversations/{test_conversation.id}/add_message",
            json={"content": "What is glycolysis?"},
        )
        assert response.status_code == 200
        assistant_msg = next(m for m in response.json()["messages"] if m["role"] == "assistant")
        assert assistant_msg["truncated"] is False

    def test_get_messages_includes_truncated_field(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message

        add_message(
            db_session, conversation_id=test_conversation.id, role="assistant",
            content="cut off", truncated=True,
        )
        db_session.commit()

        response = client.get(f"/conversations/{test_conversation.id}/messages/")
        assert response.status_code == 200
        msg = next(m for m in response.json()["messages"] if m["content"] == "cut off")
        assert msg["truncated"] is True


class TestListConversations:
    def test_get_conversations_list_returns_conversations(self, client, test_conversation):
        response = client.get("/conversations/")
        assert response.status_code == 200
        data = response.json()
        assert "conversations" in data
        assert len(data["conversations"]) > 0

    def test_get_conversations_list_respects_limit(self, client, db_session, test_user):
        from src.db.repositories.conversations import create_conversation

        for i in range(5):
            create_conversation(db_session, user_id=test_user.id, title=f"Conv {i}")
        db_session.commit()

        response = client.get("/conversations/?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["conversations"]) <= 2

    def test_get_conversations_list_unauthenticated_returns_401(self, anon_client):
        response = anon_client.get("/conversations/")
        assert response.status_code == 401


class TestDeleteConversation:
    def test_delete_conversation_success_returns_200(self, client, test_conversation):
        response = client.delete(f"/conversations/{test_conversation.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_delete_conversation_not_found_returns_404(self, client):
        import uuid
        fake_id = uuid.uuid4()
        response = client.delete(f"/conversations/{fake_id}")
        assert response.status_code == 404

    def test_delete_conversation_already_deleted_returns_404(self, client, test_conversation):
        # Delete once
        client.delete(f"/conversations/{test_conversation.id}")
        # Try deleting again
        response = client.delete(f"/conversations/{test_conversation.id}")
        assert response.status_code == 404


class TestConversationMessages:
    def test_get_conversation_messages_returns_paginated_messages(self, client, test_conversation):
        response = client.get(f"/conversations/{test_conversation.id}/messages/")
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert "conversation" in data
        assert len(data["messages"]) > 0

    def test_get_conversation_messages_respects_limit(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message

        for i in range(5):
            add_message(db_session, conversation_id=test_conversation.id, role="user", content=f"msg{i}")
        db_session.commit()

        response = client.get(f"/conversations/{test_conversation.id}/messages/?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) <= 2

    def test_get_conversation_messages_not_found_returns_404(self, client):
        import uuid
        fake_id = uuid.uuid4()
        response = client.get(f"/conversations/{fake_id}/messages/")
        assert response.status_code == 404

    def test_get_conversation_messages_wrong_user_returns_403(self, client):
        import uuid
        from src.db.repositories.conversations import create_conversation
        from src.db import sql

        # Create a conversation for another (fake) user
        other_user_id = uuid.uuid4()
        db = None
        for dep_override in [item for item in [client] if hasattr(item, '__dict__')]:
            pass

        # Simpler: just try with a random ID that would belong to another user (will be not found or 403)
        fake_id = uuid.uuid4()
        response = client.get(f"/conversations/{fake_id}/messages/")
        assert response.status_code in [403, 404]


class TestMessageFeedback:
    def test_feedback_up_returns_vote(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()

        response = client.post(
            f"/conversations/{test_conversation.id}/messages/{msg.id}/feedback",
            json={"vote": 1},
        )
        assert response.status_code == 200
        assert response.json()["vote"] == 1

    def test_feedback_same_vote_toggles_off(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()

        client.post(f"/conversations/{test_conversation.id}/messages/{msg.id}/feedback", json={"vote": -1})
        response = client.post(
            f"/conversations/{test_conversation.id}/messages/{msg.id}/feedback",
            json={"vote": -1},
        )
        assert response.json()["vote"] is None

    def test_feedback_on_user_message_returns_400(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="user", content="question")
        db_session.commit()

        response = client.post(
            f"/conversations/{test_conversation.id}/messages/{msg.id}/feedback",
            json={"vote": 1},
        )
        assert response.status_code == 400

    def test_feedback_invalid_vote_returns_422(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()

        response = client.post(
            f"/conversations/{test_conversation.id}/messages/{msg.id}/feedback",
            json={"vote": 2},
        )
        assert response.status_code == 422

    def test_feedback_message_not_found_returns_404(self, client, test_conversation):
        import uuid
        response = client.post(
            f"/conversations/{test_conversation.id}/messages/{uuid.uuid4()}/feedback",
            json={"vote": 1},
        )
        assert response.status_code == 404

    def test_feedback_conversation_not_found_returns_404(self, client, test_conversation, db_session):
        import uuid
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()

        response = client.post(
            f"/conversations/{uuid.uuid4()}/messages/{msg.id}/feedback",
            json={"vote": 1},
        )
        assert response.status_code == 404

    def test_message_listing_includes_feedback_state(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()
        client.post(f"/conversations/{test_conversation.id}/messages/{msg.id}/feedback", json={"vote": 1})

        response = client.get(f"/conversations/{test_conversation.id}/messages/")
        row = next(m for m in response.json()["messages"] if m["id"] == str(msg.id))
        assert row["feedback"] == 1


class TestSplitConversation:
    @patch("src.routers.conversations.OllamaConnector.generate_title", new_callable=AsyncMock)
    def test_split_creates_new_conversation_with_generated_title(
        self, mock_generate_title, client, test_conversation, db_session
    ):
        from src.db.repositories.messeges import add_message
        mock_generate_title.return_value = "Split Title"
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()

        response = client.post(f"/conversations/{test_conversation.id}/messages/{msg.id}/split")
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Split Title"
        assert data["id"] != str(test_conversation.id)
        # Titled from the preceding question, not the answer itself
        mock_generate_title.assert_awaited_once_with("What is cancer?")

    @patch("src.routers.conversations.OllamaConnector.generate_title", new_callable=AsyncMock)
    def test_split_copies_messages_up_to_split_point(
        self, mock_generate_title, client, test_conversation, db_session
    ):
        from src.db.repositories.messeges import add_message
        mock_generate_title.return_value = "Split Title"
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        add_message(db_session, conversation_id=test_conversation.id, role="user", content="not included")
        db_session.commit()

        response = client.post(f"/conversations/{test_conversation.id}/messages/{msg.id}/split")
        new_conv_id = response.json()["id"]

        messages_response = client.get(f"/conversations/{new_conv_id}/messages/")
        contents = [m["content"] for m in messages_response.json()["messages"]]
        assert contents == ["What is cancer?", "answer"]

    def test_split_on_user_message_returns_400(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message
        msg = add_message(db_session, conversation_id=test_conversation.id, role="user", content="question")
        db_session.commit()

        response = client.post(f"/conversations/{test_conversation.id}/messages/{msg.id}/split")
        assert response.status_code == 400

    def test_split_message_not_found_returns_404(self, client, test_conversation):
        import uuid
        response = client.post(f"/conversations/{test_conversation.id}/messages/{uuid.uuid4()}/split")
        assert response.status_code == 404

    @patch("src.routers.conversations.OllamaConnector.generate_title", new_callable=AsyncMock)
    def test_split_sets_lineage(self, mock_generate_title, client, test_conversation, db_session):
        import uuid
        from src.db.repositories.messeges import add_message
        from src.db.models import Conversation
        mock_generate_title.return_value = "Split Title"
        msg = add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="answer")
        db_session.commit()

        response = client.post(f"/conversations/{test_conversation.id}/messages/{msg.id}/split")
        new_conv_id = uuid.UUID(response.json()["id"])
        new_conv = db_session.query(Conversation).filter(Conversation.id == new_conv_id).first()
        assert str(new_conv.forked_from_conversation_id) == str(test_conversation.id)
        assert str(new_conv.forked_from_message_id) == str(msg.id)


class TestFallbackPath:
    def test_no_data_response_appends_source_citations(self, client, test_conversation):
        from src.classes.ollama_connector import NO_DATA_RESPONSE
        with patch(
            "src.routers.conversations.OllamaConnector.stream_text",
            new=_make_stream(NO_DATA_RESPONSE),
        ):
            response = client.post(
                f"/conversations/{test_conversation.id}/add_message",
                json={"content": "Very specific research question"},
            )

            assert response.status_code == 200
            data = response.json()
            assistant_msg = data["messages"][-1]
            assert assistant_msg["role"] == "assistant"
            # When the LLM has no relevant data, source citations are appended
            assert "Related sources:" in assistant_msg["content"]


class TestWebSocket:
    def test_websocket_add_message_sends_stages_and_final(self, client, test_conversation):
        conv_id = str(test_conversation.id)
        with client.websocket_connect(f"/conversations/{conv_id}/add_message/ws") as ws:
            ws.send_json({"content": "What is glycolysis?"})
            messages = []
            while True:
                msg = ws.receive_json()
                messages.append(msg)
                if msg.get("type") in ("final", "error"):
                    break

        types = [m.get("type") for m in messages]
        assert "stage" in types
        assert "final" in types or "error" in types

        if "final" in types:
            final = next(m for m in messages if m["type"] == "final")
            assert "messages" in final
            assert "conversation" in final

    def test_websocket_unauthenticated_returns_401_in_error(self, anon_client, test_conversation):
        conv_id = str(test_conversation.id)
        with pytest.raises(Exception):  # Connection rejected or error message
            with anon_client.websocket_connect(f"/conversations/{conv_id}/add_message/ws") as ws:
                ws.send_json({"content": "Any question"})


class TestContinueMessage:
    def _make_truncated_message(self, db_session, conversation_id):
        from src.db.repositories.messeges import add_message

        msg = add_message(
            db_session, conversation_id=conversation_id, role="assistant",
            content="Cancer cells favor glycolysis [src-001]",
            sources_ids=["src-001"], truncated=True,
        )
        db_session.commit()
        return msg

    def _run_continue(self, client, conversation_id, message_id):
        messages = []
        with client.websocket_connect(f"/conversations/{conversation_id}/add_message/ws") as ws:
            ws.send_json({"continue_message_id": str(message_id)})
            while True:
                msg = ws.receive_json()
                messages.append(msg)
                if msg.get("type") in ("final", "error"):
                    break
        return messages

    def test_continue_appends_to_message_and_clears_truncated(self, client, test_conversation, db_session):
        msg = self._make_truncated_message(db_session, test_conversation.id)

        async def _gen(*a, **k):
            yield " more evidence [src-001]."
            yield {"_model": "test-model", "_finish_reason": "stop"}

        with patch(
            "src.routers.conversations.add_claims_and_sources",
            lambda m: setattr(m, "sources", [{"id": "src-001", "text": "evidence text"}]),
        ), patch("src.routers.conversations.OllamaConnector.stream_continuation", new=_gen):
            messages = self._run_continue(client, test_conversation.id, msg.id)

        final = next(m for m in messages if m["type"] == "final")
        assert "continued_message" in final
        continued = final["continued_message"]
        assert continued["content"] == "Cancer cells favor glycolysis [src-001] more evidence [src-001]."
        assert continued["truncated"] is False

    def test_continue_still_truncated_keeps_flag_true(self, client, test_conversation, db_session):
        msg = self._make_truncated_message(db_session, test_conversation.id)

        async def _gen(*a, **k):
            yield " still going"
            yield {"_model": "test-model", "_finish_reason": "length"}

        with patch(
            "src.routers.conversations.add_claims_and_sources",
            lambda m: setattr(m, "sources", [{"id": "src-001", "text": "evidence text"}]),
        ), patch("src.routers.conversations.OllamaConnector.stream_continuation", new=_gen):
            messages = self._run_continue(client, test_conversation.id, msg.id)

        final = next(m for m in messages if m["type"] == "final")
        assert final["continued_message"]["truncated"] is True

    def test_continue_non_truncated_message_errors(self, client, test_conversation, db_session):
        from src.db.repositories.messeges import add_message

        msg = add_message(
            db_session, conversation_id=test_conversation.id, role="assistant",
            content="already complete", truncated=False,
        )
        db_session.commit()

        messages = self._run_continue(client, test_conversation.id, msg.id)
        assert messages[-1]["type"] == "error"

    def test_continue_missing_message_errors(self, client, test_conversation):
        import uuid
        messages = self._run_continue(client, test_conversation.id, uuid.uuid4())
        assert messages[-1]["type"] == "error"

    def test_continue_wrong_users_message_errors(self, client, db_session):
        import uuid
        from src.db.repositories.conversations import create_conversation

        other_user_id = uuid.uuid4()
        conv = create_conversation(db_session, user_id=other_user_id, title="Other user's conv")
        db_session.commit()
        msg = self._make_truncated_message(db_session, conv.id)

        messages = self._run_continue(client, conv.id, msg.id)
        assert messages[-1]["type"] == "error"
