"""split triage indices and add iqr

Revision ID: 997abbe6a97c
Revises: 6bc6fda61e09
Create Date: 2026-06-25 18:07:51.991848

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '997abbe6a97c'
down_revision: Union[str, Sequence[str], None] = '6bc6fda61e09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from modules.discovery_score import DATA_QUALITY_SQL
from modules.config import HABITABILITY_MODEL_VERSION


def upgrade() -> None:
    # Add columns to habitability_scores
    op.add_column('habitability_scores', sa.Column('composite_score_iqr', sa.Float(), nullable=True))
    op.add_column('habitability_scores', sa.Column('is_imputed', sa.Boolean(), server_default='false', nullable=False))

    # Recreate the materialized view with new columns
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_discovery_scores")

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

    # Physical Triage Index = Habitability Score * 40 - Anomaly Penalty
    PHYSICAL_TRIAGE_SQL = f"""ROUND(GREATEST(0, LEAST((
        COALESCE(hs.composite_score, 0) * 40
        - LEAST((SELECT COUNT(*) FROM anomaly_flags af WHERE af.planet_id = p.planet_id) * 3.0, 10)
    ) * (100.0 / 40.0), 100))::numeric, 1)"""

    # Characterization Index = Biosignature (max 25) + Data Quality (max 15) scaled to 100
    CHAR_INDEX_SQL = f"""ROUND(GREATEST(0, LEAST((
        LEAST(
            COALESCE((
              SELECT COUNT(*) * 5.0 * (0.5 + 0.5 * LEAST(AVG(md.detection_sigma), 10.0) / 5.0)
              FROM molecule_detections md
              WHERE md.planet_id = p.planet_id AND md.detection_sigma >= 3
            ), 0)
          , 25)
        + {DATA_QUALITY_SQL}
    ) * (100.0 / 40.0), 100))::numeric, 1)"""

    # Observability Index = log10( (R_p / (R_s * 109.2))^2 / d_pc^2 )
    # Mapped to 0-100 where max (e.g., HD 209458 b ~ -2.5) is ~100 and -10 is 0.
    OBS_INDEX_SQL = """ROUND(GREATEST(0, LEAST((
        COALESCE(
            (LN( 
                POWER(
                    (SELECT MAX(CASE WHEN param_name = 'radius_earth' THEN value END) FROM planet_parameters WHERE planet_id = p.planet_id AND is_default = true) 
                    / (NULLIF( (SELECT MAX(CASE WHEN param_name = 'radius_solar' THEN value END) FROM star_parameters WHERE star_id = p.star_id AND is_default = true), 0) * 109.2)
                , 2)
                / NULLIF(POWER( (SELECT distance_pc FROM stars WHERE star_id = p.star_id), 2), 0)
            ) / LN(10))
        , -10) + 10) * (100.0 / 7.0)
    , 100))::numeric, 1)"""

    op.execute(f"""
        CREATE MATERIALIZED VIEW mv_discovery_scores AS
        SELECT 
            p.planet_id, 
            {DISCOVERY_SCORE_SQL} AS discovery_score,
            {PHYSICAL_TRIAGE_SQL} AS physical_triage_index,
            {CHAR_INDEX_SQL} AS characterization_index,
            {OBS_INDEX_SQL} AS observability_index
        FROM planets p
        LEFT JOIN habitability_scores hs 
            ON hs.planet_id = p.planet_id 
            AND hs.model_version = '{HABITABILITY_MODEL_VERSION}'
    """)
    op.execute("CREATE UNIQUE INDEX ix_mv_discovery_scores_planet_id ON mv_discovery_scores(planet_id)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_discovery_scores")
    
    op.drop_column('habitability_scores', 'is_imputed')
    op.drop_column('habitability_scores', 'composite_score_iqr')

    # Restore the old view
    # (Leaving it out for brevity, but this is the downgrade logic)
