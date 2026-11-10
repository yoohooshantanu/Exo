"""
Record empirical scientific validation run into the database.
All four tracks are dynamically calculated and verified.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
import uuid

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
_MODULES_DIR = str(Path(__file__).resolve().parent.parent / "modules")
for _p in [_PROJECT_ROOT, _MODULES_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy.orm import sessionmaker
from db_sync import create_sync_engine
from sqlalchemy import text

from validation.esi_benchmark import run_esi_benchmark
from validation.sanity_checks import run_sanity_checks
from validation.jwst_allocation_validation import compute_jwst_validation_metrics
from modules.config import HABITABILITY_MODEL_VERSION, ORBITAL_MODEL_VERSION, BIOSIG_MODEL_VERSION

def record_empirical_run():
    engine = create_sync_engine()
    Session = sessionmaker(bind=engine)
    session = Session()

    t_start = datetime.now(timezone.utc)
    print("Executing ESI benchmark...")
    esi = run_esi_benchmark()

    print("Executing Solar System sanity checks...")
    sanity_results, sanity_scores = run_sanity_checks()

    print("Executing JWST allocation logistic regression...")
    jwst_metrics = compute_jwst_validation_metrics(engine)

    t_end = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())

    pearson_passed = bool(float(esi["pearson_r"]) >= 0.70)
    spearman_passed = bool(float(esi["spearman_rho"]) >= 0.80)
    sanity_all_passed = all(r.passed for r in sanity_results)
    jwst_passed = bool(jwst_metrics["passed"])
    purity_passed = bool(jwst_metrics["triage_passed"])

    # Solar System Planet Controls: derive statuses before computing overall run status
    earth_c = sanity_scores.get("Earth", {}).get("composite_score", 0.0)
    mars_c = sanity_scores.get("Mars", {}).get("composite_score", 0.0)
    venus_c = sanity_scores.get("Venus", {}).get("composite_score", 0.0)
    jupiter_c = sanity_scores.get("Jupiter", {}).get("composite_score", 0.0)
    # Strictly descending monotonic separation (Earth > Mars > Venus > Jupiter)
    monotonic_passed = bool(earth_c > mars_c > venus_c > jupiter_c)

    planet_statuses = {}
    for name, s in sanity_scores.items():
        comp_val = s.get("composite_score") or 0.0
        sim_val = s.get("similarity_score") or 0.0
        planet_assertions = [r for r in sanity_results if r.name.startswith(name)]
        all_planet_assertions_passed = len(planet_assertions) > 0 and all(r.passed for r in planet_assertions)

        planet_valid = all_planet_assertions_passed and monotonic_passed
        if name == "Earth" and (comp_val < 0.75 or sim_val < 0.85):
            planet_valid = False
        elif name == "Venus" and comp_val >= 0.50:
            planet_valid = False
        elif name == "Mars" and sim_val >= 0.80:
            planet_valid = False
        elif name == "Jupiter" and comp_val >= 0.40:
            planet_valid = False

        planet_statuses[name] = "PASS" if planet_valid else "FAIL"

    solar_controls_passed = bool(monotonic_passed and all(st == "PASS" for st in planet_statuses.values()))

    all_passed = (
        pearson_passed and
        spearman_passed and
        sanity_all_passed and
        jwst_passed and
        purity_passed and
        solar_controls_passed
    )

    sample_count = jwst_metrics["n_samples"]

    session.execute(text("""
        INSERT INTO validation_runs (
            run_id, engine_version, orbital_version, biosig_version,
            dataset_version, started_at, completed_at, total_samples, status
        ) VALUES (
            :run_id, :eng_ver, :orb_ver, :bio_ver,
            :ds_ver, :start_t, :end_t, :samples, :status
        )
    """), {
        "run_id": run_id,
        "eng_ver": HABITABILITY_MODEL_VERSION,
        "orb_ver": ORBITAL_MODEL_VERSION,
        "bio_ver": BIOSIG_MODEL_VERSION,
        "ds_ver": "UPR Published Catalog + NASA Exoplanet Archive + Gaia DR3",
        "start_t": t_start,
        "end_t": t_end,
        "samples": sample_count,
        "status": "completed" if all_passed else "failed"
    })

    # Track 1: ESI Pearson
    session.execute(text("""
        INSERT INTO validation_results (
            run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
        ) VALUES (
            :run_id, 'UPR ESI Benchmark Correlation', 'Pearson r', 0.70, :actual, 0.0, :samples, :status
        )
    """), {
        "run_id": run_id,
        "actual": float(esi["pearson_r"]),
        "samples": int(esi["n_compared"]),
        "status": "PASS" if pearson_passed else "FAIL"
    })

    # Track 1: ESI Spearman Rank Order
    session.execute(text("""
        INSERT INTO validation_results (
            run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
        ) VALUES (
            :run_id, 'UPR ESI Benchmark Rank Order', 'Spearman rho', 0.80, :actual, 0.0, :samples, :status
        )
    """), {
        "run_id": run_id,
        "actual": float(esi["spearman_rho"]),
        "samples": int(esi["n_compared"]),
        "status": "PASS" if spearman_passed else "FAIL"
    })

    # Track 2: Geometric Observability Power (with persisted CIs and inference method)
    session.execute(text("""
        INSERT INTO validation_results (
            run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance,
            ci_lower, ci_upper, p_value, inference_method, sample_count, status
        ) VALUES (
            :run_id, 'Geometric Observability Power', 'Odds Ratio', 2.00, :actual, :tol,
            :ci_lower, :ci_upper, :p_val, :inf_method, :samples, :status
        )
    """), {
        "run_id": run_id,
        "actual": float(jwst_metrics["obs_or"]),
        "tol": float(jwst_metrics["obs_p_val"]),
        "ci_lower": float(jwst_metrics["obs_ci_raw"][0]) if jwst_metrics.get("obs_ci_raw") else (float(jwst_metrics["obs_ci"][0]) if jwst_metrics.get("obs_ci") else None),
        "ci_upper": float(jwst_metrics["obs_ci_raw"][1]) if jwst_metrics.get("obs_ci_raw") else (float(jwst_metrics["obs_ci"][1]) if jwst_metrics.get("obs_ci") else None),
        "p_val": float(jwst_metrics["obs_p_val"]),
        "inf_method": jwst_metrics.get("inference_method", "cluster_robust"),
        "samples": int(jwst_metrics["n_samples"]),
        "status": "PASS" if jwst_passed else "FAIL"
    })

    # Track 3: Historical JWST Selection Independence Analysis (with persisted CIs and inference method)
    session.execute(text("""
        INSERT INTO validation_results (
            run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance,
            ci_lower, ci_upper, p_value, inference_method, sample_count, status
        ) VALUES (
            :run_id, 'Historical JWST Selection Independence Analysis', 'Triage Odds Ratio', 1.00, :actual, :tol,
            :ci_lower, :ci_upper, :p_val, :inf_method, :samples, :status
        )
    """), {
        "run_id": run_id,
        "actual": float(jwst_metrics["triage_or"]),
        "tol": float(jwst_metrics["triage_p_val"]),
        "ci_lower": float(jwst_metrics["triage_ci_raw"][0]) if jwst_metrics.get("triage_ci_raw") else (float(jwst_metrics["triage_ci"][0]) if jwst_metrics.get("triage_ci") else None),
        "ci_upper": float(jwst_metrics["triage_ci_raw"][1]) if jwst_metrics.get("triage_ci_raw") else (float(jwst_metrics["triage_ci"][1]) if jwst_metrics.get("triage_ci") else None),
        "p_val": float(jwst_metrics["triage_p_val"]),
        "inf_method": jwst_metrics.get("inference_method", "cluster_robust"),
        "samples": int(jwst_metrics["n_samples"]),
        "status": "PASS" if purity_passed else "FAIL"
    })

    # Track 4: Solar System Assertions (evaluated individually)
    for r in sanity_results:
        session.execute(text("""
            INSERT INTO validation_results (
                run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
            ) VALUES (
                :run_id, 'Solar System Assertion', :name, 0.0, :actual, 0.0, 1, :status
            )
        """), {
            "run_id": run_id,
            "name": r.name,
            "actual": float(r.value),
            "status": "PASS" if r.passed else "FAIL"
        })

    # Solar System Planet Controls (Insert evaluated statuses)
    for name, s in sanity_scores.items():
        comp_val = s.get("composite_score") or 0.0
        sim_val = s.get("similarity_score") or 0.0
        safe_val = s.get("safety_score") or 0.0
        status_str = planet_statuses.get(name, "FAIL")

        session.execute(text("""
            INSERT INTO validation_results (
                run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
            ) VALUES (
                :run_id, 'Solar System Sanity Control', :metric, :expected, :actual, :safe, 1, :status
            )
        """), {
            "run_id": run_id,
            "metric": f"{name} Composite Score",
            "expected": float(sim_val),
            "actual": float(comp_val),
            "safe": float(safe_val),
            "status": status_str
        })

    session.commit()
    session.close()
    print(f"Recorded Validation Run {run_id} successfully (Status: {'PASS' if all_passed else 'FAIL'})!")
    return run_id

if __name__ == "__main__":
    record_empirical_run()
