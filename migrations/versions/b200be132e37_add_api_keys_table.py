"""add api keys table

Revision ID: b200be132e37
Revises: 267de93de48c
Create Date: 2026-10-12 22:11:46.377047

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b200be132e37'
down_revision: Union[str, Sequence[str], None] = '267de93de48c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Read API clients. Only a SHA-256 hash of each key is stored."""
  op.create_table(
    'api_keys',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('key_prefix', sa.String(length=12), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash'),
  )


def downgrade() -> None:
  op.drop_table('api_keys')
