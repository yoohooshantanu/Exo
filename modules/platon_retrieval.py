"""
modules/platon_retrieval.py

A background worker module for running full Bayesian atmospheric retrievals
using PLATON (PLanetary Atmospheric Tool for Observer Noobs).
"""

import os, json, math, uuid
import numpy as np
import traceback
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from dotenv import load_dotenv

try:
    from platon.retriever import CombinedRetriever
    from platon.constants import R_sun, R_jup, M_jup, R_earth, M_earth
except ImportError:
    CombinedRetriever = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

OUTPUT_DIR = PROJECT_ROOT / "outputs" / "retrievals"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def new_id(): return str(uuid.uuid4())

def run_platon_retrieval(planet_id: str, spec_id: str, retrieval_id: str):
    """
    Runs a nested sampling retrieval using PLATON.
    Intended to be run as a background task.
    """
    if CombinedRetriever is None:
        mark_failed(retrieval_id, "PLATON library is not installed.")
        return

    session = Session()
    start_time = datetime.now(timezone.utc)
    try:
        # 1. Fetch spectrum data
        spectrum_rows = session.execute(text("""
            SELECT wavelength_um, bandwidth_um, depth_ppm, depth_err_upper, depth_err_lower
            FROM atmospheric_spectra
            WHERE spec_id = :sid AND depth_ppm IS NOT NULL
            ORDER BY wavelength_um
        """), {"sid": spec_id}).fetchall()

        if len(spectrum_rows) < 5:
            mark_failed(retrieval_id, "Insufficient spectrum points (requires > 5).")
            return

        # 2. Fetch planet & star physical parameters
        phys_row = session.execute(text("""
            SELECT p.planet_name, 
                   MAX(CASE WHEN pp.param_name='radius_earth' THEN pp.value END) as r_e,
                   MAX(CASE WHEN pp.param_name='mass_earth' THEN pp.value END) as m_e,
                   MAX(CASE WHEN pp.param_name='eq_temperature_k' THEN pp.value END) as teq,
                   MAX(CASE WHEN sp.param_name='radius_solar' THEN sp.value END) as r_s,
                   MAX(CASE WHEN sp.param_name='teff_best_k' THEN sp.value END) as teff
            FROM planets p
            JOIN stars s ON p.star_id = s.star_id
            LEFT JOIN planet_parameters pp ON pp.planet_id=p.planet_id AND pp.is_default=true
            LEFT JOIN star_parameters sp ON sp.star_id=s.star_id AND sp.is_default=true
            WHERE p.planet_id = :pid
            GROUP BY p.planet_name
        """), {"pid": planet_id}).fetchone()

        if not phys_row or not phys_row.r_e or not phys_row.m_e or not phys_row.r_s:
            mark_failed(retrieval_id, "Missing core physical parameters (radius, mass) for the planet/star.")
            return

        # 3. Setup PLATON input data
        # Wavelength bins in meters, depths fractional, errors fractional
        bins = []
        depths = []
        errors = []

        for row in spectrum_rows:
            wl_um = row.wavelength_um
            bw_um = row.bandwidth_um if row.bandwidth_um else 0.04 # fallback bandwidth
            
            # Convert um to meters
            wl_min = (wl_um - bw_um/2.0) * 1e-6
            wl_max = (wl_um + bw_um/2.0) * 1e-6
            
            err_up = row.depth_err_upper if row.depth_err_upper else 0
            err_lo = abs(row.depth_err_lower) if row.depth_err_lower else 0
            err = (err_up + err_lo) / 2.0
            if err <= 0:
                err = row.depth_ppm * 0.1 # fallback 10% error
            
            bins.append([wl_min, wl_max])
            depths.append(row.depth_ppm * 1e-6)
            errors.append(err * 1e-6)

        # 4. Initialize Retriever
        print(f"\\n[PLATON] Starting Nested Sampling Retrieval for spec_id={spec_id}")
        print(f"[PLATON] Loaded {len(bins)} spectrum points. This may take a few minutes...")
        retriever = CombinedRetriever()

        # Build initial guesses (in Jupiter/Solar units for PLATON)
        r_jup = phys_row.r_e * (R_earth / R_jup)
        m_jup = phys_row.m_e * (M_earth / M_jup)
        teq = phys_row.teq if phys_row.teq else 1000.0
        teff = phys_row.teff if phys_row.teff else 5000.0
        r_sun = phys_row.r_s

        fit_info = retriever.get_default_fit_info(
            Rs=r_sun,
            Mp=m_jup,
            Rp=r_jup,
            T=teq,
            logZ=0.0,
            CO_ratio=0.53,
            log_cloudtop_P=5.0,
            log_scat_factor=0.0,
            scat_slope=4.0,
            error_multiple=1.0,
            T_star=teff
        )

        # Setup nested sampling parameters
        # We lock star params and mass, and retrieve Rp, T, chemistry, and clouds
        fit_info.add_uniform_fit_param('Rp', 0.5 * r_jup, 2.0 * r_jup)
        fit_info.add_uniform_fit_param('T', 0.5 * teq, 2.0 * teq)
        fit_info.add_uniform_fit_param('logZ', -1.0, 3.0)
        fit_info.add_uniform_fit_param('CO_ratio', 0.1, 1.5)
        fit_info.add_uniform_fit_param('log_cloudtop_P', 1.0, 5.0)
        fit_info.add_uniform_fit_param('log_scat_factor', -1.0, 3.0)
        
        params_to_retrieve = ['Rp', 'T', 'logZ', 'CO_ratio', 'log_cloudtop_P', 'log_scat_factor']
        
        # Configure the nested sampler (using low numbers for rapid demonstration)
        # In a real scientific run, nlive would be 500-1000
        result = retriever.run_dynesty(
            transit_bins=bins, 
            transit_depths=depths, 
            transit_errors=errors,
            eclipse_bins=None,
            eclipse_depths=None,
            eclipse_errors=None,
            fit_info=fit_info, 
            nlive=150
        )
        
        best_fit_dict = {p: float(val) for p, val in zip(params_to_retrieve, result.x)}
        
        # Calculate log evidence
        evidence_ln_z = float(result.logz[-1]) if hasattr(result, 'logz') else 0.0
        
        # Save posterior data to file
        posterior_filename = f"posterior_{retrieval_id}.json"
        posterior_filepath = OUTPUT_DIR / posterior_filename
        
        # We save the samples and the weights so the frontend can plot a histogram/corner plot if needed
        samples = result.samples.tolist() if hasattr(result, 'samples') else []
        weights = result.importance_weights().tolist() if hasattr(result, 'importance_weights') else []
        
        posterior_data = {
            "params": params_to_retrieve,
            "samples": samples,
            "weights": weights,
            "best_fit": best_fit_dict,
            "evidence_ln_z": evidence_ln_z
        }
        
        with open(posterior_filepath, 'w') as f:
            json.dump(posterior_data, f)
            
        run_time_s = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Update DB
        session.execute(text("""
            UPDATE atmospheric_retrievals
            SET status = 'completed',
                run_time_seconds = :rt,
                best_fit_params = :bf,
                evidence_ln_z = :ez,
                posterior_file = :pf
            WHERE retrieval_id = :rid
        """), {
            "rt": run_time_s,
            "bf": json.dumps(best_fit_dict),
            "ez": evidence_ln_z,
            "pf": str(posterior_filepath.resolve()),
            "rid": retrieval_id
        })
        session.commit()
        print(f"[PLATON] Retrieval {retrieval_id} completed in {run_time_s:.1f}s")
        
    except Exception as e:
        err_str = str(e) + "\\n" + traceback.format_exc()
        mark_failed(retrieval_id, err_str)
        print(f"[PLATON] Error in retrieval {retrieval_id}:\n{err_str}")
    finally:
        session.close()

def mark_failed(retrieval_id: str, error_message: str):
    session = Session()
    try:
        session.execute(text("""
            UPDATE atmospheric_retrievals
            SET status = 'failed',
                error_message = :err
            WHERE retrieval_id = :rid
        """), {"err": error_message, "rid": retrieval_id})
        session.commit()
    except Exception:
        pass
    finally:
        session.close()
