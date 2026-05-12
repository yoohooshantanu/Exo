"""SQL queries for the API."""
from sqlalchemy import text

PLANET_LIST = text("""
SELECT
    p.planet_name,
    s.hip_name AS hostname,
    p.discovery_method,
    p.discovery_year,
    MAX(CASE WHEN pp.param_name = 'radius_earth' THEN pp.value END) AS radius_earth,
    MAX(CASE WHEN pp.param_name = 'mass_earth' THEN pp.value END) AS mass_earth,
    MAX(CASE WHEN pp.param_name = 'period_days' THEN pp.value END) AS period_days,
    MAX(CASE WHEN pp.param_name = 'eq_temperature_k' THEN pp.value END) AS eq_temperature_k,
    MAX(CASE WHEN pp.param_name = 'semi_major_axis_au' THEN pp.value END) AS semi_major_axis_au,
    hs.composite_score,
    hs.hz_score,
    tc.cluster_name
FROM planets p
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN planet_parameters pp
    ON pp.planet_id = p.planet_id AND pp.is_default = true AND pp.valid_to IS NULL
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
LEFT JOIN (
    SELECT DISTINCT ON (planet_id) planet_id, cluster_name
    FROM taxonomy_clusters
    ORDER BY planet_id, run_at DESC
) tc ON tc.planet_id = p.planet_id
WHERE (CAST(:method AS VARCHAR) IS NULL OR p.discovery_method = CAST(:method AS VARCHAR))
  AND (CAST(:year_min AS INTEGER) IS NULL OR p.discovery_year >= CAST(:year_min AS INTEGER))
  AND (CAST(:year_max AS INTEGER) IS NULL OR p.discovery_year <= CAST(:year_max AS INTEGER))
  AND (CAST(:min_score AS REAL) IS NULL OR hs.composite_score >= CAST(:min_score AS REAL))
  AND p.status = 'confirmed'
GROUP BY p.planet_id, p.planet_name, s.hip_name,
         p.discovery_method, p.discovery_year,
         hs.composite_score, hs.hz_score, tc.cluster_name
ORDER BY hs.composite_score DESC NULLS LAST, p.planet_name
LIMIT :limit OFFSET :offset
""")

PLANET_LIST_COUNT = text("""
SELECT COUNT(DISTINCT p.planet_id)
FROM planets p
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
WHERE (CAST(:method AS VARCHAR) IS NULL OR p.discovery_method = CAST(:method AS VARCHAR))
  AND (CAST(:year_min AS INTEGER) IS NULL OR p.discovery_year >= CAST(:year_min AS INTEGER))
  AND (CAST(:year_max AS INTEGER) IS NULL OR p.discovery_year <= CAST(:year_max AS INTEGER))
  AND (CAST(:min_score AS REAL) IS NULL OR hs.composite_score >= CAST(:min_score AS REAL))
  AND p.status = 'confirmed'
""")

