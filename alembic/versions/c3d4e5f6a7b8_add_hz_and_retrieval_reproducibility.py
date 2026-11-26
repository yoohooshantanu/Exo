"""add hz assessment and retrieval reproducibility columns

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Habitable zone assessment columns
    op.add_column('habitability_scores', sa.Column('incident_stellar_flux', sa.Float(), nullable=True))
    op.add_column('habitability_scores', sa.Column('incident_stellar_flux_err', sa.Float(), nullable=True))
    op.add_column('habitability_scores', sa.Column('hz_conservative', sa.Boolean(), nullable=True))
    op.add_column('habitability_scores', sa.Column('hz_optimistic', sa.Boolean(), nullable=True))
    op.add_column('habitability_scores', sa.Column('hz_prob_conservative', sa.Float(), nullable=True))
    op.add_column('habitability_scores', sa.Column('hz_prob_optimistic', sa.Float(), nullable=True))
    op.add_column('habitability_scores', sa.Column('luminosity_solar', sa.Float(), nullable=True))
    op.add_column('habitability_scores', sa.Column('luminosity_source', sa.Text(), nullable=True))

    # 2. Atmospheric retrieval reproducibility columns
    op.add_column('atmospheric_retrievals', sa.Column('model_version', sa.Text(), nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('reproducibility_status', sa.Text(), nullable=True, server_default='configuration_recorded'))
    op.add_column('atmospheric_retrievals', sa.Column('configuration_record', JSONB, nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('opacity_provenance', JSONB, nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('sampler_name', sa.Text(), nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('sampler_version', sa.Text(), nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('random_seed', sa.Integer(), nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('sampler_parameters', JSONB, nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('priors_record', JSONB, nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('temperature_profile_record', JSONB, nullable=True))
    op.add_column('atmospheric_retrievals', sa.Column('convergence_diagnostics', JSONB, nullable=True))

def downgrade() -> None:
    op.drop_column('atmospheric_retrievals', 'convergence_diagnostics')
    op.drop_column('atmospheric_retrievals', 'temperature_profile_record')
    op.drop_column('atmospheric_retrievals', 'priors_record')
    op.drop_column('atmospheric_retrievals', 'sampler_parameters')
    op.drop_column('atmospheric_retrievals', 'random_seed')
    op.drop_column('atmospheric_retrievals', 'sampler_version')
    op.drop_column('atmospheric_retrievals', 'sampler_name')
    op.drop_column('atmospheric_retrievals', 'opacity_provenance')
    op.drop_column('atmospheric_retrievals', 'configuration_record')
    op.drop_column('atmospheric_retrievals', 'reproducibility_status')
    op.drop_column('atmospheric_retrievals', 'model_version')

    op.drop_column('habitability_scores', 'luminosity_source')
    op.drop_column('habitability_scores', 'luminosity_solar')
    op.drop_column('habitability_scores', 'hz_prob_optimistic')
    op.drop_column('habitability_scores', 'hz_prob_conservative')
    op.drop_column('habitability_scores', 'hz_optimistic')
    op.drop_column('habitability_scores', 'hz_conservative')
    op.drop_column('habitability_scores', 'incident_stellar_flux_err')
    op.drop_column('habitability_scores', 'incident_stellar_flux')
