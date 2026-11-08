"""

Discovery Score — decision-support ranking metric for follow-up prioritization.

Formula: clamp(0, 100,
    habitability × 40  +  biosignature × 25  +  data_quality × 15
    + orbital_context × 10  −  anomaly_penalty × 10
)

Classification: DECISION-SUPPORT HEURISTIC
These weights are hand-chosen to reflect the relative importance of each
factor for observation proposal prioritization. They have NOT been validated
against outcomes (e.g., whether high-scoring planets are subsequently
confirmed or observed). The score is designed as a triage tool, not a
scientific quantity.

Weight rationale:
  habitability (40/100): A planet's physical and environmental suitability
    is the primary filter for follow-up interest.
  biosignature (25/100): Molecular detections are the strongest driver
    of immediate scientific interest and telescope time allocation.
  data_quality (15/100): Better-characterized targets yield more productive
    follow-up. NOTE: this component introduces circularity if used to
    validate the score against follow-up rates (planets with JWST data
    score higher because they were already observed).
  orbital_context (10/100): Multi-planet systems and predicted gaps add
    dynamical context that increases a planet's information value.
  anomaly_penalty (-10/100): Anomalous parameter combinations may indicate
    data quality issues rather than genuine scientific interest.

See validation/weight_stability.py for sensitivity analysis.
"""

# Data quality component — caps at 15 points
# Classification: COMPOSITE HEURISTIC
# Combines: has spectral data (5 pts), instrument tier (up to 5 pts),
#   core parameter completeness (up to 5 pts)
# WARNING: This component is inherently circular for validation — planets
# observed by JWST score higher, so correlating discovery_score with
# "was observed by JWST" partly recovers this component's own definition.

CORE_PARAMS = (
    "radius_earth",
    "mass_earth",
    "period_days",
    "eq_temperature_k",
    "semi_major_axis_au",
)

DATA_QUALITY_SQL = """LEAST(
    (
        CASE WHEN EXISTS(
            SELECT 1 FROM atmospheric_spectra asp
            WHERE asp.planet_id = p.planet_id AND asp.depth_ppm IS NOT NULL
        ) THEN 5 ELSE 0 END
        + COALESCE((
            SELECT CASE
                WHEN bool_or(
                    LOWER(COALESCE(asp.facility, '')) LIKE '%jwst%'
                    OR LOWER(COALESCE(asp.instrument, '')) LIKE '%jwst%'
                ) THEN 5.0
                WHEN bool_or(
                    LOWER(COALESCE(asp.facility, '')) LIKE '%hst%'
                    OR LOWER(COALESCE(asp.instrument, '')) LIKE '%hubble%'
                ) THEN 3.5
                ELSE 2.0
            END
            FROM atmospheric_spectra asp
            WHERE asp.planet_id = p.planet_id AND asp.depth_ppm IS NOT NULL
        ), 0)
        + LEAST((
            SELECT COUNT(DISTINCT pp2.param_name)
            FROM planet_parameters pp2
            WHERE pp2.planet_id = p.planet_id
              AND pp2.is_default = true
              AND pp2.value IS NOT NULL
              AND pp2.param_name IN (
                  'radius_earth', 'mass_earth', 'period_days',
                  'eq_temperature_k', 'semi_major_axis_au'
              )
        ), 5)
    ),
    15
)"""


def instrument_tier_points(instrument_best: str | None) -> float:
    if not instrument_best:
        return 2.0
    inst = instrument_best.lower()
    if "jwst" in inst:
        return 5.0
    if "hst" in inst or "hubble" in inst:
        return 3.5
    return 2.0


def compute_data_quality_component(
    has_spectra: bool,
    instrument_best: str | None,
    core_params_known: int,
) -> float:
    """Mirror DATA_QUALITY_SQL in Python for score breakdown display."""
    spectra_pts = 5.0 if has_spectra else 0.0
    inst_pts = instrument_tier_points(instrument_best) if has_spectra else 0.0
    completeness_pts = min(float(core_params_known), 5.0)
    return min(spectra_pts + inst_pts + completeness_pts, 15.0)
