"""Update habitability_scores to ESI-based components

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade():
    op.drop_column("habitability_scores", "size_score")
    op.add_column("habitability_scores", sa.Column("teq_score", sa.Float(), nullable=True))
    op.add_column("habitability_scores", sa.Column("radius_esi_score", sa.Float(), nullable=True))
    op.add_column("habitability_scores", sa.Column("mass_esi_score", sa.Float(), nullable=True))

def downgrade():
    op.add_column("habitability_scores", sa.Column("size_score", sa.Float(), nullable=True))
    op.drop_column("habitability_scores", "mass_esi_score")
    op.drop_column("habitability_scores", "radius_esi_score")
    op.drop_column("habitability_scores", "teq_score")
