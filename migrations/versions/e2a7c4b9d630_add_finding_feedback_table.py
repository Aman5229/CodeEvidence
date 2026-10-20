"""add finding feedback table

Revision ID: e2a7c4b9d630
Revises: d8e3f1a6b527
Create Date: 2026-10-19 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2a7c4b9d630'
down_revision: Union[str, Sequence[str], None] = 'd8e3f1a6b527'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Feedback on findings, from GitHub and the dashboard."""
  op.create_table(
    'finding_feedback',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('finding_id', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('verdict', sa.String(length=20), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('github_user', sa.String(length=255), nullable=True),
    sa.Column('external_id', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['finding_id'], ['review_findings.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_id'),
  )
  op.create_index('ix_finding_feedback_finding_id', 'finding_feedback', ['finding_id'])


def downgrade() -> None:
  op.drop_index('ix_finding_feedback_finding_id', table_name='finding_feedback')
  op.drop_table('finding_feedback')
