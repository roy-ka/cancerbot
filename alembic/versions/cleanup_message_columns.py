"""Remove intent and claim_ids columns, clean up terms"""
from alembic import op
import sqlalchemy as sa
import json

revision = 'cleanup_message_columns_001'
down_revision = 'populate_extracted_terms_001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    connection = op.get_bind()
    
    # Clean up '?' from extracted_terms
    result = connection.execute(
        sa.text("SELECT id, extracted_terms FROM messages WHERE extracted_terms IS NOT NULL")
    )
    messages = result.fetchall()
    
    for msg_id, terms_json in messages:
        if terms_json:
            try:
                terms = json.loads(terms_json) if isinstance(terms_json, str) else terms_json
                # Remove '?' from terms
                cleaned_terms = [t.strip('?').strip() for t in terms if t.strip() != '?']
                # Remove duplicates while preserving order
                cleaned_terms = list(dict.fromkeys(cleaned_terms))
                
                connection.execute(
                    sa.text("UPDATE messages SET extracted_terms = :terms WHERE id = :msg_id"),
                    {"terms": json.dumps(cleaned_terms), "msg_id": msg_id}
                )
            except Exception as e:
                print(f"Error processing message {msg_id}: {e}")
    
    connection.commit()
    print("[Migration] Cleaned up '?' from extracted_terms")
    
    # Drop intent column
    op.drop_column('messages', 'intent')
    print("[Migration] Dropped 'intent' column")
    
    # Drop claim_ids column
    op.drop_column('messages', 'claim_ids')
    print("[Migration] Dropped 'claim_ids' column")

def downgrade() -> None:
    # Add back the columns
    op.add_column('messages', sa.Column('intent', sa.String(20), nullable=True))
    op.add_column('messages', sa.Column('claim_ids', sa.JSON(), nullable=True))
