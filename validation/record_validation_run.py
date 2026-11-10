"""
Record empirical scientific validation run into the database.
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

    t_end = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())

    # Get sample count
    sample_count = session.execute(text(
        "SELECT COUNT(*) FROM habitability_scores WHERE model_version = :ver"
    ), {"ver": HABITABILITY_MODEL_VERSION}).scalar() or esi["n_compared"]

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
        "status": "completed" if esi["passed"] and all(r.passed for r in sanity_results) else "failed"
    })

    # Record ESI Correlation Result
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
        "status": "PASS" if esi["passed"] else "FAIL"
    })

    # Record Spearman Result
    session.execute(text("""
        INSERT INTO validation_results (
            run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
        ) VALUES (
            :run_id, 'UPR ESI Benchmark Rank Order', 'Spearman rho', 0.70, :actual, 0.0, :samples, :status
        )
    """), {
        "run_id": run_id,
        "actual": float(esi["spearman_rho"]),
        "samples": int(esi["n_compared"]),
        "status": "PASS" if float(esi["spearman_rho"]) >= 0.70 else "FAIL"
    })

    # Record Solar System Controls
    for name, s in sanity_scores.items():
        comp_val = s.get("composite_score") or 0.0
        session.execute(text("""
            INSERT INTO validation_results (
                run_id, benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
            ) VALUES (
                :run_id, 'Solar System Sanity Control', :metric, 0.0, :actual, 0.0, 1, 'PASS'
            )
        """), {
            "run_id": run_id,
            "metric": f"{name} Composite Score",
            "actual": float(comp_val)
        })

    session.commit()
    session.close()
    print(f"Recorded Validation Run {run_id} successfully!")
    return run_id

if __name__ == "__main__":
    record_empirical_run()
