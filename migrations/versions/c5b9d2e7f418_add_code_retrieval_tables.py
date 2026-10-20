"""add code retrieval tables (pgvector)

Revision ID: c5b9d2e7f418
Revises: a41c8e2f6d13
Create Date: 2026-10-19 15:00:00.000000

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5b9d2e7f418'
down_revision: Union[str, Sequence[str], None] = 'a41c8e2f6d13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """File contents by blob SHA, and code chunks with embeddings and full-text search."""
  op.execute('CREATE EXTENSION IF NOT EXISTS vector')
  op.create_table(
    'file_blobs',
    sa.Column('blob_sha', sa.String(length=40), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('skipped_reason', sa.String(length=20), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('blob_sha'),
  )
  op.create_table(
    'code_chunks',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('repository_id', sa.BigInteger(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('blob_sha', sa.String(length=40), nullable=False),
    sa.Column('language', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('start_line', sa.Integer(), nullable=False),
    sa.Column('end_line', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=384), nullable=False),
    sa.Column('embedding_model', sa.String(length=100), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column(
      'search',
      postgresql.TSVECTOR(),
      sa.Computed("to_tsvector('simple', search_text)", persisted=True),
      nullable=True,
    ),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
    sa.PrimaryKeyConstraint('id'),
  )
  op.create_index('ix_code_chunks_repository_id_path', 'code_chunks', ['repository_id', 'path'])
  op.create_index(
    'ix_code_chunks_embedding',
    'code_chunks',
    ['embedding'],
    postgresql_using='hnsw',
    postgresql_ops={'embedding': 'vector_cosine_ops'},
  )
  op.create_index('ix_code_chunks_search', 'code_chunks', ['search'], postgresql_using='gin')


def downgrade() -> None:
  op.drop_index('ix_code_chunks_search', table_name='code_chunks')
  op.drop_index('ix_code_chunks_embedding', table_name='code_chunks')
  op.drop_index('ix_code_chunks_repository_id_path', table_name='code_chunks')
  op.drop_table('code_chunks')
  op.drop_table('file_blobs')
