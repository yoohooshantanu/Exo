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
    from platon.constants import R_jup, M_jup, R_earth, M_earth, R_sun
except ImportError:
    CombinedRetriever = None
    R_jup = 7.1492e7
    M_jup = 1.898e27
    R_earth = 6.3781e6
    M_earth = 5.972e24
    R_sun = 6.957e8

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
        provenance["eq_temperature_assumptions"] = {
            "source": "catalog",
            "bond_albedo": "archival_catalog_default",
            "heat_redistribution": "archival_catalog_default",
            "notes": "Direct archival catalogue value; specific albedo and recirculation parameters governed by source discovery paper.",
        }
    elif teff is not None and is_valid_num(radius_solar) and is_valid_num(semi_major_axis_au):
        # 1 R_sun in AU = 0.00465047 AU
        # Teq = Teff * sqrt(R_*_au / (2 * a_au))
        # Physical assumptions:
        # 1. Zero Bond albedo (A_B = 0.0) -> maximum absorbed incident stellar flux.
        # 2. Uniform full-sphere 4pi steradian heat redistribution (f = 1/4 factor in Teq = Teff * sqrt(R_* / 2a)).
        # 3. Blackbody emissivity epsilon = 1.0 without greenhouse warming or atmospheric circulation models.
        # 4. Circular orbit approximation at semi-major axis (neglecting orbital eccentricity).
        # 5. Zero internal heat flux (tidal or radiogenic).
        r_s_au = float(radius_solar) * 0.00465047
        sma = float(semi_major_axis_au)
        derived_teq = teff * math.sqrt(r_s_au / (2.0 * sma))
        if derived_teq > 0 and not math.isnan(derived_teq):
            teq = float(derived_teq)
            provenance["eq_temperature_k"] = "derived_equilibrium_zero_albedo"
            provenance["eq_temperature_assumptions"] = {
                "source": "derived",
                "bond_albedo": 0.0,
                "heat_redistribution": "uniform_full_sphere_4pi (f = 1/4)",
                "emissivity": 1.0,
                "greenhouse_amplification": 0.0,
                "internal_heating": 0.0,
                "orbital_geometry": "circular_approximation_at_semi_major_axis",
                "formula": "T_eq = T_eff * sqrt(R_* / (2 * a))",
            }
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
        r_p_m = float(resolved_params["radius_earth"]) * R_earth
        m_p_kg = float(resolved_params["mass_earth"]) * M_earth
        r_s_m = float(resolved_params["radius_solar"]) * R_sun
        teq = float(resolved_params["eq_temperature_k"])
        teff = float(resolved_params["teff_k"])

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
                err = abs(row.depth_ppm) * 0.1

            # Convert depth & error to unitless transit depth fraction (Rp/Rs)^2
            d_val = float(row.depth_ppm)
            e_val = float(err)
            if abs(d_val) > 50.0:
                # True parts-per-million (ppm) -> divide by 1e6
                scale = 1e-6
            elif abs(d_val) > 0.001:
                # Percentage (%) -> divide by 100
                scale = 1e-2
            else:
                # Direct fractional depth
                scale = 1.0

            bins.append([wl_min_um * 1e-6, wl_max_um * 1e-6])
            depths.append(d_val * scale)
            errors.append(e_val * scale)

        # 4. Formulate explicit priors & bounds within physical & model grid ranges
        # PLATON opacity grid temperature limits are strictly [200.0, 3000.0] K.
        # Planetary radius prior bounds in SI meters.
        rp_min_m = round(max(0.05 * R_jup, 0.5 * r_p_m), 1)
        rp_max_m = round(min(3.0 * R_jup, 2.0 * r_p_m), 1)
        if rp_min_m >= rp_max_m:
            rp_min_m = round(r_p_m * 0.8, 1)
            rp_max_m = round(r_p_m * 1.2, 1)

        t_min = round(max(200.0, 0.5 * teq), 1)
        t_max = round(min(3000.0, 2.0 * teq), 1)
        if t_min >= t_max:
            t_min = round(max(200.0, teq - 200.0), 1)
            t_max = round(min(3000.0, teq + 200.0), 1)

        priors_dict = {
            "Rp": {
                "distribution": "uniform",
                "bounds": [rp_min_m, rp_max_m],
                "unit": "m",
                "description": "Planetary transit radius in meters (SI)",
            },
            "T": {
                "distribution": "uniform",
                "bounds": [t_min, t_max],
                "unit": "K",
                "description": "Isothermal atmospheric temperature",
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
            temperature_params={
                "T_guess_k": teq,
                "derivation_provenance": param_prov.get("eq_temperature_k", "catalog"),
                "assumptions": param_prov.get("eq_temperature_assumptions", {}),
            },
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
        # Note: PYTHONHASHSEED is not set here because it is only read once by the Python
        # runtime at interpreter initialization; modifying it inside a running process is ineffective.
        print(f"\n[PLATON] Starting Nested Sampling Retrieval for spec_id={spec_id} (Seed={random_seed} [API non-deterministic])")
        import numpy as np
        import random
        if random_seed is not None:
            np.random.seed(random_seed)
            random.seed(random_seed)

        retriever = CombinedRetriever()

        fit_info = retriever.get_default_fit_info(
            Rs=r_s_m,
            Mp=m_p_kg,
            Rp=r_p_m,
            T=teq,
            logZ=0.0,
            CO_ratio=0.53,
            log_cloudtop_P=5.0,
            log_scatt_factor=0.0,
            scatt_slope=4.0,
            error_multiple=1.0,
            T_star=teff
        )

        for param_name, pdef in priors_dict.items():
            fit_info.add_uniform_fit_param(param_name, pdef["bounds"][0], pdef["bounds"][1])

        params_to_retrieve = list(priors_dict.keys())

        result = retriever.run_multinest(
            transit_bins=np.asarray(bins, dtype=float),
            transit_depths=np.asarray(depths, dtype=float),
            transit_errors=np.asarray(errors, dtype=float),
            eclipse_bins=None,
            eclipse_depths=None,
            eclipse_errors=None,
            fit_info=fit_info,
            nlive=nlive,
        )

        dyn_res = getattr(result, "results", getattr(result, "result", result))
        samples = result.samples.tolist() if hasattr(result, 'samples') else (dyn_res.samples.tolist() if hasattr(dyn_res, 'samples') else [])

        if hasattr(result, 'final_logz') and result.final_logz is not None:
            evidence_ln_z = float(result.final_logz)
        elif hasattr(result, 'logz') and len(result.logz) > 0:
            evidence_ln_z = float(result.logz[-1])
        elif hasattr(dyn_res, 'logz') and len(dyn_res.logz) > 0:
            evidence_ln_z = float(dyn_res.logz[-1])
        else:
            evidence_ln_z = None

        if hasattr(result, 'logzerr') and len(result.logzerr) > 0:
            evidence_err = float(result.logzerr[-1])
        elif hasattr(dyn_res, 'logzerr') and len(dyn_res.logzerr) > 0:
            evidence_err = float(dyn_res.logzerr[-1])
        else:
            evidence_err = None

        if hasattr(result, 'weights') and result.weights is not None:
            weights = np.asarray(result.weights).tolist()
        elif hasattr(dyn_res, 'weights') and dyn_res.weights is not None:
            weights = np.asarray(dyn_res.weights).tolist()
        elif hasattr(dyn_res, 'logwt') and logz_arr is not None and len(logz_arr) > 0:
            weights = np.exp(dyn_res.logwt - logz_arr[-1]).tolist()
        else:
            weights = []

        if hasattr(result, 'logp') and len(result.logp) > 0 and len(samples) > 0:
            best_idx = int(np.argmax(result.logp))
            best_fit_dict = {p: float(samples[best_idx][i]) for i, p in enumerate(params_to_retrieve)}
        elif hasattr(result, 'best_fit_params') and result.best_fit_params:
            best_fit_dict = {p: float(val) for p, val in zip(params_to_retrieve, result.best_fit_params)}
        elif hasattr(dyn_res, 'logl') and len(dyn_res.logl) > 0 and len(samples) > 0:
            best_idx = int(np.argmax(dyn_res.logl))
            best_fit_dict = {p: float(samples[best_idx][i]) for i, p in enumerate(params_to_retrieve)}
        elif hasattr(result, 'x'):
            best_fit_dict = {p: float(val) for p, val in zip(params_to_retrieve, result.x)}
        else:
            best_fit_dict = {}

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
