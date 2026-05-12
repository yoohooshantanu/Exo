"""
pipelines/ingest_to_db.py

Ingests planets_enriched.csv into PostgreSQL.
Populates in order: stars → star_identifiers → planets → star_parameters
→ planet_parameters → habitability pre-scores (in_hz flag).

Idempotent — safe to re-run. Uses upsert logic throughout.
Existing rows are updated if values changed, never duplicated.

Requires:
  planets_enriched.csv     — output of fetch_nasa_full.py
  DATABASE_URL in .env     — postgresql://user:pass@host:5432/dbname
"""

import os
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

from sqlalchemy import create_engine, text, insert, update
from sqlalchemy.orm import sessionmaker

# Import models to use ORM constructs which enable fast multi-row INSERTs
from models import PlanetParameter, StarParameter, HabitabilityScore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL     = os.environ["DATABASE_URL"]
INPUT_CSV        = str(PROJECT_ROOT / "planets_enriched_clean.csv")
PIPELINE_VERSION = "1.0.0"

engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

NOW = datetime.now(timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────

def new_id() -> str:
    return str(uuid.uuid4())


def nv(val):
    """Convert NaN/NaT/None to None for SQL insertion."""
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    if pd.isna(val):
        return None
    return val


def log(msg: str):
    print(f"  {datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}")


# ── ingestion run record ──────────────────────────────────────────────────────

def create_ingestion_run(session) -> str:
    run_id = new_id()
    session.execute(text("""
        INSERT INTO ingestion_runs
            (run_id, pipeline_version, source, started_at, status)
        VALUES
            (:run_id, :version, 'nasa_archive+gaia_dr3', :started_at, 'running')
    """), {"run_id": run_id, "version": PIPELINE_VERSION, "started_at": NOW})
    session.commit()
    return run_id


def finish_ingestion_run(session, run_id: str, records: int, status: str = "success", error: str = None):
    session.execute(text("""
        UPDATE ingestion_runs
        SET finished_at       = :now,
            records_affected  = :records,
            status            = :status,
            error_detail      = :error
        WHERE run_id = :run_id
    """), {"now": NOW, "records": records, "status": status, "error": error, "run_id": run_id})
    session.commit()


# ── star upsert ───────────────────────────────────────────────────────────────

from sqlalchemy.dialects.postgresql import insert as pg_insert
from models import Star, Planet

def upsert_stars(session, df: pd.DataFrame) -> dict:
    """
    Insert unique stars. Returns {hostname: star_id} mapping.
    Uses hip_name = hostname as canonical name.
    Upserts on hip_name — updates ra/dec/distance if changed.
    """
    stars_df = df[["hostname", "ra", "dec", "dist_best", "st_spectype"]].drop_duplicates("hostname")
    log(f"Upserting {len(stars_df)} stars ...")

    insert_dicts = []
    for _, row in stars_df.iterrows():
        insert_dicts.append({
            "star_id": new_id(),
            "hip_name": row["hostname"],
            "ra": nv(row["ra"]),
            "dec": nv(row["dec"]),
            "distance_pc": nv(row["dist_best"]),
            "spectral_type": nv(row.get("st_spectype")),
            "created_at": NOW
        })

    if insert_dicts:
        stmt = pg_insert(Star).values(insert_dicts)
        stmt = stmt.on_conflict_do_update(
            index_elements=['hip_name'],
            set_={
                'ra': stmt.excluded.ra,
                'dec': stmt.excluded.dec,
                'distance_pc': stmt.excluded.distance_pc,
                'spectral_type': stmt.excluded.spectral_type
            }
        )
        session.execute(stmt)
        session.commit()

    # Fetch mapping after upsert
    hostname_to_id = {}
    result = session.execute(text("SELECT hip_name, star_id FROM stars")).fetchall()
    for row in result:
        hostname_to_id[row[0]] = str(row[1])

    log(f"Stars done — {len(hostname_to_id)} records")
    return hostname_to_id


# ── star identifiers ──────────────────────────────────────────────────────────

from models import StarIdentifier

def upsert_star_identifiers(session, df: pd.DataFrame, hostname_to_id: dict):
    """Insert Gaia source_id as a catalogue identifier per star."""
    log("Upserting star identifiers (Gaia source_id) ...")

    stars_df = df[["hostname", "source_id"]].drop_duplicates("hostname")
    insert_dicts = []

    for _, row in stars_df.iterrows():
        if pd.isna(row.get("source_id")):
            continue

        star_id  = hostname_to_id.get(row["hostname"])
        gaia_id  = str(int(float(row["source_id"])))

        insert_dicts.append({
            "id": new_id(),
            "star_id": star_id,
            "catalogue": "gaia_dr3",
            "catalogue_id": gaia_id
        })

    count = 0
    if insert_dicts:
        stmt = pg_insert(StarIdentifier).values(insert_dicts)
        stmt = stmt.on_conflict_do_nothing(index_elements=['catalogue', 'catalogue_id'])
        result = session.execute(stmt)
        count = result.rowcount
        session.commit()

    log(f"Star identifiers done — {count} new records")


# ── planet upsert ─────────────────────────────────────────────────────────────

def upsert_planets(session, df: pd.DataFrame, hostname_to_id: dict) -> dict:
    """
    Insert planets. Returns {pl_name: planet_id}.
    Upserts on pl_name.
    """
    log(f"Upserting {len(df)} planets ...")
    
    insert_dicts = []
    for _, row in df.iterrows():
        star_id = hostname_to_id.get(row["hostname"])
        if not star_id:
            continue

        insert_dicts.append({
            "planet_id": new_id(),
            "star_id": star_id,
            "planet_name": row["pl_name"],
            "status": "confirmed",
            "discovery_method": nv(row.get("discoverymethod")),
            "discovery_year": nv(row.get("disc_year")),
            "created_at": NOW
        })

    if insert_dicts:
        stmt = pg_insert(Planet).values(insert_dicts)
        stmt = stmt.on_conflict_do_update(
            index_elements=['planet_name'],
            set_={
                'status': 'confirmed',
                'discovery_method': stmt.excluded.discovery_method,
                'discovery_year': stmt.excluded.discovery_year
            }
        )
        session.execute(stmt)
        session.commit()

    planet_name_to_id = {}
    result = session.execute(text("SELECT planet_name, planet_id FROM planets")).fetchall()
    for row in result:
        planet_name_to_id[row[0]] = str(row[1])

    log(f"Planets done — {len(planet_name_to_id)} records")
    return planet_name_to_id


# ── parameter ingestion ───────────────────────────────────────────────────────

# Maps (column_in_csv, param_name_in_db, unit)
PLANET_PARAMS = [
    ("pl_orbper",       "period_days",          "days"),
    ("pl_orbsmax",      "semi_major_axis_au",    "au"),
    ("pl_orbeccen",     "eccentricity",          "dimensionless"),
    ("pl_orbincl",      "inclination_deg",       "degrees"),
    ("pl_rade",         "radius_earth",          "earth_radii"),
    ("pl_bmasse",       "mass_earth",            "earth_masses"),
    ("pl_dens",         "density_gcc",           "g_cm3"),
    ("pl_eqt",          "eq_temperature_k",      "kelvin"),
    ("pl_trandep",      "transit_depth_ppm",     "ppm"),
    ("pl_trandur",      "transit_duration_hr",   "hours"),
    ("pl_density_earth","density_earth",         "earth_densities"),
]

STAR_PARAMS = [
    ("st_teff",       "teff_nasa_k",       "kelvin"),
    ("teff_gspphot",  "teff_gaia_k",       "kelvin"),
    ("teff_best",     "teff_best_k",       "kelvin"),
    ("st_rad",        "radius_solar",      "solar_radii"),
    ("st_mass",       "mass_solar",        "solar_masses"),
    ("st_met",        "metallicity_nasa",  "dex"),
    ("mh_gspphot",    "metallicity_gaia",  "dex"),
    ("met_best",      "metallicity_best",  "dex"),
    ("st_logg",       "logg_nasa",         "log_cgs"),
    ("logg_gspphot",  "logg_gaia",         "log_cgs"),
    ("st_age",        "age_nasa_gyr",      "gyr"),
    ("age_flame",     "age_gaia_gyr",      "gyr"),
    ("st_lum",        "luminosity_solar",  "solar_luminosities"),
    ("distance_pc",   "distance_gaia_pc",  "parsecs"),
    ("sy_dist",       "distance_nasa_pc",  "parsecs"),
    ("dist_best",     "distance_best_pc",  "parsecs"),
    ("parallax",      "parallax_mas",      "milliarcseconds"),
]


def ingest_planet_params(session, df: pd.DataFrame, planet_name_to_id: dict, run_id: str):
    log(f"Ingesting planet parameters ({len(PLANET_PARAMS)} types × {len(df)} planets) ...")
    
    # 1. Retire all currently active planet parameters
    session.execute(
        update(PlanetParameter)
        .where(PlanetParameter.is_default == True)
        .where(PlanetParameter.valid_to.is_(None))
        .values(is_default=False, valid_to=NOW)
    )

    insert_dicts = []
    for _, row in df.iterrows():
        planet_id = planet_name_to_id.get(row["pl_name"])
        if not planet_id:
            continue

        for csv_col, param_name, unit in PLANET_PARAMS:
            val = nv(row.get(csv_col))
            if val is None:
                continue

            insert_dicts.append({
                "param_id":   new_id(),
                "planet_id":  planet_id,
                "run_id":     run_id,
                "param_name": param_name,
                "value":      float(val),
                "unit":       unit,
                "now":        NOW,
            })

    # 2. Bulk insert new parameters (SQLAlchemy 2.0 uses multi-values INSERT)
    if insert_dicts:
        # We can chunk them in case of large lists
        chunk_size = 5000
        for i in range(0, len(insert_dicts), chunk_size):
            chunk = insert_dicts[i:i+chunk_size]
            session.execute(insert(PlanetParameter), chunk)

    session.commit()
    log(f"Planet parameters done — {len(insert_dicts)} rows inserted")
    return len(insert_dicts)


def ingest_star_params(session, df: pd.DataFrame, hostname_to_id: dict, run_id: str):
    log(f"Ingesting star parameters ({len(STAR_PARAMS)} types × unique stars) ...")
    
    # 1. Retire all currently active star parameters
    session.execute(
        update(StarParameter)
        .where(StarParameter.is_default == True)
        .where(StarParameter.valid_to.is_(None))
        .values(is_default=False, valid_to=NOW)
    )

    stars_df = df.drop_duplicates("hostname")
    insert_dicts = []

    for _, row in stars_df.iterrows():
        star_id = hostname_to_id.get(row["hostname"])
        if not star_id:
            continue

        for csv_col, param_name, unit in STAR_PARAMS:
            val = nv(row.get(csv_col))
            if val is None:
                continue

            insert_dicts.append({
                "param_id":   new_id(),
                "star_id":    star_id,
                "run_id":     run_id,
                "param_name": param_name,
                "value":      float(val),
                "unit":       unit,
                "now":        NOW,
            })

    # 2. Bulk insert new parameters
    if insert_dicts:
        chunk_size = 5000
        for i in range(0, len(insert_dicts), chunk_size):
            chunk = insert_dicts[i:i+chunk_size]
            session.execute(insert(StarParameter), chunk)

    session.commit()
    log(f"Star parameters done — {len(insert_dicts)} rows inserted")
    return len(insert_dicts)





# ── habitability pre-scores (in_hz flag only for now) ─────────────────────────

def ingest_hz_flag(session, df: pd.DataFrame, planet_name_to_id: dict):
    """
    Inserts a basic habitability_scores row for planets where in_hz is computed.
    composite_score = 0.0 placeholder — will be filled by habitability module.
    hz_score = 1.0 if in_hz else 0.0.
    """
    log("Ingesting habitable zone flags ...")
    count = 0
    MODEL_VERSION = "0.1.0-hz-only"
    insert_dicts = []

    for _, row in df.iterrows():
        planet_id = planet_name_to_id.get(row["pl_name"])
        if not planet_id:
            continue

        in_hz = row.get("in_hz")
        if pd.isna(in_hz):
            continue

        insert_dicts.append({
            "score_id":      new_id(),
            "planet_id":     planet_id,
            "model_version": MODEL_VERSION,
            "composite_score": 0.0,
            "hz_score":      1.0 if in_hz else 0.0,
            "scored_at":     NOW,
        })

    if insert_dicts:
        stmt = pg_insert(HabitabilityScore).values(insert_dicts)
        stmt = stmt.on_conflict_do_nothing(index_elements=['planet_id', 'model_version'])
        session.execute(stmt)
        count = len(insert_dicts)

    session.commit()
    log(f"HZ flags done — {count} rows inserted")


# ── main ──────────────────────────────────────────────────────────────────────

def run():
    print(f"\nLoading {INPUT_CSV} ...")
    df = pd.read_csv(INPUT_CSV, low_memory=False)
    print(f"Loaded {len(df)} planets, {len(df.columns)} columns\n")

    session = SessionLocal()
    run_id  = None

    try:
        run_id = create_ingestion_run(session)
        print(f"Ingestion run: {run_id}\n")

        hostname_to_id   = upsert_stars(session, df)
        upsert_star_identifiers(session, df, hostname_to_id)
        planet_name_to_id = upsert_planets(session, df, hostname_to_id)

        p_count = ingest_planet_params(session, df, planet_name_to_id, run_id)
        s_count = ingest_star_params(session, df, hostname_to_id, run_id)
        ingest_hz_flag(session, df, planet_name_to_id)

        total = p_count + s_count
        finish_ingestion_run(session, run_id, total)

        print(f"\n{'='*52}")
        print(f"  Ingestion complete")
        print(f"  Stars          : {len(hostname_to_id)}")
        print(f"  Planets        : {len(planet_name_to_id)}")
        print(f"  Parameter rows : {total}")
        print(f"  Run ID         : {run_id}")
        print(f"{'='*52}")
        print(f"\nNext step: python ingest_to_db.py  (re-run = safe upsert)")
        print(f"Then:      python habitability_scorer.py")

    except Exception as e:
        print(f"\nFATAL: {e}")
        if run_id:
            try:
                session.rollback()
            except:
                pass
            finish_ingestion_run(session, run_id, 0, status="failed", error=str(e))
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run()