PLANET_DETAIL = text("""
SELECT
    p.planet_name,
    p.planet_id::text,
    s.hip_name AS hostname,
    s.star_id::text,
    p.status,
    p.discovery_method,
    p.discovery_year,
    MAX(CASE WHEN pp.param_name = 'radius_earth' THEN pp.value END) AS radius_earth,
    MAX(CASE WHEN pp.param_name = 'mass_earth' THEN pp.value END) AS mass_earth,
    MAX(CASE WHEN pp.param_name = 'period_days' THEN pp.value END) AS period_days,
    MAX(CASE WHEN pp.param_name = 'eq_temperature_k' THEN pp.value END) AS eq_temperature_k,
    MAX(CASE WHEN pp.param_name = 'semi_major_axis_au' THEN pp.value END) AS semi_major_axis_au,
    MAX(CASE WHEN pp.param_name = 'eccentricity' THEN pp.value END) AS eccentricity,
    MAX(CASE WHEN pp.param_name = 'density_earth' THEN pp.value END) AS density_earth,
    hs.composite_score,
    hs.hz_score,
    hs.teq_score,
    hs.radius_esi_score,
    hs.mass_esi_score,
    hs.tidal_lock_score,
    hs.flare_score,
    hs.eccentricity_score,
    hs.age_score,
    COALESCE(
        (hs.input_snapshot->>'sim_score')::float,
        CASE WHEN hs.composite_score IS NOT NULL AND hs.flare_score IS NOT NULL
             THEN (hs.composite_score - 0.30 * COALESCE(
                 (COALESCE(hs.flare_score, 0) * 0.45 + COALESCE(hs.tidal_lock_score, 0) * 0.30 +
                  COALESCE(hs.eccentricity_score, 0) * 0.15 + COALESCE(hs.age_score, 0) * 0.10), 0
             )) / 0.70
             ELSE NULL
        END
    ) AS similarity_score,
    COALESCE(
        (hs.input_snapshot->>'risk_score')::float,
        CASE WHEN hs.flare_score IS NOT NULL
             THEN COALESCE(hs.flare_score, 0) * 0.45 + COALESCE(hs.tidal_lock_score, 0) * 0.30 +
                  COALESCE(hs.eccentricity_score, 0) * 0.15 + COALESCE(hs.age_score, 0) * 0.10
             ELSE NULL
        END
    ) AS risk_score,
    tc.cluster_label,
    tc.cluster_name,
    tc.distance_to_centroid
FROM planets p
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN planet_parameters pp
    ON pp.planet_id = p.planet_id AND pp.is_default = true AND pp.valid_to IS NULL
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
LEFT JOIN (
    SELECT DISTINCT ON (planet_id) planet_id, cluster_label, cluster_name, distance_to_centroid
    FROM taxonomy_clusters
    ORDER BY planet_id, run_at DESC
) tc ON tc.planet_id = p.planet_id
WHERE p.planet_name = :planet_name
GROUP BY p.planet_id, s.hip_name, s.star_id,
         hs.composite_score, hs.hz_score, hs.teq_score,
         hs.radius_esi_score, hs.mass_esi_score,
         hs.tidal_lock_score, hs.flare_score,
         hs.eccentricity_score, hs.age_score, hs.input_snapshot,
         tc.cluster_label, tc.cluster_name, tc.distance_to_centroid
""")

PLANET_ANOMALIES = text("""
SELECT anomaly_type, deviation_sigma
FROM anomaly_flags af
JOIN planets p ON af.planet_id = p.planet_id
WHERE p.planet_name = :planet_name
ORDER BY af.deviation_sigma DESC
""")

PLANET_BIOSIGS = text("""
SELECT md.molecule, md.detection_sigma, md.wavelength_um, md.hitran_match_count,
       md.abiotic_ruled_out, md.instrument, md.facility
FROM molecule_detections md
JOIN planets p ON md.planet_id = p.planet_id
WHERE p.planet_name = :planet_name
ORDER BY md.detection_sigma DESC
""")

PLANET_GAPS = text("""
SELECT op.predicted_period_days, op.stability_confidence, op.model_version
FROM orbital_predictions op
JOIN stars s ON op.star_id = s.star_id
JOIN planets p ON p.star_id = s.star_id
WHERE p.planet_name = :planet_name AND op.model_version = :pred_version
ORDER BY op.stability_confidence DESC
""")

STAR_LIST = text("""
SELECT
    s.star_id::text,
    s.hip_name,
    s.ra,
    s.dec,
    s.distance_pc,
    COUNT(p.planet_id) AS planet_count
FROM stars s
LEFT JOIN planets p ON p.star_id = s.star_id AND p.status = 'confirmed'
GROUP BY s.star_id, s.hip_name, s.ra, s.dec, s.distance_pc
ORDER BY s.distance_pc NULLS LAST
LIMIT :limit OFFSET :offset
""")

STAR_LIST_COUNT = text("""
SELECT COUNT(*) FROM stars
""")

SPECTRA_FOR_PLANET = text("""
SELECT
    a.spec_id,
    a.instrument,
    a.facility,
    a.obs_type
FROM atmospheric_spectra a
JOIN planets p ON a.planet_id = p.planet_id
WHERE p.planet_name = :planet_name AND a.depth_ppm IS NOT NULL
GROUP BY a.spec_id, a.instrument, a.facility, a.obs_type
ORDER BY a.spec_id
""")

SPECTRUM_POINTS = text("""
SELECT wavelength_um, depth_ppm, depth_err_upper, depth_err_lower
FROM atmospheric_spectra
WHERE spec_id = :spec_id AND depth_ppm IS NOT NULL
ORDER BY wavelength_um
""")

