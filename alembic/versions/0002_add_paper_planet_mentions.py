"""
add_paper_planet_mentions

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02

Adds paper_planet_mentions junction table.
Tracks which papers mention which planets/stars — soft provenance link.
In Phase 2 this becomes the hard provenance chain when we parse
actual parameter values out of paper text.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision      = "0002"
down_revision = "0001"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "paper_planet_mentions",
        sa.Column("id",         UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("paper_id",   UUID(as_uuid=False),
                  sa.ForeignKey("papers.paper_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("planet_id",  UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("star_id",    UUID(as_uuid=False),
                  sa.ForeignKey("stars.star_id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("name_found", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_ppm_paper_id",  "paper_planet_mentions", ["paper_id"])
    op.create_index("ix_ppm_planet_id", "paper_planet_mentions", ["planet_id"])
    op.create_index("ix_ppm_star_id",   "paper_planet_mentions", ["star_id"])


def downgrade() -> None:
    op.drop_table("paper_planet_mentions")