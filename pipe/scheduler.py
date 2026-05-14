"""
pipelines/scheduler.py

Prefect flows and schedules for the exoplanet platform.

Schedules:
  nasa_sync_flow       — nightly 02:00 UTC
  gaia_sync_flow       — weekly  Sunday 03:00 UTC
  arxiv_watcher_flow   — daily   06:00 UTC
  validation_flow      — daily   07:00 UTC (after arxiv watcher)

Run locally (no Prefect Cloud needed):
  python scheduler.py

Deploy to Prefect Cloud:
  prefect deploy scheduler.py:nasa_sync_flow --name "NASA nightly"
  prefect deploy scheduler.py:arxiv_watcher_flow --name "arXiv daily"
  prefect deploy scheduler.py:validation_flow --name "Validation daily"
"""

import os
import sys
import time
import requests
import pandas as pd
import numpy as np
from io import StringIO
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Prefect imports
from prefect import flow, task, get_run_logger

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
Session      = sessionmaker(bind=engine)

# ── shared constants ──────────────────────────────────────────────────────────
NASA_TAP         = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
PIPELINE_VERSION = "1.0.0"

NASA_COLUMNS = (
    "pl_name,hostname,ra,dec,"
    "pl_orbper,pl_orbpererr1,pl_orbpererr2,"
    "pl_orbsmax,pl_orbsmaxerr1,pl_orbsmaxerr2,"
    "pl_orbeccen,pl_orbeccenerr1,pl_orbeccenerr2,"
    "pl_orbincl,pl_orbinclerr1,pl_orbinclerr2,"
    "pl_rade,pl_radeerr1,pl_radeerr2,"
    "pl_bmasse,pl_bmasseerr1,pl_bmasseerr2,"
    "pl_dens,pl_eqt,pl_eqterr1,pl_eqterr2,"
    "pl_trandep,pl_trandeperr1,pl_trandeperr2,"
    "pl_trandur,pl_trandurerr1,pl_trandurerr2,"
    "pl_tranmid,"
    "discoverymethod,disc_year,disc_facility,"
    "tran_flag,rv_flag,ima_flag,micro_flag,pl_controv_flag,"
    "sy_snum,sy_pnum,sy_dist,sy_disterr1,sy_disterr2,"
    "st_teff,st_tefferr1,st_tefferr2,"
    "st_rad,st_raderr1,st_raderr2,"
    "st_mass,st_masserr1,st_masserr2,"
    "st_met,st_meterr1,st_meterr2,"
    "st_logg,st_loggerr1,st_loggerr2,"
    "st_age,st_ageerr1,st_ageerr2,"
    "st_lum,st_spectype"
)


# ─────────────────────────────────────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────────────────────────────────────

@task(retries=3, retry_delay_seconds=30, name="fetch_nasa_archive")
def fetch_nasa_archive() -> pd.DataFrame:
    logger = get_run_logger()
    cols   = ", ".join(c.strip() for c in NASA_COLUMNS.split(",") if c.strip())
    query  = f"SELECT {cols} FROM pscomppars WHERE pl_controv_flag = 0"
    params = {"query": query, "format": "csv"}

    logger.info("Fetching NASA Exoplanet Archive ...")
    r = requests.get(NASA_TAP, params=params, timeout=120)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text), comment="#")
    logger.info(f"Fetched {len(df)} planets")
    return df


@task(retries=2, retry_delay_seconds=60, name="fetch_gaia_ages_for_new_stars")
def fetch_gaia_ages_for_new_stars(new_source_ids: list[str]) -> pd.DataFrame:
    """Fetch age_flame for any new source_ids not yet in star_parameters."""
    from astroquery.gaia import Gaia

    logger = get_run_logger()
    if not new_source_ids:
        logger.info("No new source IDs — skipping Gaia age fetch")
        return pd.DataFrame()

    logger.info(f"Fetching Gaia ages for {len(new_source_ids)} new stars ...")
    chunk_size = 100
    all_rows   = []

    for i in range(0, len(new_source_ids), chunk_size):
        chunk   = new_source_ids[i:i + chunk_size]
        ids_str = ", ".join(str(int(float(sid))) for sid in chunk)
        query   = f"""
            SELECT ap.source_id, ap.age_flame, ap.mass_flame, ap.lum_flame
            FROM gaiadr3.astrophysical_parameters AS ap
            WHERE ap.source_id IN ({ids_str})
        """
        try:
            job    = Gaia.launch_job(query=query, verbose=False)
            result = job.get_results().to_pandas()
            all_rows.append(result)
        except Exception as e:
            logger.warning(f"Gaia chunk {i//chunk_size} failed: {e}")
        time.sleep(0.8)

    if not all_rows:
        return pd.DataFrame()

    return pd.concat(all_rows, ignore_index=True)


