"""Add size_score and age_score columns to habitability_scores

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("habitability_scores",
                  sa.Column("size_score", sa.Float(), nullable=True))
    op.add_column("habitability_scores",
                  sa.Column("age_score", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("habitability_scores", "age_score")
    op.drop_column("habitability_scores", "size_score")
