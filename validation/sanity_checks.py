"""
Solar System Sanity Checks — validate scoring logic against known planets.

Runs Earth, Venus, Mars, and Jupiter through the habitability scorer to catch
gross weighting errors. These are the cheapest possible scientific validation.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from dataclasses import dataclass
from modules.habitability_scorer import score_planet


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    value: float = 0.0


# Physical parameters for Solar System bodies
# luminosity_solar = 0.0 means log10(1.0) = 0.0 (solar luminosity)
SOLAR_SYSTEM = {
    "Earth": {
        "semi_major_axis_au": 1.0, "luminosity_solar": 0.0, "period_days": 365.25,
        "mass_solar": 1.0, "teff_best_k": 5778, "eccentricity": 0.017,
        "radius_earth": 1.0, "mass_earth": 1.0, "eq_temperature_k": 255,
        "age_gaia_gyr": 4.6, "age_nasa_gyr": None,
    },
    "Venus": {
        "semi_major_axis_au": 0.723, "luminosity_solar": 0.0, "period_days": 224.7,
        "mass_solar": 1.0, "teff_best_k": 5778, "eccentricity": 0.007,
        "radius_earth": 0.949, "mass_earth": 0.815, "eq_temperature_k": 735,
        "age_gaia_gyr": 4.6, "age_nasa_gyr": None,
    },
    "Mars": {
        "semi_major_axis_au": 1.524, "luminosity_solar": 0.0, "period_days": 687.0,
        "mass_solar": 1.0, "teff_best_k": 5778, "eccentricity": 0.093,
        "radius_earth": 0.532, "mass_earth": 0.107, "eq_temperature_k": 210,
        "age_gaia_gyr": 4.6, "age_nasa_gyr": None,
    },
    "Jupiter": {
        "semi_major_axis_au": 5.203, "luminosity_solar": 0.0, "period_days": 4333,
        "mass_solar": 1.0, "teff_best_k": 5778, "eccentricity": 0.049,
        "radius_earth": 11.21, "mass_earth": 317.8, "eq_temperature_k": 110,
        "age_gaia_gyr": 4.6, "age_nasa_gyr": None,
    },
}

# Assertions: (planet, score_key, operator, threshold, description)
ASSERTIONS = [
    ("Earth",   "similarity_score", ">=", 0.85, "Earth should have high ESI similarity"),
    ("Earth",   "safety_score",     ">=", 0.70, "Earth should score safe (G-star, low ecc, old)"),
    ("Earth",   "composite_score",  ">=", 0.75, "Earth composite should be high"),
    ("Venus",   "composite_score",  "<",  0.50, "Venus Teq=735K should crush temperature ESI"),
    ("Mars",    "similarity_score", "<",  0.80, "Mars is too small and cold for high similarity"),
    ("Jupiter", "composite_score",  "<",  0.40, "Jupiter is obviously non-habitable"),
]


def run_sanity_checks():
    """Run Solar System sanity checks. Returns list of CheckResult."""
    scores = {}
    for name, params in SOLAR_SYSTEM.items():
        row = pd.Series(params)
        scores[name] = score_planet(row)

    results = []
    for planet, key, op, threshold, desc in ASSERTIONS:
        val = scores[planet].get(key)
        if val is None:
            results.append(CheckResult(
                name=f"{planet} {key}",
                passed=False,
                message=f"Score is None — cannot evaluate '{desc}'",
            ))
            continue

        if op == ">=":
            passed = val >= threshold
        elif op == "<":
            passed = val < threshold
        else:
            passed = False

        results.append(CheckResult(
            name=f"{planet} {key}",
            passed=passed,
            value=round(val, 4),
            message=f"{val:.4f} {'>=' if op == '>=' else '<'} {threshold} - "
                    f"{'PASS' if passed else 'FAIL'} — {desc}",
        ))

    return results, scores


if __name__ == "__main__":
    results, scores = run_sanity_checks()
    print(f"\n{'='*70}")
    print(f"  Solar System Sanity Checks")
    print(f"{'='*70}")

    for name in SOLAR_SYSTEM:
        s = scores[name]
        print(f"\n  {name}:")
        print(f"    similarity = {s.get('similarity_score', 'N/A')}")
        print(f"    safety     = {s.get('safety_score', 'N/A')}")
        print(f"    composite  = {s.get('composite_score', 'N/A')}")

    print(f"\n  {'─'*60}")
    all_pass = True
    for r in results:
        icon = "[+]" if r.passed else "[-]"
        print(f"  {icon} {r.name}: {r.message}")
        if not r.passed:
            all_pass = False

    print(f"\n  Result: {'ALL PASS' if all_pass else 'SOME FAILED'}")
    print(f"{'='*70}\n")
