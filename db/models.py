"""
SQLAlchemy ORM models for the Exoplanet Discovery Platform.

Tables:
  Core:       stars, star_identifiers, planets
  Provenance: papers, ingestion_runs, planet_parameters, star_parameters
  Modules:    habitability_scores, orbital_predictions,
              biosignature_detections, anomaly_flags, taxonomy_clusters
"""

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index,
    Integer, SmallInteger, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# CORE TABLES
# ─────────────────────────────────────────────────────────────────────────────

class Star(Base):
    __tablename__ = "stars"

    star_id = Column(UUID(as_uuid=False), primary_key=True,
                     server_default=text("gen_random_uuid()"))
    hip_name = Column(Text, nullable=False, unique=True)
    ra = Column(Float, nullable=False)
    dec = Column(Float, nullable=False)
    distance_pc = Column(Float)
    spectral_type = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    # relationships
    identifiers = relationship("StarIdentifier", back_populates="star",
                               cascade="all, delete-orphan")
    planets = relationship("Planet", back_populates="star")
    parameters = relationship("StarParameter", back_populates="star",
                              cascade="all, delete-orphan")
    orbital_predictions = relationship("OrbitalPrediction", back_populates="star")


class StarIdentifier(Base):
    __tablename__ = "star_identifiers"

    id = Column(UUID(as_uuid=False), primary_key=True,
                server_default=text("gen_random_uuid()"))
    star_id = Column(UUID(as_uuid=False),
                     ForeignKey("stars.star_id", ondelete="CASCADE"),
                     nullable=False, index=True)
    catalogue = Column(Text, nullable=False)
    catalogue_id = Column(Text, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("catalogue", "catalogue_id",
                         name="uq_star_identifiers_cat_id"),
    )

    star = relationship("Star", back_populates="identifiers")


class Planet(Base):
    __tablename__ = "planets"

    planet_id = Column(UUID(as_uuid=False), primary_key=True,
                       server_default=text("gen_random_uuid()"))
    star_id = Column(UUID(as_uuid=False),
                     ForeignKey("stars.star_id"), nullable=False, index=True)
    planet_name = Column(Text, nullable=False, unique=True)
    status = Column(Text, nullable=False, server_default="confirmed")
    discovery_method = Column(Text)
    discovery_year = Column(SmallInteger)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    # relationships
    star = relationship("Star", back_populates="planets")
    parameters = relationship("PlanetParameter", back_populates="planet",
                              cascade="all, delete-orphan")
    habitability_scores = relationship("HabitabilityScore", back_populates="planet")
    biosignature_detections = relationship("BiosignatureDetection",
                                          back_populates="planet")
    anomaly_flags = relationship("AnomalyFlag", back_populates="planet")
    taxonomy_clusters = relationship("TaxonomyCluster", back_populates="planet")
    atmospheric_spectra = relationship("AtmosphericSpectrum", back_populates="planet")
    molecule_detections = relationship("MoleculeDetection", back_populates="planet")


# ─────────────────────────────────────────────────────────────────────────────
# PROVENANCE TABLES
# ─────────────────────────────────────────────────────────────────────────────

class Paper(Base):
    __tablename__ = "papers"

    paper_id = Column(UUID(as_uuid=False), primary_key=True,
                      server_default=text("gen_random_uuid()"))
    doi = Column(Text, unique=True, index=True)
    arxiv_id = Column(Text, unique=True, index=True)
    title = Column(Text)
    published_at = Column(Date)
    ingested_at = Column(DateTime(timezone=True), server_default=text("now()"))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id = Column(UUID(as_uuid=False), primary_key=True,
                    server_default=text("gen_random_uuid()"))
    pipeline_version = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True))
    records_affected = Column(Integer, server_default="0")
    status = Column(Text, server_default="running")
    error_detail = Column(Text)


class PlanetParameter(Base):
    __tablename__ = "planet_parameters"

    param_id = Column(UUID(as_uuid=False), primary_key=True,
                      server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id", ondelete="CASCADE"),
                       nullable=False, index=True)
    paper_id = Column(UUID(as_uuid=False),
                      ForeignKey("papers.paper_id"), nullable=True)
    run_id = Column(UUID(as_uuid=False),
                    ForeignKey("ingestion_runs.run_id"), nullable=False)
    param_name = Column(Text, nullable=False)
    value = Column(Float, nullable=False)
    uncertainty_upper = Column(Float)
    uncertainty_lower = Column(Float)
    unit = Column(Text, nullable=False)
    is_default = Column(Boolean, nullable=False, server_default="true")
    valid_from = Column(DateTime(timezone=True), server_default=text("now()"))
    valid_to = Column(DateTime(timezone=True))
    raw_source = Column(JSONB)

    __table_args__ = (
        Index("ix_planet_params_lookup", "planet_id", "param_name", "is_default"),
    )

    planet = relationship("Planet", back_populates="parameters")


