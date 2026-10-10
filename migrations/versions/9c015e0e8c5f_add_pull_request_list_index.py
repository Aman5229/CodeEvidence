"""add pull request list index

Revision ID: 9c015e0e8c5f
Revises: 9c9ef8fe2981
Create Date: 2026-10-10 15:55:00.282850

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9c015e0e8c5f'
down_revision: Union[str, Sequence[str], None] = '9c9ef8fe2981'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """Index for the PR list: one repository's PRs, newest first, keyset paged."""
  op.create_index(
    'ix_pull_requests_repository_id_created_at_id',
    'pull_requests',
    ['repository_id', 'created_at', 'id'],
  )


def downgrade() -> None:
  op.drop_index('ix_pull_requests_repository_id_created_at_id', table_name='pull_requests')
