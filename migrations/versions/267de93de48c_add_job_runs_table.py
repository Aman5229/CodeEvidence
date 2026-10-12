"""add job runs table

Revision ID: 267de93de48c
Revises: 9c015e0e8c5f
Create Date: 2026-10-12 20:02:53.523675

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '267de93de48c'
down_revision: Union[str, Sequence[str], None] = '9c015e0e8c5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Background job tracking: status, attempts and errors. Failed rows are the dead letters."""
  op.create_table(
    'job_runs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('job_type', sa.String(length=50), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('event_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['event_id'], ['github_events.id']),
    sa.PrimaryKeyConstraint('id'),
  )
  op.create_index('ix_job_runs_event_id', 'job_runs', ['event_id'])
  op.create_index('ix_job_runs_status_id', 'job_runs', ['status', 'id'])


def downgrade() -> None:
  op.drop_index('ix_job_runs_status_id', table_name='job_runs')
  op.drop_index('ix_job_runs_event_id', table_name='job_runs')
  op.drop_table('job_runs')
