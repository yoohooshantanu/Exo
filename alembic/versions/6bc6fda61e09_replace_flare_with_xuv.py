"""replace_flare_with_xuv

Revision ID: 6bc6fda61e09
Revises: 5c03b920505d
Create Date: 2026-06-25 17:12:15.321617

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bc6fda61e09'
down_revision: Union[str, Sequence[str], None] = '5c03b920505d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add xuv_escape_score, drop flare_score
    op.add_column('habitability_scores', sa.Column('xuv_escape_score', sa.Float(), nullable=True))
    op.drop_column('habitability_scores', 'flare_score')


def downgrade() -> None:
    # Revert
    op.add_column('habitability_scores', sa.Column('flare_score', sa.Float(), nullable=True))
    op.drop_column('habitability_scores', 'xuv_escape_score')
