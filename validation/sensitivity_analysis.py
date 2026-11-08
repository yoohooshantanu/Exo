"""
Sensitivity Analysis — Monte Carlo perturbation of habitability scores.

Samples fundamental observables (radius, mass) from their measurement
uncertainties, re-derives dependent quantities each draw, and measures
how much composite scores shift. Flags planets where the IQR spans more
than one tier boundary (score uncertainty > 0.15).

Key design choices:
  - Sample FUNDAMENTALS (radius, mass), not derived quantities (density, v_esc)
  - For imputed parameters (no stored uncertainty), use ±30% as wide prior
  - Epistemic uncertainty (missing data) is flagged, not MC-sampled

Requires: live DB connection (run with --live flag).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from sqlalchemy import text
from modules.habitability_scorer import score_planet


def run_sensitivity_analysis(session, n_planets=50, n_draws=200, seed=42):
    """Run MC sensitivity analysis on top-scoring planets."""
    rng = np.random.default_rng(seed)

    # Fetch top planets by composite score
    rows = session.execute(text("""
        SELECT p.planet_name, p.planet_id,
            hs.composite_score,
            MAX(CASE WHEN pp.param_name='radius_earth' THEN pp.value END) AS radius_earth,
            MAX(CASE WHEN pp.param_name='radius_earth' THEN pp.uncertainty_upper END) AS radius_err,
            MAX(CASE WHEN pp.param_name='mass_earth' THEN pp.value END) AS mass_earth,
            MAX(CASE WHEN pp.param_name='mass_earth' THEN pp.uncertainty_upper END) AS mass_err,
            MAX(CASE WHEN pp.param_name='period_days' THEN pp.value END) AS period_days,
            MAX(CASE WHEN pp.param_name='eq_temperature_k' THEN pp.value END) AS eq_temperature_k,
            MAX(CASE WHEN pp.param_name='semi_major_axis_au' THEN pp.value END) AS semi_major_axis_au,
            MAX(CASE WHEN pp.param_name='eccentricity' THEN pp.value END) AS eccentricity,
            MAX(CASE WHEN sp.param_name='teff_best_k' THEN sp.value END) AS teff_best_k,
            MAX(CASE WHEN sp.param_name='luminosity_solar' THEN sp.value END) AS luminosity_solar,
            MAX(CASE WHEN sp.param_name='mass_solar' THEN sp.value END) AS mass_solar,
            MAX(CASE WHEN sp.param_name='age_gaia_gyr' THEN sp.value END) AS age_gaia_gyr,
            MAX(CASE WHEN sp.param_name='age_nasa_gyr' THEN sp.value END) AS age_nasa_gyr
        FROM planets p
        JOIN habitability_scores hs ON hs.planet_id = p.planet_id
        JOIN stars s ON p.star_id = s.star_id
        LEFT JOIN planet_parameters pp ON pp.planet_id = p.planet_id
            AND pp.is_default = true AND pp.valid_to IS NULL
        LEFT JOIN star_parameters sp ON sp.star_id = s.star_id
            AND sp.is_default = true AND sp.valid_to IS NULL
        WHERE hs.composite_score IS NOT NULL
        GROUP BY p.planet_name, p.planet_id, hs.composite_score
        ORDER BY hs.composite_score DESC
        LIMIT :n
    """), {"n": n_planets}).mappings().all()

    results = []
    for row in rows:
        base_radius = row["radius_earth"]
        base_mass = row["mass_earth"]
        radius_err = row["radius_err"]
        mass_err = row["mass_err"]

        if base_radius is None:
            continue

        # Determine uncertainty: stored measurement or 30% fallback for imputed
        r_sigma = radius_err if radius_err and radius_err > 0 else abs(base_radius * 0.30)
        m_sigma = (mass_err if mass_err and mass_err > 0 else abs(base_mass * 0.30)) if base_mass else None

        draws = []
        for _ in range(n_draws):
            # Sample fundamentals
            r_draw = max(0.01, rng.normal(base_radius, r_sigma))
            m_draw = max(0.01, rng.normal(base_mass, m_sigma)) if base_mass and m_sigma else base_mass

            # Build perturbed row (keep everything else at point value)
            perturbed = pd.Series({
                "semi_major_axis_au": row["semi_major_axis_au"],
                "luminosity_solar": row["luminosity_solar"],
                "period_days": row["period_days"],
                "mass_solar": row["mass_solar"],
                "teff_best_k": row["teff_best_k"],
                "eccentricity": row["eccentricity"],
                "radius_earth": r_draw,
                "mass_earth": m_draw,
                "eq_temperature_k": row["eq_temperature_k"],
                "age_gaia_gyr": row["age_gaia_gyr"],
                "age_nasa_gyr": row["age_nasa_gyr"],
            })
            result = score_planet(perturbed)
            if result["composite_score"] is not None:
                draws.append(result["composite_score"])

        if len(draws) < 10:
            continue

        draws = np.array(draws)
        q5, q25, median, q75, q95 = np.percentile(draws, [5, 25, 50, 75, 95])
        iqr = q75 - q25

        results.append({
            "planet_name": row["planet_name"],
            "point_estimate": round(row["composite_score"], 4),
            "mc_median": round(median, 4),
            "mc_iqr": round(iqr, 4),
            "mc_5th": round(q5, 4),
            "mc_95th": round(q95, 4),
            "n_valid_draws": len(draws),
            "radius_source": "measured" if radius_err and radius_err > 0 else "imputed (±30%)",
            "mass_source": "measured" if mass_err and mass_err > 0 else "imputed (±30%)",
            "tier_unstable": iqr > 0.15,
        })

    unstable = [r for r in results if r["tier_unstable"]]
    return {
        "results": results,
        "n_analyzed": len(results),
        "n_tier_unstable": len(unstable),
        "unstable_planets": [r["planet_name"] for r in unstable],
        "message": f"{len(results)} planets analyzed, {len(unstable)} have IQR > 0.15 (tier-unstable)",
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    from sqlalchemy.orm import sessionmaker
    from db_sync import create_sync_engine

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    engine = create_sync_engine()
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        result = run_sensitivity_analysis(session, n_planets=20, n_draws=100)
        print(f"\n{'='*70}")
        print(f"  Sensitivity Analysis — {result['n_analyzed']} planets")
        print(f"{'='*70}")
        print(f"\n  {'Planet':<25s} {'Point':>7s} {'Median':>7s} {'IQR':>7s} {'5th':>7s} {'95th':>7s} {'Flag':>6s}")
        print(f"  {'─'*62}")
        for r in result["results"]:
            flag = " ⚠" if r["tier_unstable"] else ""
            print(f"  {r['planet_name']:<25s} {r['point_estimate']:>7.4f} {r['mc_median']:>7.4f} "
                  f"{r['mc_iqr']:>7.4f} {r['mc_5th']:>7.4f} {r['mc_95th']:>7.4f}{flag}")
        print(f"\n  {result['message']}")
        print(f"{'='*70}\n")
    finally:
        session.close()
