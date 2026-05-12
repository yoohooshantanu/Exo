"""
modules/spectra_ingestor.py  v1.0.0

Ingests published atmospheric spectra from the NASA Exoplanet Archive
Atmospheric Spectroscopy Table into our atmospheric_spectra PostgreSQL table.

Architecture:
  1. TAP query → metadata (planet, facility, bibcode, spec_path)
  2. Firefly session → workspace ID
  3. Download .tbl files via workspace URL
  4. Parse IPAC-format tables → wavelength, depth, uncertainties
  5. Upsert into atmospheric_spectra

Run:
  python modules/spectra_ingestor.py                         # full ingestion
  python modules/spectra_ingestor.py --planet "WASP-39 b"    # single planet
  python modules/spectra_ingestor.py --facility JWST         # filter by facility
  python modules/spectra_ingestor.py --dry-run               # preview only
"""

import os
import re
import uuid
import argparse
import math
import time
import requests
import numpy as np
import pandas as pd
from io import StringIO
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL     = os.environ["DATABASE_URL"]
PIPELINE_VERSION = "1.0.0"
NASA_TAP         = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
FIREFLY_URL      = "https://exoplanetarchive.ipac.caltech.edu/cgi-bin/atmospheres/nph-firefly"

engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

DOWNLOAD_DELAY = 0.5  # seconds between file downloads (polite)


# -- helpers -----------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())

def now_utc():
    return datetime.now(timezone.utc)

def nv(val):
    if val is None:
        return None
    if isinstance(val, (np.floating, np.integer)):
        v = val.item()  # convert numpy scalar to Python native
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    return val

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"  {ts}  {msg}")


# -- TAP metadata fetch -----------------------------------------------------

def fetch_spectra_metadata(planet_name=None, facility=None):
    """Fetch metadata (spec_path, planet, facility, bibcode) via TAP."""
    cols = "pl_name, spec_type, instrument, facility, bibcode, spec_path"
    query = f"SELECT {cols} FROM spectra"

    conditions = []
    if planet_name:
        conditions.append(f"pl_name = '{planet_name}'")
    if facility:
        conditions.append(f"facility like '%{facility}%'")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    log(f"TAP: {query[:100]}...")
    r = requests.get(NASA_TAP, params={"query": query, "format": "csv"}, timeout=180)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text), comment="#")
    log(f"Fetched {len(df)} spectra metadata rows")
    return df


# -- Firefly session ---------------------------------------------------------

def get_workspace_id(http_session):
    """Initialize a Firefly session and extract the workspace ID."""
    log("Initializing Firefly session ...")
    r = http_session.get(FIREFLY_URL, params={"atmospheres": ""}, timeout=30)
    r.raise_for_status()

    # Extract workspace ID from the HTML (pattern: TMP_xxxxx_nnnnn)
    match = re.search(r'(TMP_\w+)', r.text)
    if match:
        ws = match.group(1)
        log(f"Workspace: {ws}")
        return ws

    # Fallback: check cookies
    for cookie in http_session.cookies:
        if "TMP" in cookie.value:
            log(f"Workspace (cookie): {cookie.value}")
            return cookie.value

    raise RuntimeError("Could not extract workspace ID from Firefly session")


# -- .tbl file download & parse ---------------------------------------------

def download_spectrum_file(http_session, workspace_id, spec_path):
    """Download and parse a single .tbl spectrum data file."""
    url = (f"https://exoplanetarchive.ipac.caltech.edu/workspace/"
           f"{workspace_id}/atmospheres/tab1/data/{spec_path}")
    try:
        r = http_session.get(url, timeout=30)
        if r.status_code != 200:
            return None
        # Check it's actually data, not HTML
        if "<html" in r.text[:200].lower():
            return None
        return parse_ipac_table(r.text)
    except Exception as e:
        log(f"  Download failed: {e}")
        return None


def parse_ipac_table(raw_text):
    """
    Parse IPAC table format (.tbl) into a DataFrame.
    NASA .tbl files use | delimited headers and whitespace-separated data.
    Comment lines start with \\.
    """
    lines = raw_text.strip().split("\n")
    header = None
    type_line_count = 0
    data_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("\\"):
            continue
        if stripped.startswith("|"):
            if header is None:
                # First | line = column names
                header = [c.strip() for c in stripped.split("|") if c.strip()]
            # Skip type/unit/null lines (also start with |)
            type_line_count += 1
            continue
        # Data line — whitespace separated
        if header:
            parts = stripped.split()
            if len(parts) >= len(header):
                data_lines.append(parts[:len(header)])
            elif len(parts) >= 3:
                # Pad with None
                padded = parts + [None] * (len(header) - len(parts))
                data_lines.append(padded[:len(header)])

    if not header or not data_lines:
        return None

    df = pd.DataFrame(data_lines, columns=header)
    # Replace 'null' strings with NaN, then convert numeric
    df = df.replace(["null", "NULL", "--", ""], np.nan)
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        except Exception:
            pass
    return df


