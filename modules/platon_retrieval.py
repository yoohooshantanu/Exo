"""
modules/platon_retrieval.py

A background worker module for running full Bayesian atmospheric retrievals
using PLATON (PLanetary Atmospheric Tool for Observer Noobs).

Includes full reproducibility and provenance tracking conforming to
retrieval reproducibility standards (Doriann Blain / petitRADTRANS recommendations):
- Config recorded before execution
- Species-level opacity provenance
- Exact priors and parameter bounds
- Sampler random seed and metaparameters
- Convergence diagnostics and reproducibility verification
- Standalone config JSON export
"""

import json, uuid
import traceback
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from modules.db_sync import create_sync_engine
from modules.config import RETRIEVAL_OUTPUT_DIR
from modules.retrieval_reproducibility import (
    create_retrieval_configuration,
    evaluate_retrieval_reproducibility,
    ConvergenceDiagnostics,
    compute_kish_effective_sample_size,
)

from dotenv import load_dotenv

try:
    from platon.retriever import CombinedRetriever
    from platon.constants import R_jup, M_jup, R_earth, M_earth
except ImportError:
    CombinedRetriever = None
    R_jup = 7.1492e7
    M_jup = 1.898e27
    R_earth = 6.3781e6
    M_earth = 5.972e24

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

engine = create_sync_engine()
Session = sessionmaker(bind=engine)

OUTPUT_DIR = RETRIEVAL_OUTPUT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_RETRIEVAL_SEED = 42

def new_id(): return str(uuid.uuid4())

