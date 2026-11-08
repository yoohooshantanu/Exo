"""Add materialized view for discovery scores

Revision ID: 46149d200533
Revises: 74a80e71a7a6
Create Date: 2026-06-24 20:40:32.462168

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46149d200533'
down_revision: Union[str, Sequence[str], None] = '74a80e71a7a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from modules.discovery_score import DATA_QUALITY_SQL
from modules.config import HABITABILITY_MODEL_VERSION

DISCOVERY_SCORE_SQL = f"""ROUND(GREATEST(0, LEAST((
    COALESCE(hs.composite_score, 0) * 40
    + LEAST(
        COALESCE((
          SELECT COUNT(*) * 5.0 * (0.5 + 0.5 * LEAST(AVG(md.detection_sigma), 10.0) / 5.0)
          FROM molecule_detections md
          WHERE md.planet_id = p.planet_id AND md.detection_sigma >= 3
        ), 0)
      , 25)
    + {DATA_QUALITY_SQL}
    + LEAST(
        (SELECT COUNT(*) FROM planets p2 WHERE p2.star_id = p.star_id AND p2.status = 'confirmed') * 1.5
        + (SELECT COUNT(*) FROM orbital_predictions op WHERE op.star_id = p.star_id) * 2.0
      , 10)
    - LEAST((SELECT COUNT(*) FROM anomaly_flags af WHERE af.planet_id = p.planet_id) * 3.0, 10)
), 100))::numeric, 1)"""

def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_discovery_scores AS
        SELECT p.planet_id, {DISCOVERY_SCORE_SQL} AS discovery_score
        FROM planets p
        LEFT JOIN habitability_scores hs 
            ON hs.planet_id = p.planet_id 
            AND hs.model_version = '{HABITABILITY_MODEL_VERSION}'
    """)
    op.execute("CREATE UNIQUE INDEX ix_mv_discovery_scores_planet_id ON mv_discovery_scores(planet_id)")

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_discovery_scores")
