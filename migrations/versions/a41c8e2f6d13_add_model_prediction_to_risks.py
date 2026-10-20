"""add model prediction to pull request risks

Revision ID: a41c8e2f6d13
Revises: 7d3e1c4a9b20
Create Date: 2026-10-19 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a41c8e2f6d13'
down_revision: Union[str, Sequence[str], None] = '7d3e1c4a9b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  """The trained model's prediction next to the rule score (null without a model)."""
  op.add_column('pull_request_risks', sa.Column('model_version', sa.String(length=40), nullable=True))
  op.add_column('pull_request_risks', sa.Column('model_probability', sa.Float(), nullable=True))
  op.add_column('pull_request_risks', sa.Column('model_flagged', sa.Boolean(), nullable=True))
  op.add_column(
    'pull_request_risks',
    sa.Column('model_inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
  )


def downgrade() -> None:
  op.drop_column('pull_request_risks', 'model_inputs')
  op.drop_column('pull_request_risks', 'model_flagged')
  op.drop_column('pull_request_risks', 'model_probability')
  op.drop_column('pull_request_risks', 'model_version')
