"""Clear extracted_terms rows that contain only stop words

Messages saved before the NLP fix may have extracted_terms like ["tell"] —
a scispaCy false-positive. These bad terms poison subsequent searches.
This migration nulls out any extracted_terms array whose every element is
a known stop word so the next request re-extracts terms cleanly.

Revision ID: clean_stopword_terms_001
Revises: fix_sources_ids_strip_chunk_001
Create Date: 2026-07-15
"""
from alembic import op

revision = 'clean_stopword_terms_001'
down_revision = 'fix_sources_ids_strip_chunk_001'
branch_labels = None
depends_on = None

# Must mirror _TERM_STOP_WORDS in src/routers/conversation_helper.py
_STOP_WORDS = (
    'the', 'and', 'or', 'is', 'are', 'was', 'were', 'be', 'been',
    'what', 'that', 'this', 'from', 'with', 'for', 'but', 'not',
    'has', 'have', 'had', 'can', 'could', 'will', 'would', 'should',
    'may', 'might', 'do', 'does', 'did', 'get', 'got', 'use', 'used',
    'how', 'why', 'when', 'where', 'who', 'which', 'there', 'here',
    'also', 'just', 'very', 'more', 'most', 'such', 'than', 'then',
    'about', 'like', 'into', 'over', 'after', 'some', 'any', 'all',
    'tell', 'give', 'show', 'explain', 'describe', 'list', 'find',
    'know', 'need', 'want', 'help', 'make', 'look', 'take',
    'see', 'say', 'let', 'put', 'ask',
    'no', 'yes',
)


def upgrade() -> None:
    # Build a SQL array literal from the stop-word tuple so we can use
    # NOT EXISTS ... WHERE lower(term) != ALL(stop_words) to detect rows
    # where every element is a stop word.
    # exec_driver_sql bypasses SQLAlchemy parameter substitution (avoids
    # ':c' / '%' placeholder conflicts).
    stop_array = "ARRAY[" + ",".join(f"'{w}'" for w in _STOP_WORDS) + "]"
    op.get_bind().exec_driver_sql(f"""
        UPDATE messages
        SET extracted_terms = NULL
        WHERE extracted_terms IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(extracted_terms::jsonb) AS term
              WHERE lower(term) != ALL({stop_array})
          )
    """)


def downgrade() -> None:
    pass
