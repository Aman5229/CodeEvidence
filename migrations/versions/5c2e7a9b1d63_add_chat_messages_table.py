"""add chat messages table

Revision ID: 5c2e7a9b1d63
Revises: 3b8f1d2c9a40
Create Date: 2026-10-20 10:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5c2e7a9b1d63'
down_revision: Union[str, Sequence[str], None] = '3b8f1d2c9a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Questions about a PR and the answers, from the dashboard and from GitHub."""
  op.create_table(
    'chat_messages',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('pull_request_id', sa.BigInteger(), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('github_user', sa.String(length=255), nullable=True),
    sa.Column('github_comment_id', sa.BigInteger(), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id']),
    sa.PrimaryKeyConstraint('id'),
  )
  op.create_index('ix_chat_messages_pull_request_id_id', 'chat_messages', ['pull_request_id', 'id'])


def downgrade() -> None:
  op.drop_index('ix_chat_messages_pull_request_id_id', table_name='chat_messages')
  op.drop_table('chat_messages')
