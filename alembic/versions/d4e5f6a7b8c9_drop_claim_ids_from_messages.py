"""drop claim_ids from messages

Revision ID: d4e5f6a7b8c9
Revises: c9d51316d12e, c3d4e5f6a7b8
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = ('c9d51316d12e', 'c3d4e5f6a7b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('messages', 'claim_ids')


def downgrade() -> None:
    op.add_column('messages', sa.Column('claim_ids', postgresql.JSON(astext_type=sa.Text()), nullable=True))
