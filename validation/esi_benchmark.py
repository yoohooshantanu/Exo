"""
ESI Benchmark — compare our Earth Similarity Index against published UPR values.

Validates that compute_similarity_esi() produces results consistent with the
University of Puerto Rico's Habitable Exoplanets Catalog (Méndez et al.).

Pass criterion: Spearman rho >= 0.80 and documented mean delta against published ESI for 20 reference planets.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scipy import stats
from modules.habitability_scorer import compute_similarity_esi


# Published ESI values from UPR Habitable Exoplanets Catalog (phl.upr.edu)
# Snapshot: Dec 2023
# Input parameters: radius (R_Earth), mass (M_Earth), Teq (K)
REFERENCE_PLANETS = [
    {"name": "TRAPPIST-1 e",       "radius": 0.92,  "mass": 0.69,  "teq": 251, "published_esi": 0.85},
    {"name": "TRAPPIST-1 d",       "radius": 0.77,  "mass": 0.39,  "teq": 288, "published_esi": 0.90},
    {"name": "TRAPPIST-1 f",       "radius": 1.04,  "mass": 0.68,  "teq": 219, "published_esi": 0.68},
    {"name": "TRAPPIST-1 g",       "radius": 1.13,  "mass": 1.34,  "teq": 199, "published_esi": 0.58},
    {"name": "Proxima Centauri b", "radius": 1.03,  "mass": 1.27,  "teq": 234, "published_esi": 0.87},
    {"name": "Kepler-442 b",       "radius": 1.34,  "mass": 2.36,  "teq": 233, "published_esi": 0.84},
    {"name": "Kepler-452 b",       "radius": 1.63,  "mass": 3.29,  "teq": 265, "published_esi": 0.83},
    {"name": "Ross 128 b",         "radius": 1.03,  "mass": 1.40,  "teq": 256, "published_esi": 0.86},
    {"name": "LHS 1140 b",         "radius": 1.43,  "mass": 5.60,  "teq": 235, "published_esi": 0.74},
    {"name": "K2-18 b",            "radius": 2.61,  "mass": 8.63,  "teq": 284, "published_esi": 0.73},
    {"name": "TOI-700 d",          "radius": 1.19,  "mass": 1.72,  "teq": 269, "published_esi": 0.93},
    {"name": "Kepler-1649 c",      "radius": 1.06,  "mass": 1.20,  "teq": 234, "published_esi": 0.92},
    {"name": "Teegarden's Star b", "radius": 1.02,  "mass": 1.05,  "teq": 264, "published_esi": 0.95},
    {"name": "GJ 1002 b",          "radius": 1.03,  "mass": 1.08,  "teq": 231, "published_esi": 0.88},
    {"name": "GJ 1061 d",          "radius": 1.03,  "mass": 1.64,  "teq": 218, "published_esi": 0.82},
    {"name": "Kepler-62 f",        "radius": 1.41,  "mass": 2.80,  "teq": 208, "published_esi": 0.67},
    {"name": "Kepler-186 f",       "radius": 1.17,  "mass": 1.71,  "teq": 188, "published_esi": 0.61},
    {"name": "Wolf 1061 c",        "radius": 1.66,  "mass": 3.41,  "teq": 271, "published_esi": 0.76},
    {"name": "GJ 667C c",          "radius": 1.54,  "mass": 3.80,  "teq": 277, "published_esi": 0.84},
    {"name": "HD 40307 g",         "radius": 1.56,  "mass": 7.09,  "teq": 226, "published_esi": 0.74},
]


def run_esi_benchmark():
    """Run ESI benchmark and return structured results."""
    our_values = []
    published_values = []
    per_planet = []

    for p in REFERENCE_PLANETS:
        our_esi = compute_similarity_esi(p["radius"], p["mass"], p["teq"])
        if our_esi is None:
            per_planet.append({
                "name": p["name"], "our_esi": None,
                "published_esi": p["published_esi"], "delta": None,
            })
            continue

        our_values.append(our_esi)
        published_values.append(p["published_esi"])
        per_planet.append({
            "name": p["name"],
            "our_esi": round(our_esi, 4),
            "published_esi": p["published_esi"],
            "delta": round(our_esi - p["published_esi"], 4),
        })

    if len(our_values) < 5:
        return {
            "passed": False,
            "pearson_r": None,
            "spearman_rho": None,
            "n_compared": len(our_values),
            "per_planet": per_planet,
            "message": f"Only {len(our_values)} planets computed — insufficient for correlation",
        }

    pearson_r, pearson_p = stats.pearsonr(our_values, published_values)
    spearman_rho, spearman_p = stats.spearmanr(our_values, published_values)

    mean_delta = sum(abs(p["delta"]) for p in per_planet if p["delta"] is not None) / len(our_values)
    max_delta = max(abs(p["delta"]) for p in per_planet if p["delta"] is not None)

    # We expect a systematic offset due to using Teq vs UPR's Ts (greenhouse),
    # so we assert on rank correlation (Spearman rho >= 0.80) rather than zero delta.
    passed = spearman_rho >= 0.80

    return {
        "passed": passed,
        "pearson_r": round(pearson_r, 4),
        "pearson_p": round(pearson_p, 6),
        "spearman_rho": round(spearman_rho, 4),
        "spearman_p": round(spearman_p, 6),
        "max_delta": round(max_delta, 4),
        "mean_delta": round(mean_delta, 4),
        "n_compared": len(our_values),
        "per_planet": per_planet,
        "message": f"Spearman rho = {spearman_rho:.4f}, mean delta = {mean_delta:.4f} ({'PASS' if passed else 'FAIL'})",
    }


if __name__ == "__main__":
    result = run_esi_benchmark()
    print(f"\n{'='*70}")
    print(f"  ESI Benchmark — {result['n_compared']} planets compared")
    print(f"{'='*70}")
    print(f"\n  {'Planet':<22s} {'Ours':>8s} {'Published':>10s} {'Delta':>8s}")
    print(f"  {'-'*50}")
    for p in result["per_planet"]:
        ours = f"{p['our_esi']:.4f}" if p["our_esi"] is not None else "N/A"
        delta = f"{p['delta']:+.4f}" if p["delta"] is not None else "N/A"
        print(f"  {p['name']:<22s} {ours:>8s} {p['published_esi']:>10.4f} {delta:>8s}")
    print(f"\n  Pearson r  = {result['pearson_r']}")
    print(f"  Spearman rho = {result['spearman_rho']}")
    print(f"  Result: {result['message']}")
    print(f"{'='*70}\n")
