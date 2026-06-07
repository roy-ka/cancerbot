"""Populate extracted_terms for existing messages"""
from alembic import op
import sqlalchemy as sa
import json
import logging

logger = logging.getLogger(__name__)

revision = 'populate_extracted_terms_001'
down_revision = '40a72103fc4f'
branch_labels = None
depends_on = None

def fallback_extract_terms(text: str) -> list[str]:
    """Extract terms by simple word filtering"""
    if not text:
        return []
    
    words = text.split()
    stop_words = {
        'the', 'and', 'or', 'is', 'are', 'was', 'what', 'that', 'this', 'from',
        'with', 'for', 'but', 'has', 'have', 'had', 'can', 'could', 'will', 'would',
        'a', 'an', 'be', 'been', 'being', 'do', 'does', 'did', 'should'
    }
    
    meaningful = [w.lower() for w in words if len(w) >= 3 and w.lower() not in stop_words]
    return list(dict.fromkeys(meaningful))[:20]

def upgrade() -> None:
    connection = op.get_bind()
    
    # Get all messages with content but no extracted_terms
    result = connection.execute(
        sa.text("SELECT id, content FROM messages WHERE extracted_terms IS NULL AND content IS NOT NULL")
    )
    messages = result.fetchall()
    
    print(f"\n[Migration] Found {len(messages)} messages to process\n")
    
    processed = 0
    for msg_id, content in messages:
        terms = fallback_extract_terms(content)
        
        if terms:
            # Update the message with extracted terms
            connection.execute(
                sa.text("UPDATE messages SET extracted_terms = :terms WHERE id = :msg_id"),
                {"terms": json.dumps(terms), "msg_id": msg_id}
            )
            processed += 1
            if processed % 10 == 0:
                print(f"[Migration] Processed {processed} messages...")
    
    connection.commit()
    print(f"[Migration] Successfully populated {processed} messages\n")

def downgrade() -> None:
    op.execute("UPDATE messages SET extracted_terms = NULL")
