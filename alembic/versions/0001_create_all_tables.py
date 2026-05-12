"""create_all_tables

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00

Creates all tables for the exoplanet discovery platform:
  Core:       stars, star_identifiers, planets
  Provenance: papers, ingestion_runs, planet_parameters, star_parameters
  Modules:    habitability_scores, orbital_predictions,
              biosignature_detections, anomaly_flags, taxonomy_clusters
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── extension: pgcrypto for gen_random_uuid() ─────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ─────────────────────────────────────────────────────────────────────────
    # CORE TABLES
    # ─────────────────────────────────────────────────────────────────────────

    op.create_table(
        "stars",
        sa.Column("star_id",     UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("hip_name",    sa.Text, nullable=False),
        sa.Column("ra",          sa.Float, nullable=False),
        sa.Column("dec",         sa.Float, nullable=False),
        sa.Column("distance_pc", sa.Float),
        sa.Column("created_at",  sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_stars_hip_name", "stars", ["hip_name"], unique=True)
    # Composite index on (ra, dec) for coordinate-based lookups
    op.create_index("ix_stars_ra_dec", "stars", ["ra", "dec"])


    op.create_table(
        "star_identifiers",
        sa.Column("id",           UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("star_id",      UUID(as_uuid=False),
                  sa.ForeignKey("stars.star_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("catalogue",    sa.Text, nullable=False),
        sa.Column("catalogue_id", sa.Text, nullable=False, index=True),
        sa.UniqueConstraint("catalogue", "catalogue_id",
                            name="uq_star_identifiers_cat_id"),
    )
    op.create_index("ix_star_identifiers_star_id", "star_identifiers", ["star_id"])


    op.create_table(
        "planets",
        sa.Column("planet_id",        UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("star_id",          UUID(as_uuid=False),
                  sa.ForeignKey("stars.star_id"), nullable=False),
        sa.Column("planet_name",      sa.Text, nullable=False),
        sa.Column("status",           sa.Text, nullable=False,
                  server_default="confirmed"),
        sa.Column("discovery_method", sa.Text),
        sa.Column("discovery_year",   sa.SmallInteger),
        sa.Column("created_at",       sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_planets_planet_name", "planets", ["planet_name"], unique=True)
    op.create_index("ix_planets_star_id",     "planets", ["star_id"])


    # ─────────────────────────────────────────────────────────────────────────
    # PROVENANCE TABLES
    # ─────────────────────────────────────────────────────────────────────────

    op.create_table(
        "papers",
        sa.Column("paper_id",     UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("doi",          sa.Text, unique=True),
        sa.Column("arxiv_id",     sa.Text, unique=True),
        sa.Column("title",        sa.Text),
        sa.Column("published_at", sa.Date),
        sa.Column("ingested_at",  sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_papers_doi",      "papers", ["doi"])
    op.create_index("ix_papers_arxiv_id", "papers", ["arxiv_id"])


    op.create_table(
        "ingestion_runs",
        sa.Column("run_id",           UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_version", sa.Text, nullable=False),
        sa.Column("source",           sa.Text, nullable=False),
        sa.Column("started_at",       sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("finished_at",      sa.DateTime(timezone=True)),
        sa.Column("records_affected", sa.Integer, server_default="0"),
        sa.Column("status",           sa.Text, server_default="running"),
        sa.Column("error_detail",     sa.Text),
    )


    op.create_table(
        "planet_parameters",
        sa.Column("param_id",          UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("planet_id",         UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("paper_id",          UUID(as_uuid=False),
                  sa.ForeignKey("papers.paper_id"), nullable=True),
        sa.Column("run_id",            UUID(as_uuid=False),
                  sa.ForeignKey("ingestion_runs.run_id"), nullable=False),
        sa.Column("param_name",        sa.Text, nullable=False),
        sa.Column("value",             sa.Float, nullable=False),
        sa.Column("uncertainty_upper", sa.Float),
        sa.Column("uncertainty_lower", sa.Float),
        sa.Column("unit",              sa.Text, nullable=False),
        sa.Column("is_default",        sa.Boolean, nullable=False,
                  server_default="true"),
        sa.Column("valid_from",        sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("valid_to",          sa.DateTime(timezone=True)),
        sa.Column("raw_source",        JSONB),
    )
    # primary lookup index: get current best value for a planet parameter
    op.create_index(
        "ix_planet_params_lookup",
        "planet_parameters",
        ["planet_id", "param_name", "is_default"],
    )
    op.create_index("ix_planet_params_planet_id", "planet_parameters", ["planet_id"])


    op.create_table(
        "star_parameters",
        sa.Column("param_id",          UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("star_id",           UUID(as_uuid=False),
                  sa.ForeignKey("stars.star_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("paper_id",          UUID(as_uuid=False),
                  sa.ForeignKey("papers.paper_id"), nullable=True),
        sa.Column("run_id",            UUID(as_uuid=False),
                  sa.ForeignKey("ingestion_runs.run_id"), nullable=False),
        sa.Column("param_name",        sa.Text, nullable=False),
        sa.Column("value",             sa.Float, nullable=False),
        sa.Column("uncertainty_upper", sa.Float),
        sa.Column("uncertainty_lower", sa.Float),
        sa.Column("unit",              sa.Text, nullable=False),
        sa.Column("is_default",        sa.Boolean, nullable=False,
                  server_default="true"),
        sa.Column("valid_from",        sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("valid_to",          sa.DateTime(timezone=True)),
        sa.Column("raw_source",        JSONB),
    )
    op.create_index(
        "ix_star_params_lookup",
        "star_parameters",
        ["star_id", "param_name", "is_default"],
    )
    op.create_index("ix_star_params_star_id", "star_parameters", ["star_id"])


    # ─────────────────────────────────────────────────────────────────────────
    # MODULE TABLES
    # ─────────────────────────────────────────────────────────────────────────

    op.create_table(
        "habitability_scores",
        sa.Column("score_id",           UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("planet_id",          UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id"), nullable=False),
        sa.Column("model_version",      sa.Text, nullable=False),
        sa.Column("composite_score",    sa.Float),
        sa.Column("hz_score",           sa.Float),
        sa.Column("tidal_lock_score",   sa.Float),
        sa.Column("flare_score",        sa.Float),
        sa.Column("eccentricity_score", sa.Float),
        sa.Column("input_snapshot",     JSONB),
        sa.Column("scored_at",          sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("planet_id", "model_version",
                            name="uq_habitability_planet_version"),
    )
    op.create_index("ix_habitability_planet_id", "habitability_scores", ["planet_id"])
    op.create_index(
        "ix_habitability_composite",
        "habitability_scores",
        ["composite_score"],
        postgresql_where=sa.text("composite_score IS NOT NULL"),
    )


    op.create_table(
        "orbital_predictions",
        sa.Column("prediction_id",          UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("star_id",                UUID(as_uuid=False),
                  sa.ForeignKey("stars.star_id"), nullable=False),
        sa.Column("predicted_period_days",  sa.Float, nullable=False),
        sa.Column("period_uncertainty",     sa.Float),
        sa.Column("mass_min_earth",         sa.Float),
        sa.Column("mass_max_earth",         sa.Float),
        sa.Column("stability_confidence",   sa.Float),
        sa.Column("n_body_runs",            sa.Integer),
        sa.Column("detection_method_hint",  sa.Text),
        sa.Column("model_version",          sa.Text, nullable=False),
        sa.Column("confirmed_by_planet_id", UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id"), nullable=True),
        # immutable — proof of prediction timestamp
        sa.Column("predicted_at",           sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_orbital_predictions_star_id", "orbital_predictions", ["star_id"])
    op.create_index(
        "ix_orbital_predictions_unconfirmed",
        "orbital_predictions",
        ["predicted_at"],
        postgresql_where=sa.text("confirmed_by_planet_id IS NULL"),
    )


    op.create_table(
        "biosignature_detections",
        sa.Column("detection_id",         UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("planet_id",            UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id"), nullable=False),
        sa.Column("molecule",             sa.Text, nullable=False),
        sa.Column("detection_confidence", sa.Float, nullable=False),
        sa.Column("wavelength_um",        sa.Float),
        sa.Column("jwst_program_id",      sa.Text),
        sa.Column("mast_file_uri",        sa.Text),
        # null=unknown | false=possible abiotic source | true=abiotic ruled out
        sa.Column("abiotic_ruled_out",    sa.Boolean),
        sa.Column("flagged_at",           sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_biosig_planet_id",   "biosignature_detections", ["planet_id"])
    op.create_index("ix_biosig_molecule",    "biosignature_detections", ["molecule"])
    op.create_index("ix_biosig_confidence",  "biosignature_detections", ["detection_confidence"])


    op.create_table(
        "anomaly_flags",
        sa.Column("anomaly_id",      UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("planet_id",       UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id"), nullable=False),
        sa.Column("anomaly_type",    sa.Text, nullable=False),
        sa.Column("deviation_sigma", sa.Float, nullable=False),
        sa.Column("expected_value",  sa.Float),
        sa.Column("observed_value",  sa.Float),
        sa.Column("unit",            sa.Text),
        sa.Column("model_reference", sa.Text),
        sa.Column("reviewed",        sa.Boolean, server_default="false"),
        sa.Column("flagged_at",      sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_anomaly_planet_id",  "anomaly_flags", ["planet_id"])
    op.create_index("ix_anomaly_reviewed",   "anomaly_flags", ["reviewed"])
    op.create_index("ix_anomaly_sigma",      "anomaly_flags", ["deviation_sigma"])


    op.create_table(
        "taxonomy_clusters",
        sa.Column("cluster_id",           UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("planet_id",            UUID(as_uuid=False),
                  sa.ForeignKey("planets.planet_id"), nullable=False),
        sa.Column("cluster_run_id",       UUID(as_uuid=False), nullable=False),
        sa.Column("cluster_label",        sa.SmallInteger, nullable=False),
        sa.Column("cluster_name",         sa.Text),
        sa.Column("distance_to_centroid", sa.Float),
        sa.Column("features_used",        ARRAY(sa.Text)),
        sa.Column("algorithm",            sa.Text),
        sa.Column("run_at",               sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_taxonomy_planet_id",     "taxonomy_clusters", ["planet_id"])
    op.create_index("ix_taxonomy_cluster_run_id","taxonomy_clusters", ["cluster_run_id"])


def downgrade() -> None:
    # drop in reverse dependency order
    op.drop_table("taxonomy_clusters")
    op.drop_table("anomaly_flags")
    op.drop_table("biosignature_detections")
    op.drop_table("orbital_predictions")
    op.drop_table("habitability_scores")
    op.drop_table("star_parameters")
    op.drop_table("planet_parameters")
    op.drop_table("ingestion_runs")
    op.drop_table("papers")
    op.drop_table("planets")
    op.drop_table("star_identifiers")
    op.drop_table("stars")

    op.execute("DROP EXTENSION IF EXISTS pgcrypto")