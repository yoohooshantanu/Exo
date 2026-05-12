"""
alembic/versions/0005_add_atmospheric_spectra.py

Adds:
  - atmospheric_spectra       — stores all published transmission/eclipse spectra
                                from NASA Atmospheric Spectroscopy Table
  - Extends biosignature_detections with spectrum_id foreign key
  - molecule_detections       — one row per molecule per spectrum (replaces
                                biosignature_detections for granular tracking)

Run:
  alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision      = "0005"
down_revision = "0004"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── atmospheric_spectra ───────────────────────────────────────────────────
    # One row per data point per spectrum publication.
    # Each published spectrum = multiple rows (one per wavelength bin).
    # spec_id groups all rows from one published spectrum together.
    op.create_table(
        "atmospheric_spectra",
        sa.Column("row_id",       UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("spec_id",      sa.Text, nullable=False),   # groups one full spectrum
        sa.Column("planet_id",    UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id", ondelete="SET NULL"),
                  nullable=True),                              # null if planet not in our DB
        sa.Column("planet_name",  sa.Text, nullable=False),   # raw name from archive
        sa.Column("hostname",     sa.Text),

        # spectrum metadata
        sa.Column("obs_type",     sa.Text),    # transmission | eclipse | direct_imaging
        sa.Column("instrument",   sa.Text),    # JWST/NIRSpec | JWST/MIRI | HST/WFC3 etc
        sa.Column("facility",     sa.Text),    # JWST | HST | Spitzer
        sa.Column("pub_reference",sa.Text),    # paper reference / DOI
        sa.Column("pub_date",     sa.Date),

        # spectral data point
        sa.Column("wavelength_um",  sa.Float, nullable=False),  # microns
        sa.Column("bandwidth_um",   sa.Float),                   # bin width
        sa.Column("depth_ppm",      sa.Float),                   # transit depth in ppm
        sa.Column("depth_err_upper",sa.Float),                   # +1σ
        sa.Column("depth_err_lower",sa.Float),                   # -1σ
        sa.Column("rprs",           sa.Float),                   # Rp/Rs (alternative)
        sa.Column("rp_earth",       sa.Float),                   # planet radius in R⊕

        # provenance
        sa.Column("ingested_at",  sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("run_id",       UUID(as_uuid=False),
                  sa.ForeignKey("ingestion_runs.run_id"), nullable=True),
    )
    op.create_index("ix_atm_spectra_planet_id",   "atmospheric_spectra", ["planet_id"])
    op.create_index("ix_atm_spectra_planet_name", "atmospheric_spectra", ["planet_name"])
    op.create_index("ix_atm_spectra_spec_id",     "atmospheric_spectra", ["spec_id"])
    op.create_index("ix_atm_spectra_wavelength",  "atmospheric_spectra", ["wavelength_um"])
    op.create_index("ix_atm_spectra_facility",    "atmospheric_spectra", ["facility"])


    # ── molecule_detections ───────────────────────────────────────────────────
    # One row per molecule per spectrum where a signal was detected.
    # More granular than biosignature_detections — tracks per-spectrum evidence.
    op.create_table(
        "molecule_detections",
        sa.Column("detection_id",       UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("planet_id",          UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("spec_id",            sa.Text, nullable=False),  # links to atmospheric_spectra
        sa.Column("molecule",           sa.Text, nullable=False),  # h2o|co2|ch4|co|o3|nh3|so2
        sa.Column("detection_sigma",    sa.Float, nullable=False), # confidence in σ
        sa.Column("wavelength_um",      sa.Float),                 # central detection wavelength
        sa.Column("hitran_match_count", sa.Integer),               # n lines matched
        sa.Column("depth_excess_ppm",   sa.Float),                 # observed excess vs continuum
        sa.Column("instrument",         sa.Text),
        sa.Column("facility",           sa.Text),
        sa.Column("pub_reference",      sa.Text),
        # null=unknown | false=known abiotic source | true=abiotic ruled out
        sa.Column("abiotic_ruled_out",  sa.Boolean),
        sa.Column("method_notes",       sa.Text),                  # how detection was flagged
        sa.Column("flagged_at",         sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("reviewed",           sa.Boolean, server_default="false"),
    )
    op.create_index("ix_mol_det_planet_id",  "molecule_detections", ["planet_id"])
    op.create_index("ix_mol_det_molecule",   "molecule_detections", ["molecule"])
    op.create_index("ix_mol_det_sigma",      "molecule_detections", ["detection_sigma"])
    op.create_index("ix_mol_det_reviewed",   "molecule_detections", ["reviewed"])

    # ── hitran_lines ──────────────────────────────────────────────────────────
    # Reference molecular line data from HITRAN for matching.
    # Populated once from HITRAN API — rarely changes.
    op.create_table(
        "hitran_lines",
        sa.Column("line_id",       UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("molecule",      sa.Text, nullable=False),   # h2o|co2|ch4|o3|co|n2o|nh3|so2
        sa.Column("wavelength_um", sa.Float, nullable=False),  # central wavelength in microns
        sa.Column("wavenumber",    sa.Float),                   # cm⁻¹ (from HITRAN directly)
        sa.Column("intensity",     sa.Float),                   # line strength at 296K
        sa.Column("einstein_a",    sa.Float),                   # transition probability
        sa.Column("lower_energy",  sa.Float),                   # lower state energy (cm⁻¹)
        sa.Column("hitran_source", sa.Text),                    # HITRAN | ExoMol
        sa.Column("ingested_at",   sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_hitran_molecule",   "hitran_lines", ["molecule"])
    op.create_index("ix_hitran_wavelength", "hitran_lines", ["wavelength_um"])
    # composite index for molecule + wavelength range queries
    op.create_index("ix_hitran_mol_wave",   "hitran_lines", ["molecule", "wavelength_um"])


def downgrade() -> None:
    op.drop_table("hitran_lines")
    op.drop_table("molecule_detections")
    op.drop_table("atmospheric_spectra")