class StarParameter(Base):
    __tablename__ = "star_parameters"

    param_id = Column(UUID(as_uuid=False), primary_key=True,
                      server_default=text("gen_random_uuid()"))
    star_id = Column(UUID(as_uuid=False),
                     ForeignKey("stars.star_id", ondelete="CASCADE"),
                     nullable=False, index=True)
    paper_id = Column(UUID(as_uuid=False),
                      ForeignKey("papers.paper_id"), nullable=True)
    run_id = Column(UUID(as_uuid=False),
                    ForeignKey("ingestion_runs.run_id"), nullable=False)
    param_name = Column(Text, nullable=False)
    value = Column(Float, nullable=False)
    uncertainty_upper = Column(Float)
    uncertainty_lower = Column(Float)
    unit = Column(Text, nullable=False)
    is_default = Column(Boolean, nullable=False, server_default="true")
    valid_from = Column(DateTime(timezone=True), server_default=text("now()"))
    valid_to = Column(DateTime(timezone=True))
    raw_source = Column(JSONB)

    __table_args__ = (
        Index("ix_star_params_lookup", "star_id", "param_name", "is_default"),
    )

    star = relationship("Star", back_populates="parameters")


# ─────────────────────────────────────────────────────────────────────────────
# MODULE TABLES
# ─────────────────────────────────────────────────────────────────────────────

class HabitabilityScore(Base):
    __tablename__ = "habitability_scores"

    score_id = Column(UUID(as_uuid=False), primary_key=True,
                      server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id"), nullable=False, index=True)
    model_version = Column(Text, nullable=False)
    composite_score = Column(Float)
    hz_score = Column(Float)
    teq_score = Column(Float)
    radius_esi_score = Column(Float)
    mass_esi_score = Column(Float)
    tidal_lock_score = Column(Float)
    flare_score = Column(Float)
    eccentricity_score = Column(Float)
    age_score = Column(Float)
    input_snapshot = Column(JSONB)
    scored_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("planet_id", "model_version",
                         name="uq_habitability_planet_version"),
    )

    planet = relationship("Planet", back_populates="habitability_scores")


class OrbitalPrediction(Base):
    __tablename__ = "orbital_predictions"

    prediction_id = Column(UUID(as_uuid=False), primary_key=True,
                           server_default=text("gen_random_uuid()"))
    star_id = Column(UUID(as_uuid=False),
                     ForeignKey("stars.star_id"), nullable=False, index=True)
    predicted_period_days = Column(Float, nullable=False)
    period_uncertainty = Column(Float)
    mass_min_earth = Column(Float)
    mass_max_earth = Column(Float)
    stability_confidence = Column(Float)
    n_body_runs = Column(Integer)
    detection_method_hint = Column(Text)
    model_version = Column(Text, nullable=False)
    confirmed_by_planet_id = Column(UUID(as_uuid=False),
                                    ForeignKey("planets.planet_id"), nullable=True)
    predicted_at = Column(DateTime(timezone=True),
                          server_default=text("now()"), nullable=False)

    star = relationship("Star", back_populates="orbital_predictions")


