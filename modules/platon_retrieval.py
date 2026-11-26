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
import math
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
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

def resolve_retrieval_physical_parameters(
    radius_earth: Optional[float],
    mass_earth: Optional[float],
    radius_solar: Optional[float],
    teff_best_k: Optional[float],
    eq_temperature_k: Optional[float] = None,
    semi_major_axis_au: Optional[float] = None,
    luminosity_solar: Optional[float] = None,
) -> Tuple[Optional[Dict[str, float]], List[str], Dict[str, str]]:
    """
    Validates and resolves physical parameters required for PLATON atmospheric retrieval.
    Never silently substitutes default values (e.g. 5000 K or 1000 K).
    
    Derivation rules:
    - Teff: Used if provided, positive, and finite. If missing, derived via Stefan-Boltzmann
      L_* = R_*^2 * (Teff / 5778)^4 if both radius_solar and luminosity_solar are available.
    - Teq: Used if provided, positive, and finite. If missing, derived assuming zero Bond albedo
      and uniform heat redistribution: Teq = Teff * sqrt(R_* / (2 * a)) if Teff, radius_solar,
      and semi_major_axis_au are all valid.
    
    Returns:
        (resolved_params_dict, missing_parameter_names, derivation_provenance)
    """
    missing: List[str] = []
    provenance: Dict[str, str] = {}

    def is_valid_num(val: Any) -> bool:
        if val is None:
            return False
        try:
            f = float(val)
            return not (math.isnan(f) or math.isinf(f)) and f > 0
        except (ValueError, TypeError):
            return False

    # 1. Planet Radius
    if is_valid_num(radius_earth):
        r_e = float(radius_earth)
        provenance["radius_earth"] = "catalog"
    else:
        r_e = None
        missing.append("radius_earth")

    # 2. Planet Mass
    if is_valid_num(mass_earth):
        m_e = float(mass_earth)
        provenance["mass_earth"] = "catalog"
    else:
        m_e = None
        missing.append("mass_earth")

    # 3. Stellar Radius
    if is_valid_num(radius_solar):
        r_s = float(radius_solar)
        provenance["radius_solar"] = "catalog"
    else:
        r_s = None
        missing.append("radius_solar")

    # 4. Stellar Effective Temperature
    teff: Optional[float] = None
    if is_valid_num(teff_best_k):
        teff = float(teff_best_k)
        provenance["teff_k"] = "catalog"
    elif is_valid_num(radius_solar) and is_valid_num(luminosity_solar):
        # Derive via Stefan-Boltzmann: Teff = 5778 * (L_* / R_*^2)^(1/4)
        derived_teff = 5778.0 * ((float(luminosity_solar) / (float(radius_solar) ** 2.0)) ** 0.25)
        if derived_teff > 0 and not math.isnan(derived_teff):
            teff = float(derived_teff)
            provenance["teff_k"] = "derived_stefan_boltzmann"
        else:
            missing.append("teff_best_k")
    else:
        missing.append("teff_best_k")

    # 5. Planetary Equilibrium Temperature
    teq: Optional[float] = None
    if is_valid_num(eq_temperature_k):
        teq = float(eq_temperature_k)
        provenance["eq_temperature_k"] = "catalog"
    elif teff is not None and is_valid_num(radius_solar) and is_valid_num(semi_major_axis_au):
        # 1 R_sun in AU = 0.00465047 AU
        # Teq = Teff * sqrt(R_*_au / (2 * a_au))
        r_s_au = float(radius_solar) * 0.00465047
        sma = float(semi_major_axis_au)
        derived_teq = teff * math.sqrt(r_s_au / (2.0 * sma))
        if derived_teq > 0 and not math.isnan(derived_teq):
            teq = float(derived_teq)
            provenance["eq_temperature_k"] = "derived_equilibrium_zero_albedo"
        else:
            missing.append("eq_temperature_k")
    else:
        missing.append("eq_temperature_k")

    if missing:
        return None, missing, provenance

    resolved = {
        "radius_earth": r_e,
        "mass_earth": m_e,
        "radius_solar": r_s,
        "teff_k": teff,
        "eq_temperature_k": teq,
    }
    return resolved, [], provenance


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
                   MAX(CASE WHEN pp.param_name='semi_major_axis_au' THEN pp.value END) as sma_au,
                   MAX(CASE WHEN sp.param_name='radius_solar' THEN sp.value END) as r_s,
                   MAX(CASE WHEN sp.param_name='teff_best_k' THEN sp.value END) as teff,
                   MAX(CASE WHEN sp.param_name='luminosity_solar' THEN sp.value END) as lum_s
            FROM planets p
            JOIN stars s ON p.star_id = s.star_id
            LEFT JOIN planet_parameters pp ON pp.planet_id=p.planet_id AND pp.is_default=true
            LEFT JOIN star_parameters sp ON sp.star_id=s.star_id AND sp.is_default=true
            WHERE p.planet_id = :pid
            GROUP BY p.planet_name
        """), {"pid": planet_id}).fetchone()

        if not phys_row:
            mark_failed(retrieval_id, "Planet or star record not found in database.", missing_parameters=["planet_record"])
            return

        resolved_params, missing_params, param_prov = resolve_retrieval_physical_parameters(
            radius_earth=phys_row.r_e,
            mass_earth=phys_row.m_e,
            radius_solar=phys_row.r_s,
            teff_best_k=phys_row.teff,
            eq_temperature_k=phys_row.teq,
            semi_major_axis_au=phys_row.sma_au,
            luminosity_solar=phys_row.lum_s,
        )

        if not resolved_params:
            err_msg = (
                f"Missing required physical parameters for atmospheric retrieval: {', '.join(missing_params)}. "
                "Silent numerical defaults (e.g. Teff=5000 K, Teq=1000 K) are strictly forbidden."
            )
            mark_failed(retrieval_id, err_msg, missing_parameters=missing_params)
            return

        planet_name = phys_row.planet_name
        r_jup = resolved_params["radius_earth"] * (R_earth / R_jup)
        m_jup = resolved_params["mass_earth"] * (M_earth / M_jup)
        teq = resolved_params["eq_temperature_k"]
        teff = resolved_params["teff_k"]
        r_sun = resolved_params["radius_solar"]

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
            temperature_params={"T_guess_k": teq, "derivation_provenance": param_prov.get("eq_temperature_k", "catalog")},
            priors=priors_dict,
            sampler_name="PyMultiNest",
            random_seed=random_seed,
            sampler_seed_deterministic=False,
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
        # NOTE: PRNG is initialized at the host Python/NumPy level for worker isolation,
        # but PLATON CombinedRetriever does NOT expose random seed control to the underlying
        # MultiNest C/Fortran library. Stochastic determinism cannot be guaranteed via the public API.
        print(f"\n[PLATON] Starting Nested Sampling Retrieval for spec_id={spec_id} (Seed={random_seed} [API non-deterministic])")
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

def mark_failed(retrieval_id: str, error_message: str, missing_parameters: Optional[List[str]] = None):
    session = Session()
    try:
        diag = {
            "converged": False,
            "error": error_message,
            "missing_parameters": missing_parameters or [],
            "diagnostics_notes": ["Execution aborted: physical parameter prerequisites not met."] if missing_parameters else ["Execution failed during retrieval."],
        }
        session.execute(text("""
            UPDATE atmospheric_retrievals
            SET status = 'failed',
                reproducibility_status = 'reproducibility_metadata_incomplete',
                error_message = :err,
                convergence_diagnostics = :diag
            WHERE retrieval_id = :rid
        """), {
            "err": error_message,
            "diag": json.dumps(diag),
            "rid": retrieval_id,
        })
        session.commit()
    except Exception:
        pass
    finally:
        session.close()
