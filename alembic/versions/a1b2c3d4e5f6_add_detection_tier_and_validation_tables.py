"""add detection tier and validation tables

Revision ID: a1b2c3d4e5f6
Revises: 997abbe6a97c
Create Date: 2026-11-10 16:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '997abbe6a97c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add detection_tier and biosig_model_version to molecule_detections
    op.execute("ALTER TABLE molecule_detections ADD COLUMN IF NOT EXISTS detection_tier TEXT;")
    op.execute("ALTER TABLE molecule_detections ADD COLUMN IF NOT EXISTS biosig_model_version TEXT DEFAULT '3.0.0';")

    # 2. Backfill existing legacy records
    op.execute("""
        UPDATE molecule_detections
        SET detection_tier = 'screening_candidate', biosig_model_version = '3.0.0'
        WHERE detection_tier IS NULL AND detection_sigma >= 3.0 AND COALESCE(hitran_match_count, 0) >= 3;
    """)
    op.execute("""
        UPDATE molecule_detections
        SET detection_tier = 'marginal', biosig_model_version = '3.0.0'
        WHERE detection_tier IS NULL AND detection_sigma >= 2.0 AND COALESCE(hitran_match_count, 0) >= 2;
    """)
    op.execute("""
        UPDATE molecule_detections
        SET detection_tier = 'rejected', biosig_model_version = '3.0.0'
        WHERE detection_tier IS NULL;
    """)

    # 3. Create validation_runs and validation_results tables
    op.execute("""
        CREATE TABLE IF NOT EXISTS validation_runs (
            run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            engine_version TEXT NOT NULL,
            orbital_version TEXT NOT NULL,
            biosig_version TEXT NOT NULL,
            dataset_version TEXT NOT NULL,
            started_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ,
            total_samples INTEGER DEFAULT 0,
            status TEXT DEFAULT 'completed'
        );
        CREATE TABLE IF NOT EXISTS validation_results (
            result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES validation_runs(run_id) ON DELETE CASCADE,
            benchmark_name TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            expected_value DOUBLE PRECISION,
            actual_value DOUBLE PRECISION,
            tolerance DOUBLE PRECISION,
            sample_count INTEGER,
            status TEXT DEFAULT 'PASS'
        );
        CREATE INDEX IF NOT EXISTS ix_validation_results_run_id ON validation_results(run_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS validation_results CASCADE;")
    op.execute("DROP TABLE IF EXISTS validation_runs CASCADE;")
    op.execute("ALTER TABLE molecule_detections DROP COLUMN IF EXISTS biosig_model_version;")
    op.execute("ALTER TABLE molecule_detections DROP COLUMN IF EXISTS detection_tier;")