@task(name="run_arxiv_watcher")
def run_arxiv_watcher_task(lookback_days: int = 2):
    logger = get_run_logger()
    logger.info(f"Running arXiv watcher (lookback={lookback_days}d) ...")

    # import and run the watcher
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from arxiv_watcher import run as arxiv_run
    arxiv_run(lookback_days=lookback_days)
    logger.info("arXiv watcher complete")


@task(name="run_validation")
def run_validation_task() -> bool:
    logger = get_run_logger()
    logger.info("Running validation suite ...")

    from validation_suite import run_validation
    passed, report = run_validation()
    report.print()

    if not passed:
        failures = [r.name for r in report.critical_failures]
        logger.error(f"Validation FAILED — critical checks: {failures}")
    else:
        logger.info("Validation PASSED")

    return passed


@task(name="upsert_planets_to_db")
def upsert_planets_to_db(df: pd.DataFrame) -> int:
    """
    Lightweight upsert — only insert/update planets that changed
    since the last ingestion run. Checks pl_name existence and
    updates discovery_method / year if different.
    """
    logger  = get_run_logger()
    session = Session()
    count   = 0

    try:
        for _, row in df.iterrows():
            pl_name  = row.get("pl_name")
            hostname = row.get("hostname")
            if not pl_name or not hostname:
                continue

            # upsert star first
            star = session.execute(
                text("SELECT star_id FROM stars WHERE hip_name = :n"),
                {"n": hostname}
            ).fetchone()

            if not star:
                from uuid import uuid4
                star_id = str(uuid4())
                session.execute(text("""
                    INSERT INTO stars (star_id, hip_name, ra, dec, distance_pc, created_at)
                    VALUES (:sid, :name, :ra, :dec, :dist, now())
                """), {
                    "sid":  star_id, "name": hostname,
                    "ra":   _nv(row.get("ra")), "dec": _nv(row.get("dec")),
                    "dist": _nv(row.get("sy_dist"))
                })
            else:
                star_id = star[0]

            # upsert planet
            planet = session.execute(
                text("SELECT planet_id FROM planets WHERE planet_name = :n"),
                {"n": pl_name}
            ).fetchone()

            if not planet:
                from uuid import uuid4
                session.execute(text("""
                    INSERT INTO planets
                        (planet_id, star_id, planet_name, status,
                         discovery_method, discovery_year, created_at)
                    VALUES (:pid, :sid, :name, 'confirmed', :method, :year, now())
                """), {
                    "pid": str(uuid4()), "sid": star_id, "name": pl_name,
                    "method": _nv(row.get("discoverymethod")),
                    "year":   _nv(row.get("disc_year")),
                })
                count += 1

        session.commit()
        logger.info(f"Upserted {count} new planets")
        return count

    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


def _nv(val):
    if val is None: return None
    if isinstance(val, float) and np.isnan(val): return None
    try:
        if pd.isna(val): return None
    except Exception:
        pass
    return val


# ─────────────────────────────────────────────────────────────────────────────
# FLOWS
# ─────────────────────────────────────────────────────────────────────────────

@flow(
    name="nasa_sync_flow",
    description="Nightly NASA archive sync — fetches latest planets and parameters",
    retries=1,
)
def nasa_sync_flow():
    logger = get_run_logger()
    logger.info("Starting nightly NASA sync ...")

    # Import and run the robust ingestor
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from nasa_ingestor import run_ingestion
    run_ingestion()
    
    validation = run_validation_task()

    logger.info(f"NASA sync complete — validation={'PASS' if validation else 'FAIL'}")
    return {"validation_passed": validation}


@flow(
    name="arxiv_watcher_flow",
    description="Daily arXiv paper watcher — tracks new exoplanet papers",
)
def arxiv_watcher_flow(lookback_days: int = 2):
    run_arxiv_watcher_task(lookback_days=lookback_days)
    run_validation_task()


@flow(
    name="validation_flow",
    description="Standalone validation — run anytime to check data health",
)
def validation_flow():
    passed = run_validation_task()
    return passed


@flow(
    name="full_pipeline_flow",
    description="Runs all pipelines in sequence — for manual full refresh",
)
def full_pipeline_flow():
    logger = get_run_logger()
    logger.info("Starting full pipeline run ...")

    df        = fetch_nasa_archive()
    new_count = upsert_planets_to_db(df)
    run_arxiv_watcher_task(lookback_days=7)
    run_spectra_ingestion_task()
    run_biosignature_detector_task()
    run_anomaly_detector_task()
    run_taxonomy_engine_task()
    run_synthesis_task()
    passed    = run_validation_task()

    logger.info(f"Full pipeline done — {new_count} new, validation={'PASS' if passed else 'FAIL'}")


