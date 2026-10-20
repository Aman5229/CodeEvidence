"""add learnings table

Revision ID: 7e4a1c8d2f95
Revises: 5c2e7a9b1d63
Create Date: 2026-10-20 10:20:00.000000

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7e4a1c8d2f95'
down_revision: Union[str, Sequence[str], None] = '5c2e7a9b1d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Repository rules learned from feedback, retrieved into future reviews."""
  op.create_table(
    'learnings',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('repository_id', sa.BigInteger(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('path_glob', sa.String(length=255), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('source_finding_id', sa.BigInteger(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=384), nullable=False),
    sa.Column('embedding_model', sa.String(length=100), nullable=False),
    sa.Column('times_applied', sa.Integer(), nullable=False),
    sa.Column('last_applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
    sa.ForeignKeyConstraint(['source_finding_id'], ['review_findings.id']),
    sa.PrimaryKeyConstraint('id'),
  )
  op.create_index('ix_learnings_repository_id', 'learnings', ['repository_id'])


def downgrade() -> None:
  op.drop_index('ix_learnings_repository_id', table_name='learnings')
  op.drop_table('learnings')