SPECTRUM_DETECTIONS = text("""
SELECT molecule, detection_sigma, wavelength_um, hitran_match_count,
       abiotic_ruled_out, instrument, facility
FROM molecule_detections md
JOIN planets p ON md.planet_id = p.planet_id
WHERE p.planet_name = :planet_name
ORDER BY md.detection_sigma DESC
""")

HITRAN_LINES_FOR_PLANET = text("""
SELECT h.wavelength_um, h.intensity, h.molecule
FROM hitran_lines h
JOIN molecule_detections md ON h.molecule = md.molecule
JOIN planets p ON md.planet_id = p.planet_id
WHERE p.planet_name = :planet_name
ORDER BY h.intensity DESC LIMIT 500
""")

RANKINGS_TOP_HABITABLE = text("""
SELECT
    p.planet_name,
    s.hip_name AS hostname,
    hs.composite_score,
    'Top Habitable' AS category,
    tc.cluster_name AS detail
FROM habitability_scores hs
JOIN planets p ON hs.planet_id = p.planet_id
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN (
    SELECT DISTINCT ON (planet_id) planet_id, cluster_name
    FROM taxonomy_clusters ORDER BY planet_id, run_at DESC
) tc ON tc.planet_id = p.planet_id
WHERE hs.model_version = :score_version AND hs.composite_score IS NOT NULL
ORDER BY hs.composite_score DESC
LIMIT :limit
""")

RANKINGS_ANOMALOUS = text("""
SELECT
    p.planet_name,
    s.hip_name AS hostname,
    hs.composite_score,
    'Anomalous' AS category,
    af.anomaly_type AS detail
FROM anomaly_flags af
JOIN planets p ON af.planet_id = p.planet_id
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
WHERE af.deviation_sigma >= 3.0
ORDER BY hs.composite_score DESC, af.deviation_sigma DESC
LIMIT :limit
""")

RANKINGS_NOVEL = text("""
SELECT
    p.planet_name,
    s.hip_name AS hostname,
    hs.composite_score,
    'Novel Taxonomy' AS category,
    tc.cluster_name AS detail
FROM (
    SELECT DISTINCT ON (planet_id) planet_id, cluster_name
    FROM taxonomy_clusters
    WHERE cluster_label = -1 OR cluster_name NOT IN (
        'Hot Giant', 'Warm Giant', 'Cold Giant',
        'Hot Sub-Neptune', 'Warm Sub-Neptune',
        'Hot Rocky', 'Temperate Rocky', 'Neptune-class'
    )
    ORDER BY planet_id, run_at DESC
) tc
JOIN planets p ON tc.planet_id = p.planet_id
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
ORDER BY hs.composite_score DESC NULLS LAST
LIMIT :limit
""")

RANKINGS_BIOSIGNATURES = text("""
SELECT
    p.planet_name,
    s.hip_name AS hostname,
    hs.composite_score,
    'Biosignature' AS category,
    STRING_AGG(DISTINCT md.molecule, ', ') AS detail
FROM molecule_detections md
JOIN planets p ON md.planet_id = p.planet_id
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
WHERE md.detection_sigma >= 2.0
GROUP BY p.planet_name, s.hip_name, hs.composite_score
ORDER BY MAX(md.detection_sigma) DESC
LIMIT :limit
""")

RANKINGS_GAPS = text("""
SELECT
    p2.planet_name,
    s.hip_name AS hostname,
    hs.composite_score,
    'Gap System' AS category,
    op.predicted_period_days::text || ' d' AS detail
FROM (
    SELECT DISTINCT ON (star_id) star_id, predicted_period_days, stability_confidence
    FROM orbital_predictions
    WHERE model_version = :pred_version
    ORDER BY star_id, stability_confidence DESC
) op
JOIN stars s ON op.star_id = s.star_id
JOIN planets p2 ON p2.star_id = s.star_id
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p2.planet_id AND hs.model_version = :score_version
ORDER BY op.stability_confidence DESC, p2.planet_name
LIMIT :limit
""")