# ── Phase 4: Biosignature pipeline tasks ─────────────────────────────────────

@task(retries=2, retry_delay_seconds=60, name="ingest_atmospheric_spectra")
def run_spectra_ingestion_task():
    logger = get_run_logger()
    logger.info("Running atmospheric spectra ingestion ...")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'modules'))
    from spectra_ingestor import run as spectra_run
    spectra_run()
    logger.info("Spectra ingestion complete")


@task(retries=1, name="run_biosignature_detector")
def run_biosignature_detector_task():
    logger = get_run_logger()
    logger.info("Running biosignature detector ...")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'modules'))
    from biosignature_detector import run as biosig_run
    biosig_run()
    logger.info("Biosignature detector complete")


@flow(
    name="biosignature_flow",
    description="Weekly biosignature pipeline — spectra ingestion → molecule detection",
)
def biosignature_flow():
    logger = get_run_logger()
    logger.info("Starting biosignature pipeline ...")
    run_spectra_ingestion_task()
    run_biosignature_detector_task()
    run_validation_task()
    logger.info("Biosignature pipeline complete")


# ── Phase 5: Anomaly + Taxonomy + Synthesis tasks ────────────────────────────

@task(retries=1, name="run_anomaly_detector")
def run_anomaly_detector_task():
    logger = get_run_logger()
    logger.info("Running anomaly detector ...")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'modules'))
    from anomaly_detector import run as anomaly_run
    anomaly_run()
    logger.info("Anomaly detector complete")


@task(retries=1, name="run_taxonomy_engine")
def run_taxonomy_engine_task():
    logger = get_run_logger()
    logger.info("Running taxonomy engine ...")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'modules'))
    from taxonomy_engine import run as taxonomy_run
    taxonomy_run()
    logger.info("Taxonomy engine complete")


@task(retries=1, name="run_synthesis_engine")
def run_synthesis_task():
    logger = get_run_logger()
    logger.info("Running synthesis engine ...")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'modules'))
    from synthesis_engine import run as synthesis_run
    synthesis_run()
    logger.info("Synthesis engine complete")


@flow(
    name="phase5_flow",
    description="Anomaly detection + taxonomy clustering + cross-module synthesis",
)
def phase5_flow():
    logger = get_run_logger()
    logger.info("Starting Phase 5 pipeline ...")
    run_anomaly_detector_task()
    run_taxonomy_engine_task()
    run_synthesis_task()
    logger.info("Phase 5 pipeline complete")



# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULES  (applied at deploy time, not at import time)
# ─────────────────────────────────────────────────────────────────────────────

# To deploy with schedules run:
#
#   prefect deploy scheduler.py:nasa_sync_flow \
#       --name "NASA nightly" \
#       --cron "0 2 * * *" --timezone "UTC"
#
#   prefect deploy scheduler.py:arxiv_watcher_flow \
#       --name "arXiv daily" \
#       --cron "0 6 * * *" --timezone "UTC"
#
#   prefect deploy scheduler.py:validation_flow \
#       --name "Validation daily" \
#       --cron "0 7 * * *" --timezone "UTC"
#
# Or use the prefect.yaml deploy config below.

PREFECT_YAML = """
# prefect.yaml — paste this in your project root
deployments:
  - name: nasa-nightly
    flow: scheduler.py:nasa_sync_flow
    schedule:
      cron: "0 2 * * *"
      timezone: "UTC"

  - name: arxiv-daily
    flow: scheduler.py:arxiv_watcher_flow
    schedule:
      cron: "0 6 * * *"
      timezone: "UTC"

  - name: validation-daily
    flow: scheduler.py:validation_flow
    schedule:
      cron: "0 7 * * *"
      timezone: "UTC"

  - name: biosignature-weekly
    flow: scheduler.py:biosignature_flow
    schedule:
      cron: "0 4 * * 0"
      timezone: "UTC"

  - name: phase5-weekly
    flow: scheduler.py:phase5_flow
    schedule:
      cron: "0 5 * * 0"
      timezone: "UTC"
"""


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"

    if cmd == "nasa":
        nasa_sync_flow()
    elif cmd == "arxiv":
        arxiv_watcher_flow()
    elif cmd == "validate":
        validation_flow()
    elif cmd == "full":
        full_pipeline_flow()
    elif cmd == "biosig":
        biosignature_flow()
    elif cmd == "phase5":
        phase5_flow()
    else:
        print("Usage: python scheduler.py [nasa|arxiv|validate|full|biosig|phase5]")