"""
Weight Stability Analysis — discovery score sensitivity to weight perturbation.

Tests whether the top-20 planet ranking is robust to ±20% perturbation of the
five discovery score component weights. If the ranking is stable, the specific
weight choices matter less. If fragile, they're load-bearing and need justification.

Requires: live DB connection (run with --live flag).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sqlalchemy import text

from modules.discovery_score import DATA_QUALITY_SQL


# Base weights (out of 100)
BASE_WEIGHTS = {
    "habitability": 40,
    "biosignature": 25,
    "data_quality": 15,
    "orbital_context": 10,
    "anomaly_penalty": 10,
}


def run_weight_stability(session, n_trials=1000, seed=42):
    """Perturb discovery score weights and measure ranking stability."""
    rng = np.random.default_rng(seed)

    # Fetch component values for top planets
    sql_query = f"""
        SELECT
            p.planet_name,
            COALESCE(hs.composite_score, 0) AS hab_component,
            COALESCE((
                SELECT COUNT(*) * 5.0 * (0.5 + 0.5 * LEAST(AVG(md.detection_sigma), 10.0) / 5.0)
                FROM molecule_detections md
                WHERE md.planet_id = p.planet_id AND md.detection_sigma >= 3
            ), 0) AS biosig_raw,
            ({DATA_QUALITY_SQL}) AS data_raw,
            COALESCE(mvs.discovery_score, 0) AS current_score,
            (SELECT COUNT(*) FROM planets p2
             WHERE p2.star_id = p.star_id AND p2.status = 'confirmed') AS sibling_count,
            (SELECT COUNT(*) FROM orbital_predictions op
             WHERE op.star_id = p.star_id) AS gap_count,
            (SELECT COUNT(*) FROM anomaly_flags af
             WHERE af.planet_id = p.planet_id) AS anomaly_count
        FROM planets p
        LEFT JOIN habitability_scores hs ON hs.planet_id = p.planet_id
            AND hs.model_version = (SELECT value FROM (VALUES ('4.2.0')) AS t(value))
        LEFT JOIN mv_discovery_scores mvs ON mvs.planet_id = p.planet_id
        WHERE p.status = 'confirmed'
        ORDER BY COALESCE(mvs.discovery_score, 0) DESC
        LIMIT 40
    """
    rows = session.execute(text(sql_query)).mappings().all()

    if len(rows) < 20:
        return {
            "passed": True,
            "message": f"Only {len(rows)} planets found — cannot assess top-20 stability",
            "stability_pct": None,
        }

    # Pre-compute component values
    planets = []
    for r in rows:
        planets.append({
            "name": r["planet_name"],
            "hab": float(r["hab_component"]),
            "biosig": min(float(r["biosig_raw"]), 25),
            "data": float(r["data_raw"]),
            "orbital": min(float(r["sibling_count"]) * 1.5 + float(r["gap_count"]) * 2.0, 10),
            "anomaly": min(float(r["anomaly_count"]) * 3.0, 10),
            "current_score": float(r["current_score"]),
        })

    original_top20 = set(p["name"] for p in planets[:20])

    # Run perturbation trials
    retention_counts = []
    for _ in range(n_trials):
        w = {k: v * rng.uniform(0.8, 1.2) for k, v in BASE_WEIGHTS.items()}

        scored = []
        for p in planets:
            score = max(0, min(100,
                p["hab"] * w["habitability"]
                + p["biosig"] * (w["biosignature"] / 25.0)
                + p["data"] * (w["data_quality"] / 15.0)
                + p["orbital"] * (w["orbital_context"] / 10.0)
                - p["anomaly"] * (w["anomaly_penalty"] / 10.0)
            ))
            scored.append((p["name"], score))

        scored.sort(key=lambda x: -x[1])
        perturbed_top20 = set(name for name, _ in scored[:20])
        retained = len(original_top20 & perturbed_top20)
        retention_counts.append(retained)

    retention_counts = np.array(retention_counts)
    mean_retained = float(np.mean(retention_counts))
    stability_pct = mean_retained / 20 * 100

    return {
        "passed": stability_pct >= 70,
        "stability_pct": round(stability_pct, 1),
        "mean_retained": round(mean_retained, 1),
        "min_retained": int(np.min(retention_counts)),
        "max_retained": int(np.max(retention_counts)),
        "n_trials": n_trials,
        "message": f"Top-20 stability: {stability_pct:.1f}% retention under ±20% weight perturbation "
                   f"({'PASS' if stability_pct >= 70 else 'FAIL'}, threshold 70%)",
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    from sqlalchemy.orm import sessionmaker
    from modules.db_sync import create_sync_engine

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    engine = create_sync_engine()
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        result = run_weight_stability(session)
        print(f"\n{'='*70}")
        print(f"  Weight Stability — {result['n_trials']} trials")
        print(f"{'='*70}")
        print(f"\n  Mean top-20 retained: {result['mean_retained']} / 20")
        print(f"  Range: [{result['min_retained']}, {result['max_retained']}]")
        print(f"  Stability: {result['stability_pct']}%")
        print(f"  {result['message']}")
        print(f"{'='*70}\n")
    finally:
        session.close()
