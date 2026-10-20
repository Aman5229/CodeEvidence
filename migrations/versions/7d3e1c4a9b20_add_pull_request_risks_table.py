"""add pull request risks table

Revision ID: 7d3e1c4a9b20
Revises: b200be132e37
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7d3e1c4a9b20'
down_revision: Union[str, Sequence[str], None] = 'b200be132e37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Each PR's features and rule-based risk score."""
  op.create_table(
    'pull_request_risks',
    sa.Column('pull_request_id', sa.BigInteger(), nullable=False),
    sa.Column('repository_id', sa.BigInteger(), nullable=False),
    sa.Column('files_changed', sa.Integer(), nullable=False),
    sa.Column('lines_changed', sa.Integer(), nullable=False),
    sa.Column('log_lines_changed', sa.Float(), nullable=False),
    sa.Column('test_file_ratio', sa.Float(), nullable=False),
    sa.Column('docs_only', sa.Boolean(), nullable=False),
    sa.Column('is_bot', sa.Boolean(), nullable=False),
    sa.Column('size_percentile', sa.Float(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id']),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
    sa.PrimaryKeyConstraint('pull_request_id'),
  )
  op.create_index(
    'ix_pull_request_risks_repository_id_lines', 'pull_request_risks', ['repository_id', 'lines_changed']
  )


def downgrade() -> None:
  op.drop_index('ix_pull_request_risks_repository_id_lines', table_name='pull_request_risks')
  op.drop_table('pull_request_risks')
