"""
modules/exomol_seeder.py  v2.0.0

Offline template generation for Cross-Correlation Function (CCF) biosignature detection.

This script simulates the offline generation of continuous, broadened spectral templates 
(using opacity data) for target molecules. In a full production environment, this would
wrap `exojax` or `radis` to process terabytes of ExoMol .states and .trans files.

Here, we compute continuous 1D arrays (wavelength vs. cross-section flux), applying 
broadening and instrument resolution binning, and save them as lightning-fast .parquet 
files for the runtime engine.
"""

import os
import uuid
import math
import argparse
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

OUTPUT_DIR = PROJECT_ROOT / "data" / "templates"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── constants & simulation config ─────────────────────────────────────────────

# JWST NIRSpec/MIRI wavelength range (0.6 to 28 µm)
WAVELENGTH_MIN = 0.6
WAVELENGTH_MAX = 28.0

# Resolution for our pre-computed grid (higher = more precise template)
# We use R ~ 2000 which is typical for JWST NIRSpec G395H binned.
GRID_POINTS = 20000
WAVELENGTH_GRID = np.linspace(WAVELENGTH_MIN, WAVELENGTH_MAX, GRID_POINTS)

# In a full ExoMol run, these would be fetched from their API.
import sys
sys.path.append(str(PROJECT_ROOT))
from modules.hitran_seeder import STATIC_LINES, MOLECULES

def new_id() -> str:
    return str(uuid.uuid4())

def log(msg: str):
    print(f"  {datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}")

def compute_template(molecule_key: str, temp_k: float, pres_bar: float) -> pd.DataFrame:
    """
    Computes a continuous, broadened 1D spectral template.
    """
    raw_lines = STATIC_LINES.get(molecule_key, [])
    if not raw_lines:
        return pd.DataFrame()

    flux = np.zeros(GRID_POINTS)
    
    # 1. Map discrete lines onto high-res grid
    for wn, intensity, ea, le in raw_lines:
        # wavenumber to wavelength (um)
        wl = 10000.0 / wn if wn > 0 else 0
        if WAVELENGTH_MIN <= wl <= WAVELENGTH_MAX:
            idx = np.argmin(np.abs(WAVELENGTH_GRID - wl))
            
            # Very basic temperature scaling approximation for line intensity
            # E_lower in cm-1, kb in cm-1/K = 0.695
            q_scale = math.exp(-le / (0.695 * temp_k))
            flux[idx] += intensity * q_scale

    # 2. Apply Broadening
    # Thermal (Doppler) + Pressure (Lorentzian) -> Voigt profile.
    # In this mock we use a Gaussian filter equivalent to typical JWST instrument resolution + broadening.
    # Sigma ~ 3 grid points gives a nice continuous band structure.
    broadened_flux = gaussian_filter1d(flux, sigma=3.0)

    # 3. Normalize to [0, 1] range for CCF matching
    max_flux = np.max(broadened_flux)
    if max_flux > 0:
        broadened_flux = broadened_flux / max_flux

    return pd.DataFrame({
        "wavelength_um": np.round(WAVELENGTH_GRID, 5),
        "flux": np.round(broadened_flux, 6)
    })

def seed_templates(session, dry_run=False):
    """Generate offline templates and register them in the database."""
    log("Starting ExoMol Template generation...")
    
    # Grid of conditions
    temperatures = [500.0, 1000.0, 1500.0, 2000.0]
    pressure = 0.1 # reference pressure
    resolution = 1000 # JWST approximation
    
    total_generated = 0

    for mol_key in MOLECULES.keys():
        for temp_k in temperatures:
            # Generate the 1D continuous template
            df = compute_template(mol_key, temp_k, pressure)
            if df.empty:
                continue
                
            # Save to Parquet
            filename = f"{mol_key}_{int(temp_k)}K.parquet"
            filepath = OUTPUT_DIR / filename
            
            if not dry_run:
                df.to_parquet(filepath, index=False)
            
            rel_path = f"data/templates/{filename}"
            log(f"  Generated template: {filename} ({len(df)} points)")
            
            if not dry_run:
                # Register in database
                existing = session.execute(text("""
                    SELECT template_id FROM spectral_templates
                    WHERE molecule = :mol AND temperature_k = :t AND pressure_bar = :p
                """), {"mol": mol_key, "t": temp_k, "p": pressure}).fetchone()

                if not existing:
                    session.execute(text("""
                        INSERT INTO spectral_templates
                            (template_id, molecule, temperature_k, pressure_bar, instrument_resolution, file_path)
                        VALUES
                            (:tid, :mol, :t, :p, :res, :path)
                    """), {
                        "tid": new_id(),
                        "mol": mol_key,
                        "t": temp_k,
                        "p": pressure,
                        "res": resolution,
                        "path": rel_path
                    })
            total_generated += 1

    if not dry_run:
        session.commit()
    log(f"Done. {total_generated} templates processed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ExoMol Template Seeder")
    parser.add_argument("--molecule", type=str, default=None, help="Specific molecule to seed")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files or DB")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        seed_templates(session, dry_run=args.dry_run)
    except Exception as e:
        print(f"FATAL: {e}")
        import traceback; traceback.print_exc()
    finally:
        session.close()
