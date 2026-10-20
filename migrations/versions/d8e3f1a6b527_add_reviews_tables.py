"""add reviews and review findings tables

Revision ID: d8e3f1a6b527
Revises: c5b9d2e7f418
Create Date: 2026-10-19 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd8e3f1a6b527'
down_revision: Union[str, Sequence[str], None] = 'c5b9d2e7f418'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """AI review runs and the findings they produced (kept and dropped)."""
  op.create_table(
    'reviews',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('pull_request_id', sa.BigInteger(), nullable=False),
    sa.Column('head_sha', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('prompt_version', sa.String(length=40), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('cache_key', sa.String(length=64), nullable=False),
    sa.Column('cached', sa.Boolean(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('llm_calls', sa.Integer(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('github_review_id', sa.BigInteger(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id']),
    sa.PrimaryKeyConstraint('id'),
  )
  op.create_index('ix_reviews_cache_key', 'reviews', ['cache_key'])
  op.create_index('ix_reviews_pull_request_id_created_at', 'reviews', ['pull_request_id', 'created_at'])
  op.create_table(
    'review_findings',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('review_id', sa.BigInteger(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('line', sa.Integer(), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('claim', sa.Text(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=False),
    sa.Column('suggestion', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('drop_reason', sa.String(length=40), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('finding_key', sa.String(length=32), nullable=False),
    sa.Column('github_comment_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id']),
    sa.PrimaryKeyConstraint('id'),
  )
  op.create_index('ix_review_findings_review_id', 'review_findings', ['review_id'])
  op.create_index('ix_review_findings_github_comment_id', 'review_findings', ['github_comment_id'])


def downgrade() -> None:
  op.drop_index('ix_review_findings_github_comment_id', table_name='review_findings')
  op.drop_index('ix_review_findings_review_id', table_name='review_findings')
  op.drop_table('review_findings')
  op.drop_index('ix_reviews_pull_request_id_created_at', table_name='reviews')
  op.drop_index('ix_reviews_cache_key', table_name='reviews')
  op.drop_table('reviews')
