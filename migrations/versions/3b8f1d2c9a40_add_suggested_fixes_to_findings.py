"""add suggested fixes to review findings

Revision ID: 3b8f1d2c9a40
Revises: e2a7c4b9d630
Create Date: 2026-10-20 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3b8f1d2c9a40'
down_revision: Union[str, Sequence[str], None] = 'e2a7c4b9d630'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """One-click fixes: the replacement line, the line it replaces, and why a fix was refused."""
  op.add_column('review_findings', sa.Column('replacement', sa.Text(), nullable=True))
  op.add_column('review_findings', sa.Column('original_line', sa.Text(), nullable=True))
  op.add_column('review_findings', sa.Column('replacement_rejected', sa.String(length=20), nullable=True))


def downgrade() -> None:
  op.drop_column('review_findings', 'replacement_rejected')
  op.drop_column('review_findings', 'original_line')
  op.drop_column('review_findings', 'replacement')
