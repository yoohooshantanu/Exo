"""add_spectral_type_to_stars

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-06 00:00:00

Add spectral_type text column to stars table so the star map
can show actual spectral classifications (e.g. "K2V") instead
of inferring them purely from effective temperature.
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stars",
        sa.Column("spectral_type", sa.Text, nullable=True),
    )
    op.create_index("ix_stars_spectral_type", "stars", ["spectral_type"])


def downgrade() -> None:
    op.drop_index("ix_stars_spectral_type", table_name="stars")
    op.drop_column("stars", "spectral_type")