ALERTS = text("""
(
    SELECT
        'Anomaly + Habitable' AS alert_type,
        p.planet_name,
        s.hip_name AS hostname,
        af.anomaly_type AS detail,
        hs.composite_score AS score,
        CASE WHEN hs.composite_score > 0.5 THEN 'high' ELSE 'medium' END AS severity,
        af.flagged_at AS created_at
    FROM anomaly_flags af
    JOIN planets p ON af.planet_id = p.planet_id
    JOIN stars s ON p.star_id = s.star_id
    LEFT JOIN habitability_scores hs
        ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
    WHERE af.deviation_sigma >= 3.0
)
UNION ALL
(
    SELECT
        'Novel Taxonomy' AS alert_type,
        p.planet_name,
        s.hip_name AS hostname,
        tc.cluster_name AS detail,
        hs.composite_score AS score,
        'medium' AS severity,
        tc.run_at AS created_at
    FROM (
        SELECT DISTINCT ON (planet_id) planet_id, cluster_name, run_at
        FROM taxonomy_clusters
        WHERE cluster_label = -1 OR cluster_name NOT IN (
            'Hot Giant', 'Warm Giant', 'Cold Giant',
            'Hot Sub-Neptune', 'Warm Sub-Neptune',
            'Hot Rocky', 'Temperate Rocky', 'Neptune-class'
        )
        ORDER BY planet_id, run_at DESC
    ) tc
    JOIN planets p ON tc.planet_id = p.planet_id
    JOIN stars s ON p.star_id = s.star_id
    LEFT JOIN habitability_scores hs
        ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
)
UNION ALL
(
    SELECT
        'Gap + Biosig' AS alert_type,
        p2.planet_name,
        s.hip_name AS hostname,
        md.molecule AS detail,
        hs.composite_score AS score,
        'high' AS severity,
        md.flagged_at AS created_at
    FROM orbital_predictions op
    JOIN stars s ON op.star_id = s.star_id
    JOIN planets p2 ON p2.star_id = s.star_id
    JOIN molecule_detections md ON md.planet_id = p2.planet_id
    LEFT JOIN habitability_scores hs
        ON hs.planet_id = p2.planet_id AND hs.model_version = :score_version
    WHERE md.detection_sigma >= 2.0 AND op.model_version = :pred_version
)
ORDER BY created_at DESC
LIMIT :limit
""")

PLATFORM_STATS = text("""
SELECT
    (SELECT COUNT(*) FROM stars) AS stars,
    (SELECT COUNT(*) FROM planets WHERE status = 'confirmed') AS planets,
    (SELECT COUNT(*) FROM habitability_scores WHERE model_version = :score_version) AS habitability_scores,
    (SELECT COUNT(*) FROM orbital_predictions WHERE model_version = :pred_version) AS orbital_predictions,
    (SELECT COUNT(*) FROM molecule_detections) AS molecule_detections,
    (SELECT COUNT(*) FROM atmospheric_spectra) AS atmospheric_spectra,
    (SELECT COUNT(*) FROM anomaly_flags) AS anomaly_flags,
    (SELECT COUNT(DISTINCT planet_id) FROM taxonomy_clusters) AS taxonomy_clusters
""")


# ── Star Positions (3D Map) ─────────────────────────────────────────────────

STAR_POSITIONS = text("""
SELECT
    s.star_id::text AS id,
    s.hip_name,
    s.ra,
    s.dec,
    s.distance_pc,
    s.spectral_type,
    MAX(CASE WHEN sp.param_name = 'teff_best_k' THEN sp.value END) AS teff,
    MAX(CASE WHEN sp.param_name = 'radius_solar' THEN sp.value END) AS radius_solar,
    COUNT(DISTINCT p.planet_id) AS n_planets,
    COALESCE(MAX(hs.composite_score), 0) AS hab_score_max,
    EXISTS(
        SELECT 1 FROM orbital_predictions op WHERE op.star_id = s.star_id
    ) AS has_prediction,
    EXISTS(
        SELECT 1 FROM molecule_detections md
        JOIN planets p2 ON md.planet_id = p2.planet_id
        WHERE p2.star_id = s.star_id
    ) AS has_biosig
FROM stars s
LEFT JOIN star_parameters sp
    ON sp.star_id = s.star_id
    AND sp.param_name IN ('teff_best_k', 'radius_solar')
    AND sp.is_default = true
    AND sp.valid_to IS NULL
LEFT JOIN planets p
    ON p.star_id = s.star_id AND p.status = 'confirmed'
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
GROUP BY s.star_id, s.hip_name, s.ra, s.dec, s.distance_pc, s.spectral_type
ORDER BY s.distance_pc NULLS LAST
LIMIT :limit
""")