def extract_depth_columns(df):
    """
    Extract wavelength, depth, and uncertainty columns from parsed .tbl.
    NASA tables use varying column names depending on the spectrum type.
    """
    # Column name patterns — NASA uses PL_TRANDEP, CENTRALWAVELNG etc.
    wl_candidates = ["centralwavelng", "wavelength", "wave", "lambda"]
    depth_candidates = ["pl_trandep", "tran_depth", "depth", "transit_depth",
                        "rp_rs_sq", "rprs2"]
    err_up_candidates = ["pl_trandeperr1", "tran_deptherr1", "deptherr1",
                         "depth_err1", "err_upper"]
    err_lo_candidates = ["pl_trandeperr2", "tran_deptherr2", "deptherr2",
                         "depth_err2", "err_lower"]
    bw_candidates = ["bandwidth", "bin_width", "binwidth"]

    def find_col(df, candidates):
        cols_lower = {c.lower(): c for c in df.columns}
        for cand in candidates:
            if cand.lower() in cols_lower:
                return cols_lower[cand.lower()]
        return None

    wl_col = find_col(df, wl_candidates)
    depth_col = find_col(df, depth_candidates)
    err_up_col = find_col(df, err_up_candidates)
    err_lo_col = find_col(df, err_lo_candidates)
    bw_col = find_col(df, bw_candidates)

    if not wl_col or not depth_col:
        return None

    result = pd.DataFrame()
    result["wavelength_um"] = pd.to_numeric(df[wl_col], errors="coerce")
    result["depth_ppm"] = pd.to_numeric(df[depth_col], errors="coerce")

    if err_up_col:
        result["depth_err_upper"] = pd.to_numeric(df[err_up_col], errors="coerce")
    if err_lo_col:
        result["depth_err_lower"] = pd.to_numeric(df[err_lo_col], errors="coerce")
    if bw_col:
        result["bandwidth_um"] = pd.to_numeric(df[bw_col], errors="coerce")

    return result.dropna(subset=["wavelength_um", "depth_ppm"])


# -- planet cross-reference -------------------------------------------------

def build_planet_lookup(session):
    rows = session.execute(text("SELECT planet_name, planet_id FROM planets")).fetchall()
    return {row[0].lower(): row[1] for row in rows}


# -- ingestion run -----------------------------------------------------------

def create_ingestion_run(session):
    run_id = new_id()
    session.execute(text("""
        INSERT INTO ingestion_runs (run_id, pipeline_version, source, started_at, status)
        VALUES (:rid, :ver, 'nasa_atmospheric_spectra', :ts, 'running')
    """), {"rid": run_id, "ver": PIPELINE_VERSION, "ts": now_utc()})
    session.commit()
    return run_id

def finish_ingestion_run(session, run_id, records, status="success", error=None):
    session.execute(text("""
        UPDATE ingestion_runs SET finished_at=:ts, records_affected=:n, status=:st, error_detail=:err
        WHERE run_id=:rid
    """), {"ts": now_utc(), "n": records, "st": status, "err": error, "rid": run_id})
    session.commit()


# -- upsert ------------------------------------------------------------------

def upsert_spectra(db_session, rows, run_id):
    count = 0
    for row in rows:
        existing = db_session.execute(text("""
            SELECT row_id FROM atmospheric_spectra
            WHERE spec_id=:sid AND ABS(wavelength_um - :wl) < 0.0001
            LIMIT 1
        """), {"sid": row["spec_id"], "wl": row["wavelength_um"]}).fetchone()

        params = {
            "rid": new_id(), "sid": row["spec_id"], "pid": row.get("planet_id"),
            "pn": row["planet_name"], "hn": row.get("hostname"),
            "ot": row.get("obs_type"), "inst": row.get("instrument"),
            "fac": row.get("facility"), "ref": row.get("pub_reference"),
            "wl": row["wavelength_um"], "bw": row.get("bandwidth_um"),
            "dp": row.get("depth_ppm"), "eu": row.get("depth_err_upper"),
            "el": row.get("depth_err_lower"), "rn": run_id,
        }

        if existing:
            params["eid"] = existing[0]
            db_session.execute(text("""
                UPDATE atmospheric_spectra SET
                    depth_ppm=:dp, depth_err_upper=:eu, depth_err_lower=:el,
                    bandwidth_um=:bw, run_id=:rn
                WHERE row_id=:eid
            """), params)
        else:
            db_session.execute(text("""
                INSERT INTO atmospheric_spectra
                    (row_id, spec_id, planet_id, planet_name, hostname,
                     obs_type, instrument, facility, pub_reference,
                     wavelength_um, bandwidth_um, depth_ppm,
                     depth_err_upper, depth_err_lower, run_id)
                VALUES (:rid, :sid, :pid, :pn, :hn, :ot, :inst, :fac, :ref,
                        :wl, :bw, :dp, :eu, :el, :rn)
            """), params)

        count += 1
        if count % 100 == 0:
            db_session.commit()
            log(f"  {count} rows processed ...")

    db_session.commit()
    return count


