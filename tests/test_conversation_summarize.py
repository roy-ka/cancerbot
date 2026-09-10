"""Tests for POST /conversations/{id}/summarize (src/routers/conversations.py)."""
from unittest.mock import patch, AsyncMock
import uuid

from src.db.repositories.messeges import add_message


class TestSummarizeConversation:
    def test_returns_the_generated_summary(self, client, db_session, test_conversation):
        add_message(db_session, conversation_id=test_conversation.id, role="assistant", content="Cancer is...")
        db_session.commit()

        with patch(
            "src.routers.conversations.OllamaConnector.summarize_conversation",
            new=AsyncMock(return_value="A short recap of the conversation."),
        ) as mock_summarize:
            res = client.post(f"/conversations/{test_conversation.id}/summarize")

        assert res.status_code == 200
        assert res.json() == {"summary": "A short recap of the conversation."}
        # Transcript passed to the LLM includes both roles
        transcript = mock_summarize.call_args.args[0]
        assert "User: What is cancer?" in transcript
        assert "CancerBot: Cancer is..." in transcript

    def test_hidden_messages_excluded_from_transcript(self, client, db_session, test_conversation):
        add_message(
            db_session, conversation_id=test_conversation.id, role="assistant",
            content="Ninja-only reply", hidden_from_user=True,
        )
        db_session.commit()

        with patch(
            "src.routers.conversations.OllamaConnector.summarize_conversation",
            new=AsyncMock(return_value="summary"),
        ) as mock_summarize:
            res = client.post(f"/conversations/{test_conversation.id}/summarize")

        assert res.status_code == 200
        transcript = mock_summarize.call_args.args[0]
        assert "Ninja-only reply" not in transcript

    def test_404_for_conversation_owned_by_someone_else(self, client):
        res = client.post(f"/conversations/{uuid.uuid4()}/summarize")
        assert res.status_code == 404

    def test_503_when_llm_unavailable(self, client, test_conversation):
        with patch(
            "src.routers.conversations.OllamaConnector.summarize_conversation",
            new=AsyncMock(side_effect=ValueError("AI generation unavailable")),
        ):
            res = client.post(f"/conversations/{test_conversation.id}/summarize")
        assert res.status_code == 503