# ── Priority Target (Dashboard Hero) ────────────────────────────────────────

PRIORITY_TARGET = text("""
SELECT
    p.planet_name,
    s.hip_name AS hostname,
    hs.composite_score,
    hs.hz_score,
    tc.cluster_name,
    MAX(CASE WHEN pp.param_name = 'radius_earth' THEN pp.value END) AS radius_earth,
    MAX(CASE WHEN pp.param_name = 'mass_earth' THEN pp.value END) AS mass_earth,
    MAX(CASE WHEN pp.param_name = 'eq_temperature_k' THEN pp.value END) AS eq_temperature_k,
    (SELECT COUNT(*) FROM molecule_detections md WHERE md.planet_id = p.planet_id) AS biosig_count,
    (SELECT string_agg(DISTINCT md.molecule, ', ')
     FROM molecule_detections md WHERE md.planet_id = p.planet_id) AS molecules_detected,
    (SELECT COUNT(*) FROM anomaly_flags af WHERE af.planet_id = p.planet_id) AS anomaly_count
FROM habitability_scores hs
JOIN planets p ON hs.planet_id = p.planet_id
JOIN stars s ON p.star_id = s.star_id
LEFT JOIN planet_parameters pp
    ON pp.planet_id = p.planet_id AND pp.is_default = true AND pp.valid_to IS NULL
LEFT JOIN (
    SELECT DISTINCT ON (planet_id) planet_id, cluster_name
    FROM taxonomy_clusters ORDER BY planet_id, run_at DESC
) tc ON tc.planet_id = p.planet_id
WHERE hs.model_version = :score_version AND hs.composite_score IS NOT NULL
GROUP BY p.planet_id, p.planet_name, s.hip_name,
         hs.composite_score, hs.hz_score, tc.cluster_name
ORDER BY hs.composite_score DESC
LIMIT 1
""")


# ── Star System Detail (Zoom View) ──────────────────────────────────────────

STAR_SYSTEM = text("""
SELECT
    s.star_id::text,
    s.hip_name,
    s.ra,
    s.dec,
    s.distance_pc,
    MAX(CASE WHEN sp.param_name = 'teff_best_k' THEN sp.value END) AS teff,
    MAX(CASE WHEN sp.param_name = 'radius_solar' THEN sp.value END) AS radius_solar,
    MAX(CASE WHEN sp.param_name = 'mass_solar' THEN sp.value END) AS mass_solar
FROM stars s
LEFT JOIN star_parameters sp
    ON sp.star_id = s.star_id AND sp.is_default = true AND sp.valid_to IS NULL
WHERE s.star_id = CAST(:star_id AS uuid)
GROUP BY s.star_id, s.hip_name, s.ra, s.dec, s.distance_pc
""")

STAR_SYSTEM_PLANETS = text("""
SELECT
    p.planet_name,
    MAX(CASE WHEN pp.param_name = 'radius_earth' THEN pp.value END) AS radius_earth,
    MAX(CASE WHEN pp.param_name = 'mass_earth' THEN pp.value END) AS mass_earth,
    MAX(CASE WHEN pp.param_name = 'semi_major_axis_au' THEN pp.value END) AS semi_major_axis_au,
    MAX(CASE WHEN pp.param_name = 'period_days' THEN pp.value END) AS period_days,
    MAX(CASE WHEN pp.param_name = 'eccentricity' THEN pp.value END) AS eccentricity,
    MAX(CASE WHEN pp.param_name = 'eq_temperature_k' THEN pp.value END) AS eq_temperature_k,
    hs.composite_score,
    tc.cluster_name
FROM planets p
LEFT JOIN planet_parameters pp
    ON pp.planet_id = p.planet_id AND pp.is_default = true AND pp.valid_to IS NULL
LEFT JOIN habitability_scores hs
    ON hs.planet_id = p.planet_id AND hs.model_version = :score_version
LEFT JOIN (
    SELECT DISTINCT ON (planet_id) planet_id, cluster_name
    FROM taxonomy_clusters ORDER BY planet_id, run_at DESC
) tc ON tc.planet_id = p.planet_id
WHERE p.star_id = CAST(:star_id AS uuid) AND p.status = 'confirmed'
GROUP BY p.planet_id, p.planet_name, hs.composite_score, tc.cluster_name
ORDER BY semi_major_axis_au NULLS LAST
""")
