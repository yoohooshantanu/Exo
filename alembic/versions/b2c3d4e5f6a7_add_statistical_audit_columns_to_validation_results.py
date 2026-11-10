"""add statistical audit columns to validation_results

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-10 19:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('validation_results', sa.Column('ci_lower', sa.Float(), nullable=True))
    op.add_column('validation_results', sa.Column('ci_upper', sa.Float(), nullable=True))
    op.add_column('validation_results', sa.Column('p_value', sa.Float(), nullable=True))
    op.add_column('validation_results', sa.Column('inference_method', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('validation_results', 'inference_method')
    op.drop_column('validation_results', 'p_value')
    op.drop_column('validation_results', 'ci_upper')
    op.drop_column('validation_results', 'ci_lower')
