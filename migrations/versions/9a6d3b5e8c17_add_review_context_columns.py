"""add review context columns: mode, config, diagram, tools, check state

Revision ID: 9a6d3b5e8c17
Revises: 7e4a1c8d2f95
Create Date: 2026-10-20 10:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9a6d3b5e8c17'
down_revision: Union[str, Sequence[str], None] = '7e4a1c8d2f95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Incremental reviews, repository settings, diagrams, static analysis and commit statuses."""
  op.add_column('reviews', sa.Column('mode', sa.String(length=12), server_default='full', nullable=False))
  op.add_column('reviews', sa.Column('base_review_id', sa.BigInteger(), nullable=True))
  op.add_column('reviews', sa.Column('compared_from_sha', sa.String(length=40), nullable=True))
  op.add_column('reviews', sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
  op.add_column('reviews', sa.Column('diagram', sa.Text(), nullable=True))
  op.add_column('reviews', sa.Column('tools', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
  op.add_column('reviews', sa.Column('check_state', sa.String(length=10), nullable=True))
  op.create_foreign_key('fk_reviews_base_review_id', 'reviews', 'reviews', ['base_review_id'], ['id'])
  op.add_column('review_findings', sa.Column('carried_from_review_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
  op.drop_column('review_findings', 'carried_from_review_id')
  op.drop_constraint('fk_reviews_base_review_id', 'reviews', type_='foreignkey')
  op.drop_column('reviews', 'check_state')
  op.drop_column('reviews', 'tools')
  op.drop_column('reviews', 'diagram')
  op.drop_column('reviews', 'config')
  op.drop_column('reviews', 'compared_from_sha')
  op.drop_column('reviews', 'base_review_id')
  op.drop_column('reviews', 'mode')
