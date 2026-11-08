"""add is_imputed to parameters

Revision ID: 5c03b920505d
Revises: 46149d200533
Create Date: 2026-06-25 00:08:29.763698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c03b920505d'
down_revision: Union[str, Sequence[str], None] = '46149d200533'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('planet_parameters', sa.Column('is_imputed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('star_parameters', sa.Column('is_imputed', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('star_parameters', 'is_imputed')
    op.drop_column('planet_parameters', 'is_imputed')
