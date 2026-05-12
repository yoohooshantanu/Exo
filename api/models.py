"""Pydantic response models."""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class PlanetListItem(BaseModel):
    planet_name: str
    hostname: Optional[str]
    discovery_method: Optional[str]
    discovery_year: Optional[int]
    radius_earth: Optional[float]
    mass_earth: Optional[float]
    period_days: Optional[float]
    eq_temperature_k: Optional[float]
    semi_major_axis_au: Optional[float]
    composite_score: Optional[float]
    hz_score: Optional[float]
    cluster_name: Optional[str]

    class Config:
        from_attributes = True


class PlanetDetail(BaseModel):
    planet_name: str
    planet_id: str
    hostname: Optional[str]
    star_id: Optional[str]
    status: str
    discovery_method: Optional[str]
    discovery_year: Optional[int]
    # Params
    radius_earth: Optional[float]
    mass_earth: Optional[float]
    period_days: Optional[float]
    eq_temperature_k: Optional[float]
    semi_major_axis_au: Optional[float]
    eccentricity: Optional[float]
    density_earth: Optional[float]
    # Scores
    composite_score: Optional[float]
    hz_score: Optional[float]
    teq_score: Optional[float]
    radius_esi_score: Optional[float]
    mass_esi_score: Optional[float]
    tidal_lock_score: Optional[float]
    flare_score: Optional[float]
    eccentricity_score: Optional[float]
    age_score: Optional[float]
    similarity_score: Optional[float]
    risk_score: Optional[float]
    # Cluster
    cluster_label: Optional[int]
    cluster_name: Optional[str]
    distance_to_centroid: Optional[float]
    # Anomalies
    anomaly_count: int
    anomaly_types: List[str]
    # Biosigs
    biosig_count: int
    molecules: List[str]
    # Gaps
    gap_count: int

    class Config:
        from_attributes = True


class StarItem(BaseModel):
    star_id: str
    hip_name: str
    ra: float
    dec: float
    distance_pc: Optional[float]
    planet_count: int

    class Config:
        from_attributes = True


class SpectrumPoint(BaseModel):
    wavelength_um: float
    depth_ppm: Optional[float]
    depth_err_upper: Optional[float]
    depth_err_lower: Optional[float]


class HitranLineItem(BaseModel):
    wavelength_um: float
    intensity: Optional[float]
    molecule: str


class MoleculeDetectionItem(BaseModel):
    molecule: str
    detection_sigma: float
    wavelength_um: Optional[float]
    hitran_match_count: Optional[int]
    abiotic_ruled_out: Optional[bool]
    instrument: Optional[str]
    facility: Optional[str]


class SpectrumView(BaseModel):
    spec_id: str
    instrument: Optional[str]
    facility: Optional[str]
    obs_type: Optional[str]
    points: List[SpectrumPoint]
    detections: List[MoleculeDetectionItem]
    hitran_lines: List[HitranLineItem]


class RankingItem(BaseModel):
    planet_name: str
    hostname: Optional[str]
    composite_score: Optional[float]
    category: str
    detail: Optional[str]


class AlertItem(BaseModel):
    alert_type: str
    planet_name: Optional[str]
    hostname: Optional[str]
    detail: str
    score: Optional[float]
    severity: str
    created_at: Optional[datetime]


class PlatformStats(BaseModel):
    stars: int
    planets: int
    habitability_scores: int
    orbital_predictions: int
    molecule_detections: int
    atmospheric_spectra: int
    anomaly_flags: int
    taxonomy_clusters: int


class PaginatedResponse(BaseModel):
    items: List
    total: int
    page: int
    page_size: int
    pages: int


class StarPositionItem(BaseModel):
    id: str
    hip_name: str = ""
    x: float
    y: float
    z: float
    teff: Optional[float] = None
    radius_solar: Optional[float] = None
    distance_pc: Optional[float] = None
    spectral_type: Optional[str] = None
    n_planets: int
    hab_score_max: float
    has_prediction: bool
    has_biosig: bool


class StarPositionsResponse(BaseModel):
    stars: List[StarPositionItem]


class PriorityTarget(BaseModel):
    planet_name: str
    hostname: Optional[str] = None
    composite_score: float
    hz_score: Optional[float] = None
    cluster_name: Optional[str] = None
    radius_earth: Optional[float] = None
    mass_earth: Optional[float] = None
    eq_temperature_k: Optional[float] = None
    biosig_count: int = 0
    molecules_detected: Optional[str] = None
    anomaly_count: int = 0
    rationale: str = ""


class SystemPlanet(BaseModel):
    planet_name: str
    radius_earth: Optional[float] = None
    mass_earth: Optional[float] = None
    semi_major_axis_au: Optional[float] = None
    period_days: Optional[float] = None
    eccentricity: Optional[float] = None
    eq_temperature_k: Optional[float] = None
    composite_score: Optional[float] = None
    cluster_name: Optional[str] = None

    class Config:
        from_attributes = True


class StarSystemResponse(BaseModel):
    star_id: str
    hip_name: str
    ra: Optional[float] = None
    dec: Optional[float] = None
    distance_pc: Optional[float] = None
    teff: Optional[float] = None
    radius_solar: Optional[float] = None
    mass_solar: Optional[float] = None
    planets: List[SystemPlanet] = []