# -- main --------------------------------------------------------------------

def run(planet_name=None, facility=None, dry_run=False):
    print(f"\nSpectra Ingestor v{PIPELINE_VERSION}")
    print(f"  Source: NASA Exoplanet Archive - Atmospheric Spectroscopy")
    if planet_name:
        print(f"  Filter: planet = {planet_name}")
    if facility:
        print(f"  Filter: facility = {facility}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    # Step 1: TAP metadata
    print("\n[1/4] Fetching spectra metadata via TAP ...")
    meta_df = fetch_spectra_metadata(planet_name, facility)
    if meta_df.empty:
        print("  No spectra metadata returned")
        return

    n_planets = meta_df["pl_name"].nunique()
    n_spectra = len(meta_df)
    print(f"  Planets:  {n_planets}")
    print(f"  Spectra:  {n_spectra}")

    if dry_run:
        print(f"\n[DRY RUN] Sample metadata:")
        print(meta_df[["pl_name", "facility", "instrument"]].head(10).to_string(index=False))
        print(f"\n[DRY RUN] No downloads or DB writes.")
        return

    # Step 2: Firefly session
    print("\n[2/4] Getting Firefly workspace ...")
    http_session = requests.Session()
    try:
        workspace_id = get_workspace_id(http_session)
    except Exception as e:
        print(f"  Could not get workspace: {e}")
        print("  This is expected if NASA archive is temporarily unavailable.")
        return

    # Step 3: Download & parse each .tbl
    print(f"\n[3/4] Downloading {n_spectra} spectrum files ...")
    db_session = SessionLocal()
    run_id = create_ingestion_run(db_session)
    planet_lookup = build_planet_lookup(db_session)
    log(f"Planet lookup: {len(planet_lookup)} planets in DB")

    all_rows = []
    downloaded = 0
    failed = 0

    for idx, meta in meta_df.iterrows():
        spec_path = meta.get("spec_path")
        if not spec_path or pd.isna(spec_path):
            continue

        pname = str(meta["pl_name"])
        spec_id = spec_path.split("/")[-1].replace(".tbl", "")
        planet_id = planet_lookup.get(pname.lower())

        # Download and parse
        raw_df = download_spectrum_file(http_session, workspace_id, spec_path)
        if raw_df is None:
            failed += 1
            continue

        parsed = extract_depth_columns(raw_df)
        if parsed is None or parsed.empty:
            failed += 1
            continue

        downloaded += 1
        for _, drow in parsed.iterrows():
            all_rows.append({
                "spec_id": spec_id,
                "planet_id": planet_id,
                "planet_name": pname,
                "hostname": None,
                "obs_type": nv(meta.get("spec_type")),
                "instrument": nv(meta.get("instrument")),
                "facility": nv(meta.get("facility")),
                "pub_reference": nv(meta.get("bibcode")),
                "wavelength_um": nv(drow.get("wavelength_um")),
                "bandwidth_um": nv(drow.get("bandwidth_um")),
                "depth_ppm": nv(drow.get("depth_ppm")),
                "depth_err_upper": nv(drow.get("depth_err_upper")),
                "depth_err_lower": nv(drow.get("depth_err_lower")),
            })

        if downloaded % 20 == 0:
            log(f"  Downloaded {downloaded}/{n_spectra} spectra ({len(all_rows)} data points)")

        time.sleep(DOWNLOAD_DELAY)

    log(f"Downloaded: {downloaded}, Failed: {failed}, Data points: {len(all_rows)}")

    # Step 4: Upsert
    print(f"\n[4/4] Upserting {len(all_rows)} data points ...")
    try:
        count = upsert_spectra(db_session, all_rows, run_id)
        finish_ingestion_run(db_session, run_id, count)

        print(f"\n{'='*60}")
        print(f"  Spectra ingestion complete")
        print(f"  Files downloaded:    {downloaded}")
        print(f"  Data points stored:  {count}")
        print(f"  Unique planets:      {n_planets}")
        print(f"  Run ID:              {run_id}")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\nFATAL: {e}")
        try:
            db_session.rollback()
            finish_ingestion_run(db_session, run_id, 0, status="failed", error=str(e))
        except Exception as inner_e:
            print(f"Failed to log error to DB: {inner_e}")
        raise
    finally:
        db_session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spectra Ingestor - NASA TAP")
    parser.add_argument("--planet", type=str, default=None)
    parser.add_argument("--facility", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(planet_name=args.planet, facility=args.facility, dry_run=args.dry_run)