class BiosignatureDetection(Base):
    __tablename__ = "biosignature_detections"

    detection_id = Column(UUID(as_uuid=False), primary_key=True,
                          server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id"), nullable=False, index=True)
    molecule = Column(Text, nullable=False, index=True)
    detection_confidence = Column(Float, nullable=False, index=True)
    wavelength_um = Column(Float)
    jwst_program_id = Column(Text)
    mast_file_uri = Column(Text)
    abiotic_ruled_out = Column(Boolean)
    flagged_at = Column(DateTime(timezone=True), server_default=text("now()"))

    planet = relationship("Planet", back_populates="biosignature_detections")


class AnomalyFlag(Base):
    __tablename__ = "anomaly_flags"

    anomaly_id = Column(UUID(as_uuid=False), primary_key=True,
                        server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id"), nullable=False, index=True)
    anomaly_type = Column(Text, nullable=False)
    deviation_sigma = Column(Float, nullable=False, index=True)
    expected_value = Column(Float)
    observed_value = Column(Float)
    unit = Column(Text)
    model_reference = Column(Text)
    reviewed = Column(Boolean, server_default="false", index=True)
    flagged_at = Column(DateTime(timezone=True), server_default=text("now()"))

    planet = relationship("Planet", back_populates="anomaly_flags")


class TaxonomyCluster(Base):
    __tablename__ = "taxonomy_clusters"

    cluster_id = Column(UUID(as_uuid=False), primary_key=True,
                        server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id"), nullable=False, index=True)
    cluster_run_id = Column(UUID(as_uuid=False), nullable=False, index=True)
    cluster_label = Column(SmallInteger, nullable=False)
    cluster_name = Column(Text)
    distance_to_centroid = Column(Float)
    features_used = Column(ARRAY(Text))
    algorithm = Column(Text)
    run_at = Column(DateTime(timezone=True), server_default=text("now()"))

    planet = relationship("Planet", back_populates="taxonomy_clusters")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4: BIOSIGNATURE PIPELINE TABLES
# ─────────────────────────────────────────────────────────────────────────────

class AtmosphericSpectrum(Base):
    __tablename__ = "atmospheric_spectra"

    row_id = Column(UUID(as_uuid=False), primary_key=True,
                    server_default=text("gen_random_uuid()"))
    spec_id = Column(Text, nullable=False, index=True)
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id", ondelete="SET NULL"),
                       nullable=True, index=True)
    planet_name = Column(Text, nullable=False, index=True)
    hostname = Column(Text)

    # spectrum metadata
    obs_type = Column(Text)        # transmission | eclipse | direct_imaging
    instrument = Column(Text)      # JWST/NIRSpec | JWST/MIRI | HST/WFC3 etc
    facility = Column(Text, index=True)  # JWST | HST | Spitzer
    pub_reference = Column(Text)   # paper reference / DOI
    pub_date = Column(Date)

    # spectral data point
    wavelength_um = Column(Float, nullable=False, index=True)
    bandwidth_um = Column(Float)
    depth_ppm = Column(Float)      # transit depth in ppm
    depth_err_upper = Column(Float)  # +1σ
    depth_err_lower = Column(Float)  # -1σ
    rprs = Column(Float)           # Rp/Rs (alternative)
    rp_earth = Column(Float)       # planet radius in R⊕

    # provenance
    ingested_at = Column(DateTime(timezone=True), server_default=text("now()"))
    run_id = Column(UUID(as_uuid=False),
                    ForeignKey("ingestion_runs.run_id"), nullable=True)

    planet = relationship("Planet", back_populates="atmospheric_spectra")


class MoleculeDetection(Base):
    __tablename__ = "molecule_detections"

    detection_id = Column(UUID(as_uuid=False), primary_key=True,
                          server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id", ondelete="CASCADE"),
                       nullable=False, index=True)
    spec_id = Column(Text, nullable=False)
    molecule = Column(Text, nullable=False, index=True)
    detection_sigma = Column(Float, nullable=False, index=True)
    wavelength_um = Column(Float)
    hitran_match_count = Column(Integer)
    depth_excess_ppm = Column(Float)
    instrument = Column(Text)
    facility = Column(Text)
    pub_reference = Column(Text)
    abiotic_ruled_out = Column(Boolean)
    method_notes = Column(Text)
    flagged_at = Column(DateTime(timezone=True), server_default=text("now()"))
    reviewed = Column(Boolean, server_default="false", index=True)

    planet = relationship("Planet", back_populates="molecule_detections")


class AtmosphericRetrieval(Base):
    __tablename__ = "atmospheric_retrievals"

    retrieval_id = Column(UUID(as_uuid=False), primary_key=True,
                          server_default=text("gen_random_uuid()"))
    planet_id = Column(UUID(as_uuid=False),
                       ForeignKey("planets.planet_id", ondelete="CASCADE"),
                       nullable=False, index=True)
    spec_id = Column(Text, nullable=False, index=True)
    model_name = Column(Text, nullable=False) # e.g. "PLATON_v1"
    run_time_seconds = Column(Float)
    best_fit_params = Column(JSONB) # e.g. {"metallicity": 1.0, "C/O": 0.5, "cloud_top_pressure": 1e4}
    evidence_ln_z = Column(Float)
    posterior_file = Column(Text) # Path to saved posterior data (e.g. JSON or NPZ)
    status = Column(Text, server_default="running") # running, completed, failed
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    planet = relationship("Planet")



class HitranLine(Base):
    __tablename__ = "hitran_lines"

    line_id = Column(UUID(as_uuid=False), primary_key=True,
                     server_default=text("gen_random_uuid()"))
    molecule = Column(Text, nullable=False, index=True)
    wavelength_um = Column(Float, nullable=False, index=True)
    wavenumber = Column(Float)
    intensity = Column(Float)
    einstein_a = Column(Float)
    lower_energy = Column(Float)
    hitran_source = Column(Text)
    ingested_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_hitran_mol_wave", "molecule", "wavelength_um"),
    )


class SpectralTemplate(Base):
    __tablename__ = "spectral_templates"

    template_id = Column(UUID(as_uuid=False), primary_key=True,
                         server_default=text("gen_random_uuid()"))
    molecule = Column(Text, nullable=False, index=True)
    temperature_k = Column(Float, nullable=False)
    pressure_bar = Column(Float, nullable=False)
    instrument_resolution = Column(Integer, nullable=False)
    file_path = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_spectral_templates_lookup", "molecule", "temperature_k"),
    )