def run_platon_retrieval(
    planet_id: str,
    spec_id: str,
    retrieval_id: str,
    random_seed: int = DEFAULT_RETRIEVAL_SEED,
    nlive: int = 500,
):
    """
    Runs a nested sampling retrieval using PLATON with complete reproducibility tracking.
    Intended to be run as a background task.
    """
    if CombinedRetriever is None:
        mark_failed(retrieval_id, "PLATON library is not installed in the execution environment.")
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
            mark_failed(retrieval_id, "Insufficient spectrum points (requires >= 5).")
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

        planet_name = phys_row.planet_name
        r_jup = phys_row.r_e * (R_earth / R_jup)
        m_jup = phys_row.m_e * (M_earth / M_jup)
        teq = phys_row.teq if phys_row.teq else 1000.0
        teff = phys_row.teff if phys_row.teff else 5000.0
        r_sun = phys_row.r_s

        # 3. Setup PLATON input data
        bins = []
        depths = []
        errors = []
        wl_min_total = float("inf")
        wl_max_total = float("-inf")

        for row in spectrum_rows:
            wl_um = row.wavelength_um
            bw_um = row.bandwidth_um if row.bandwidth_um else 0.04
            
            wl_min_um = wl_um - bw_um / 2.0
            wl_max_um = wl_um + bw_um / 2.0
            wl_min_total = min(wl_min_total, wl_min_um)
            wl_max_total = max(wl_max_total, wl_max_um)

            err_up = row.depth_err_upper if row.depth_err_upper else 0
            err_lo = abs(row.depth_err_lower) if row.depth_err_lower else 0
            err = (err_up + err_lo) / 2.0
            if err <= 0:
                err = row.depth_ppm * 0.1

            bins.append([wl_min_um * 1e-6, wl_max_um * 1e-6])
            depths.append(row.depth_ppm * 1e-6)
            errors.append(err * 1e-6)

        # 4. Formulate explicit priors & bounds
        priors_dict = {
            "Rp": {
                "distribution": "uniform",
                "bounds": [round(0.5 * r_jup, 4), round(2.0 * r_jup, 4)],
                "unit": "R_jup",
                "description": "Planetary transit radius in Jupiter radii",
            },
            "T": {
                "distribution": "uniform",
                "bounds": [round(0.5 * teq, 1), round(2.0 * teq, 1)],
                "unit": "K",
                "description": "Isothermal atmospheric temperature",
            },
            "logZ": {
                "distribution": "uniform",
                "bounds": [-1.0, 3.0],
                "unit": "dex",
                "description": "Atmospheric metallicity [M/H] relative to solar",
            },
            "CO_ratio": {
                "distribution": "uniform",
                "bounds": [0.1, 1.5],
                "unit": "dimensionless",
                "description": "Atmospheric Carbon to Oxygen elemental abundance ratio",
            },
            "log_cloudtop_P": {
                "distribution": "uniform",
                "bounds": [1.0, 5.0],
                "unit": "log10(Pa)",
                "description": "Opaque cloud top pressure",
            },
            "log_scat_factor": {
                "distribution": "uniform",
                "bounds": [-1.0, 3.0],
                "unit": "log10(dimensionless)",
                "description": "Rayleigh scattering enhancement factor",
            },
        }

        chemical_species = ["H2O", "CO", "CO2", "CH4"]

        # 5. Create and persist configuration record BEFORE execution
        retrieval_config = create_retrieval_configuration(
            retrieval_id=retrieval_id,
            spec_id=spec_id,
            planet_id=planet_id,
            planet_name=planet_name,
            model_name="PLATON",
            model_version="1.0.0",
            chemical_species=chemical_species,
            temperature_profile_type="isothermal",
            temperature_params={"T_guess_k": teq},
            priors=priors_dict,
            sampler_name="PyMultiNest",
            random_seed=random_seed,
            nlive=nlive,
            wavelength_range_um=(round(wl_min_total, 2), round(wl_max_total, 2)),
        )

        config_filename = f"config_{retrieval_id}.json"
        config_filepath = OUTPUT_DIR / config_filename
        retrieval_config.export_to_file(config_filepath)

        # Record pre-execution state in database
        session.execute(text("""
            UPDATE atmospheric_retrievals
            SET status = 'running',
                reproducibility_status = 'configuration_recorded',
                configuration_record = :cfg,
                opacity_provenance = :opc,
                sampler_name = 'PyMultiNest',
                sampler_version = '1.0',
                random_seed = :seed,
                sampler_parameters = :sparms,
                priors_record = :prs
            WHERE retrieval_id = :rid
        """), {
            "cfg": json.dumps(retrieval_config.to_dict()),
            "opc": json.dumps(retrieval_config.opacity_provenance),
            "seed": random_seed,
            "sparms": json.dumps(retrieval_config.sampler),
            "prs": json.dumps(priors_dict),
            "rid": retrieval_id,
        })
        session.commit()

        # 6. Initialize Retriever and run Nested Sampling
        print(f"\n[PLATON] Starting Nested Sampling Retrieval for spec_id={spec_id} (Seed={random_seed})")
        import numpy as np
        import random, os
        if random_seed is not None:
            np.random.seed(random_seed)
            random.seed(random_seed)
            os.environ["PYTHONHASHSEED"] = str(random_seed)

        retriever = CombinedRetriever()

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

        for param_name, pdef in priors_dict.items():
            fit_info.add_uniform_fit_param(param_name, pdef["bounds"][0], pdef["bounds"][1])

        params_to_retrieve = list(priors_dict.keys())

        result = retriever.run_multinest(
            bins=bins, depths=depths, errors=errors,
            plot_best_fit=False,
            nlive=nlive,
            eclipse_bins=None,
            eclipse_depths=None,
            eclipse_errors=None,
            fit_info=fit_info
        )

        best_fit_dict = {p: float(val) for p, val in zip(params_to_retrieve, result.x)} if hasattr(result, 'x') else {}
        evidence_ln_z = float(result.logz[-1]) if (hasattr(result, 'logz') and len(result.logz) > 0) else None
        evidence_err = float(result.logzerr[-1]) if (hasattr(result, 'logzerr') and len(result.logzerr) > 0) else None

        samples = result.samples.tolist() if hasattr(result, 'samples') else []
        weights = result.importance_weights().tolist() if hasattr(result, 'importance_weights') else []

        # 7. Evaluate convergence and reproducibility with Kish ESS and defensible criteria
        n_samples = len(samples)
        effective_sample_size = compute_kish_effective_sample_size(weights)

        converged = bool(
            evidence_ln_z is not None
            and evidence_err is not None
            and evidence_err <= 0.5
            and effective_sample_size is not None
            and effective_sample_size >= 100.0
            and n_samples >= 100
        )
        warnings = []
        if not converged:
            if evidence_ln_z is None:
                warnings.append("Sampler evidence log(Z) could not be determined.")
            if evidence_err is None:
                warnings.append("Sampler evidence uncertainty is unavailable.")
            elif evidence_err > 0.5:
                warnings.append(f"Evidence uncertainty ({evidence_err:.3f}) exceeds tolerance (0.5).")
            if effective_sample_size is None or effective_sample_size < 100.0:
                warnings.append(f"Effective sample size ({effective_sample_size}) is below acceptable threshold (100.0).")
            if n_samples < 100:
                warnings.append(f"Sample count ({n_samples}) is below live threshold.")

        diagnostics = ConvergenceDiagnostics(
            converged=converged,
            evidence_ln_z=evidence_ln_z,
            evidence_err=evidence_err,
            n_samples=n_samples,
            effective_sample_size=effective_sample_size,
            warnings=warnings,
            diagnostics_notes=["Nested sampling evidence converged within tolerance."] if converged else ["Convergence not established."],
        )

        repro_status, repro_notes = evaluate_retrieval_reproducibility(retrieval_config, diagnostics, require_disk_verification=True)
        retrieval_config.reproducibility_status = repro_status
        retrieval_config.reproducibility_notes = repro_notes
        retrieval_config.convergence = {
            "converged": diagnostics.converged,
            "evidence_ln_z": diagnostics.evidence_ln_z,
            "evidence_err": diagnostics.evidence_err,
            "n_samples": diagnostics.n_samples,
            "effective_sample_size": diagnostics.effective_sample_size,
            "warnings": diagnostics.warnings,
        }

        # Re-export final verified configuration file
        retrieval_config.export_to_file(config_filepath)

        # Save posterior data
        posterior_filename = f"posterior_{retrieval_id}.json"
        posterior_filepath = OUTPUT_DIR / posterior_filename

        posterior_data = {
            "retrieval_id": retrieval_id,
            "params": params_to_retrieve,
            "samples": samples,
            "weights": weights,
            "best_fit": best_fit_dict,
            "evidence_ln_z": evidence_ln_z,
            "evidence_err": evidence_err,
            "reproducibility_status": repro_status,
            "random_seed": random_seed,
            "config_file": config_filename,
        }

        with open(posterior_filepath, 'w', encoding='utf-8') as f:
            json.dump(posterior_data, f)

        run_time_s = (datetime.now(timezone.utc) - start_time).total_seconds()
        stored_path = posterior_filepath.relative_to(PROJECT_ROOT).as_posix()

        # Update database with complete provenance and reproducibility status
        session.execute(text("""
            UPDATE atmospheric_retrievals
            SET status = 'completed',
                reproducibility_status = :rps,
                run_time_seconds = :rt,
                best_fit_params = :bf,
                evidence_ln_z = :ez,
                posterior_file = :pf,
                configuration_record = :cfg,
                convergence_diagnostics = :conv
            WHERE retrieval_id = :rid
        """), {
            "rps": repro_status,
            "rt": run_time_s,
            "bf": json.dumps(best_fit_dict),
            "ez": evidence_ln_z,
            "pf": stored_path,
            "cfg": json.dumps(retrieval_config.to_dict()),
            "conv": json.dumps(retrieval_config.convergence),
            "rid": retrieval_id,
        })
        session.commit()
        print(f"[PLATON] Retrieval {retrieval_id} completed ({repro_status}) in {run_time_s:.1f}s")

    except Exception as e:
        err_str = str(e) + "\n" + traceback.format_exc()
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
                reproducibility_status = 'reproducibility_metadata_incomplete',
                error_message = :err
            WHERE retrieval_id = :rid
        """), {"err": error_message, "rid": retrieval_id})
        session.commit()
    except Exception:
        pass
    finally:
        session.close()
