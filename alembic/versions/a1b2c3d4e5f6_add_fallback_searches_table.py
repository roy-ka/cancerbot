"""add fallback_searches table

Revision ID: a1b2c3d4e5f6
Revises: cfdb7341f961
Create Date: 2026-04-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = 'a1b2c3d4e5f6'
down_revision = 'cfdb7341f961'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fallback_searches',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', UUID(as_uuid=True),
                  sa.ForeignKey('conversations.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('message_id', UUID(as_uuid=True),
                  sa.ForeignKey('messages.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('terms', JSON, nullable=True),
        sa.Column('initial_sources', JSON, nullable=True),
        sa.Column('pubmed_found', sa.Float, nullable=True),
        sa.Column('crossref_found', sa.Float, nullable=True),
        sa.Column('wikipedia_found', sa.Float, nullable=True),
        sa.Column('indexed', sa.Float, nullable=True),
        sa.Column('searched_web', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('fallback_searches')
