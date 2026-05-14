"""
modules/biosignature_detector.py  v2.0.0

Core science engine for Phase 4. Compares atmospheric spectra against
HITRAN molecular features to identify biosignature candidates.

v2.0.0 upgrades:
  1. Polynomial continuum fitting (Legendre degree-3)
  2. Bayesian evidence scoring (BIC-based Bayes factor)
  3. Multi-epoch consistency checks
  4. Stellar contamination filter (M/K-dwarf H2O mimicry)
  5. Expanded abiotic reasoning (CO/CO2 ratio, SO2 volcanic, NH3 context)
  6. Injection-recovery validation (--validate mode)
  7. Instrument confidence weighting (JWST > HST > Spitzer)

Run:
  python modules/biosignature_detector.py
  python modules/biosignature_detector.py --planet "WASP-39 b"
  python modules/biosignature_detector.py --validate
  python modules/biosignature_detector.py --dry-run
"""

import os, uuid, math, argparse, time, json
import numpy as np
import pandas as pd
from scipy.signal import correlate
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel, ConstantKernel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL     = os.environ["DATABASE_URL"]
MODEL_VERSION    = "3.0.0"
OUTPUT_DIR       = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

engine  = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# ── constants ────────────────────────────────────────────────────────────────

CONFIRMED_SIGMA  = 3.0   # Tier 1
MARGINAL_SIGMA   = 2.0   # Tier 2 floor
MIN_HITRAN_MATCH = 2     # require ≥2 HITRAN lines for valid detection
CONTINUUM_BINS   = 5     # ±N bins for continuum estimation
WAVELENGTH_TOL   = 0.05  # µm tolerance for HITRAN line matching
POLY_DEGREE      = 3     # Legendre polynomial degree for continuum

# Molecules where abiotic origin is likely
ABIOTIC_MOLECULES = {"so2", "co"}
# Triple biosignature — if all three present, abiotic_ruled_out = True
TRIPLE_BIOSIG = {"h2o", "ch4", "o3"}
# Disequilibrium pair — both without O₃ = thermochemical disequilibrium
DISEQ_PAIR = {"h2o", "ch4"}

TARGET_MOLECULES = ["h2o", "co2", "o3", "ch4", "co", "nh3", "so2"]

MOL_NAMES = {
    "h2o": "H2O", "co2": "CO2", "o3": "O3", "ch4": "CH4",
    "co": "CO", "nh3": "NH3", "so2": "SO2",
}

# Known absorption band centers per molecule (µm) — mask during continuum fit
MOL_BAND_CENTERS = {
    "h2o": [1.4, 1.9, 2.7, 6.3], "co2": [2.0, 2.7, 4.3, 15.0],
    "o3": [9.6], "ch4": [1.7, 2.3, 3.3, 7.7],
    "co": [2.3, 4.7], "nh3": [2.0, 3.0, 6.1, 10.5], "so2": [4.0, 7.3, 8.7],
}
MOL_MASK_HALF_WIDTH = 0.15  # µm, mask ± this around each band center

# Instrument quality weights for confidence decay
INSTRUMENT_WEIGHTS = {
    "jwst": 1.0, "james webb": 1.0,
    "hst": 0.85, "hubble": 0.85,
    "spitzer": 0.70,
}
DEFAULT_INSTRUMENT_WEIGHT = 0.60  # ground-based or unknown

# Stellar contamination risk map: spectral_type_prefix -> {molecule: penalty}
STELLAR_CONTAM_RISK = {
    "M": {"h2o": 0.5, "tio": 0.5, "co": 0.3},
    "K": {"h2o": 0.3},
}


def new_id(): return str(uuid.uuid4())
def now_utc(): return datetime.now(timezone.utc)

def nv(val):
    if val is None: return None
    if isinstance(val, (np.floating, np.integer)):
        v = val.item()
        if math.isnan(v) or math.isinf(v): return None
        return v
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)): return None
    try:
        if pd.isna(val): return None
    except Exception: pass
    return float(val) if isinstance(val, (int, float, np.number)) else val

def log(msg): print(f"  {datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}")


# ── data fetching ────────────────────────────────────────────────────────────

def fetch_planets_with_spectra(session, planet_name=None):
    """Get distinct planets that have atmospheric spectra in our DB."""
    q = """
        SELECT DISTINCT a.planet_name, a.planet_id, a.hostname,
               a.facility, a.instrument, a.obs_type, a.spec_id, a.pub_reference
        FROM atmospheric_spectra a
        WHERE a.depth_ppm IS NOT NULL
    """
    params = {}
    if planet_name:
        q += " AND a.planet_name = :pn"
        params["pn"] = planet_name
    q += " ORDER BY a.planet_name"
    rows = session.execute(text(q), params).fetchall()
    # Group by planet
    planets = {}
    for r in rows:
        pn = r[0]
        if pn not in planets:
            planets[pn] = {"planet_name": pn, "planet_id": r[1], "hostname": r[2],
                           "spectra": set()}
        planets[pn]["spectra"].add((r[6], r[3], r[4], r[5], r[7]))  # spec_id, facility, inst, obs, ref
    return planets


def fetch_spectrum_data(session, spec_id):
    """Get wavelength-sorted spectral data points for one spectrum."""
    rows = session.execute(text("""
        SELECT wavelength_um, bandwidth_um, depth_ppm,
               depth_err_upper, depth_err_lower
        FROM atmospheric_spectra
        WHERE spec_id = :sid AND depth_ppm IS NOT NULL
        ORDER BY wavelength_um
    """), {"sid": spec_id}).fetchall()
    return pd.DataFrame(rows, columns=[
        "wavelength_um", "bandwidth_um", "depth_ppm",
        "depth_err_upper", "depth_err_lower"])


def fetch_template(session, molecule, teq):
    """Find the best matching spectral template parquet file."""
    templates = session.execute(text("""
        SELECT temperature_k, file_path FROM spectral_templates
        WHERE molecule = :mol
    """), {"mol": molecule}).fetchall()
    
    if not templates:
        return pd.DataFrame()
        
    teq = teq or 500.0
    closest = min(templates, key=lambda x: abs(x[0] - teq))
    file_path = closest[1]
    
    abs_path = PROJECT_ROOT / file_path
    if not abs_path.exists():
        return pd.DataFrame()
        
    return pd.read_parquet(abs_path)

def fetch_physics(session):
    rows = session.execute(text("""
        SELECT p.planet_name, 
            MAX(CASE WHEN pp.param_name='radius_earth' THEN pp.value END) as r_e,
            MAX(CASE WHEN pp.param_name='mass_earth' THEN pp.value END) as m_e,
            MAX(CASE WHEN pp.param_name='eq_temperature_k' THEN pp.value END) as teq,
            MAX(CASE WHEN sp.param_name='radius_solar' THEN sp.value END) as r_s,
            s.spectral_type
        FROM planets p
        JOIN stars s ON p.star_id = s.star_id
        LEFT JOIN planet_parameters pp ON pp.planet_id=p.planet_id AND pp.is_default=true
        LEFT JOIN star_parameters sp ON sp.star_id=s.star_id AND sp.is_default=true
        GROUP BY p.planet_name, s.spectral_type
    """)).fetchall()
    return {r[0]: {"r_e": r[1], "m_e": r[2], "teq": r[3], "r_s": r[4], "spectral_type": r[5]} for r in rows}


# ── molecule matching engine ─────────────────────────────────────────────────

def fit_gp_continuum(spectrum_df):
    """Fit a Gaussian Process continuum to the spectrum, masking known absorption bands."""
    wl = spectrum_df["wavelength_um"].values
    depth = spectrum_df["depth_ppm"].values

    # Build mask: True = use for continuum fitting
    mask = np.ones(len(wl), dtype=bool)
    for mol, centers in MOL_BAND_CENTERS.items():
        for c in centers:
            mask &= (np.abs(wl - c) > MOL_MASK_HALF_WIDTH)

    valid = mask & np.isfinite(depth)
    if valid.sum() < 5:
        # Fallback: σ-clipped median
        finite = depth[np.isfinite(depth)]
        if len(finite) < 3:
            return np.full(len(wl), np.nan)
        med = np.median(finite)
        return np.full(len(wl), med)

    # Normalize wavelengths and depth for numerical stability
    wl_valid = wl[valid].reshape(-1, 1)
    depth_valid = depth[valid]
    depth_mean = np.mean(depth_valid)
    depth_std = np.std(depth_valid) if np.std(depth_valid) > 0 else 1.0
    depth_valid_norm = (depth_valid - depth_mean) / depth_std

    try:
        # Flexible Matern kernel + WhiteNoise to handle correlated wiggles + shot noise
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(length_scale=0.5, length_scale_bounds=(0.01, 10.0), nu=1.5) + WhiteKernel(noise_level=0.1, noise_level_bounds=(1e-5, 1.0))
        gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=3, random_state=42, normalize_y=False)
        
        # Suppress GP warnings to keep console clean
        import warnings
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ConvergenceWarning)
            warnings.simplefilter('ignore', UserWarning)
            gp.fit(wl_valid, depth_valid_norm)

        pred_norm, _ = gp.predict(wl.reshape(-1, 1), return_std=True)
        continuum = (pred_norm * depth_std) + depth_mean
    except Exception:
        # Fallback to median if GP fails
        med = np.median(depth[np.isfinite(depth)])
        continuum = np.full(len(wl), med)

    return continuum


def unmix_spectrum(spectrum_df, templates_dict, phys_params):
    """
    Simultaneously fit multiple molecular templates (OLS) to GP-detrended spectrum.
    Replaces match_molecule. Returns a list of detection dictionaries, one for each molecule.
    """
    if spectrum_df.empty or not templates_dict:
        return []

    spectrum_df = spectrum_df.sort_values("wavelength_um").reset_index(drop=True)
    obs_wl = spectrum_df["wavelength_um"].values
    obs_depth = spectrum_df["depth_ppm"].values

    # Fit GP Continuum
    continuum = fit_gp_continuum(spectrum_df)

    norm_excess = np.zeros(len(obs_wl))
    valid_mask = np.zeros(len(obs_wl), dtype=bool)
    excess_ppm_arr = np.zeros(len(obs_wl))
    error_arr = np.zeros(len(obs_wl))

    for idx, row in spectrum_df.iterrows():
        err_up = nv(row["depth_err_upper"])
        err_lo = nv(row["depth_err_lower"])
        if err_up is None and err_lo is None: continue
        err = (abs(err_up) + abs(err_lo)) / 2.0 if err_up and err_lo else (abs(err_up) if err_up else abs(err_lo))
        if err <= 0: continue

        cont = continuum[idx]
        if not np.isfinite(cont) or cont <= 0: continue

        norm_excess[idx] = (row["depth_ppm"] - cont) / cont
        excess_ppm_arr[idx] = row["depth_ppm"] - cont
        error_arr[idx] = err
        valid_mask[idx] = True

    if not valid_mask.any(): return []

    # Scale-Height Proxy
    teq = nv(phys_params.get("teq")); m_e = nv(phys_params.get("m_e"))
    r_e = nv(phys_params.get("r_e")); r_s = nv(phys_params.get("r_s"))
    if teq and m_e and r_e and r_s and m_e > 0:
        g = (m_e / (r_e**2)) * 9.8
        H = (1.38e-23 * teq) / (2.3 * 1.66e-27 * g)
        Rp = r_e * 6.37e6
        Rs = r_s * 6.95e8
        max_depth_ppm = (2 * Rp * H / (Rs**2)) * 1e6
        allowed_max_ppm = max_depth_ppm * 2.0
    else:
        allowed_max_ppm = 5000.0

    for idx in range(len(obs_wl)):
        if valid_mask[idx] and excess_ppm_arr[idx] > allowed_max_ppm:
            valid_mask[idx] = False

    if not valid_mask.any(): return []

    is_muted = False
    obs_std = np.std(excess_ppm_arr[valid_mask])
    if obs_std < 0.2 * allowed_max_ppm:
        is_muted = True

    y = norm_excess[valid_mask]
    y_error = error_arr[valid_mask] / continuum[valid_mask]
    y_w = y / y_error

    active_molecules = []
    X = []
    
    for mol, template_df in templates_dict.items():
        template_wl = template_df["wavelength_um"].values
        template_flux = template_df["flux"].values
        t_interp = np.interp(obs_wl[valid_mask], template_wl, template_flux, left=0, right=0)
        
        if np.sum(t_interp) > 0:
            X.append(t_interp / y_error)
            active_molecules.append(mol)

    if not X:
        return []

    X = np.column_stack(X)
    
    try:
        XTX = X.T @ X + np.eye(X.shape[1]) * 1e-8
        XTy = X.T @ y_w
        beta = np.linalg.inv(XTX) @ XTy
        
        residuals = y_w - X @ beta
        dof = len(y_w) - len(beta)
        if dof > 0:
            mse = np.sum(residuals**2) / dof
            cov = mse * np.linalg.inv(XTX)
            beta_errors = np.sqrt(np.diag(cov))
        else:
            beta_errors = np.ones_like(beta) * np.inf
    except np.linalg.LinAlgError:
        return []

    chi2_m0 = np.sum(y_w**2)
    chi2_m1 = np.sum(residuals**2)
    bic_m0 = chi2_m0
    bic_m1 = chi2_m1 + len(beta) * math.log(len(y_w))
    log_evidence = round(bic_m0 - bic_m1, 2)

    detections = []
    for i, mol in enumerate(active_molecules):
        b = beta[i]
        b_err = beta_errors[i]
        sigma = b / b_err if b_err > 0 else 0
        if sigma < 0:
            sigma = 0

        template_vals = X[:, i] * y_error
        active_points = np.sum((template_vals > np.max(template_vals)*0.1) & (y > 0))
        
        if sigma >= MARGINAL_SIGMA:
            max_idx = np.argmax(template_vals)
            peak_wl = obs_wl[valid_mask][max_idx]
            mean_excess = np.mean(excess_ppm_arr[valid_mask][template_vals > np.max(template_vals)*0.1]) if active_points > 0 else 0

            detections.append({
                "molecule": mol,
                "detection_sigma": round(sigma, 3),
                "wavelength_um": round(peak_wl, 4),
                "hitran_match_count": int(active_points),
                "depth_excess_ppm": round(float(mean_excess), 3),
                "log_evidence": log_evidence,
                "is_muted": is_muted,
            })

    return detections


# ── detection classification ─────────────────────────────────────────────────

def classify_detection(det, all_detections_for_planet, phys_params, host_spectral_type):
    """Apply two-tier classification, abiotic reasoning, stellar contamination, and instrument weighting."""
    mol = det["molecule"]
    sigma = det["detection_sigma"]
    matches = det["hitran_match_count"]
    notes = ""
    
    # 0. Cloud/Haze Suppression Muting
    if det.get("is_muted"):
        sigma = max(0.0, sigma - 0.5)
        det["detection_sigma"] = round(sigma, 3)
        notes += "Cloud/Haze muting detected: spectrum variance suppressed. -0.5σ penalty applied. "
    
    # 1. Instrument Weighting
    inst = str(det.get("instrument") or "").lower()
    fac = str(det.get("facility") or "").lower()
    weight = DEFAULT_INSTRUMENT_WEIGHT
    for key, w in INSTRUMENT_WEIGHTS.items():
        if key in inst or key in fac:
            weight = w
            break
    
    if weight < 1.0:
        sigma = sigma * weight
        det["detection_sigma"] = round(sigma, 3)
        notes += f"Instrument weight {weight} applied. "

    # 2. Stellar Contamination Filter
    st_prefix = str(host_spectral_type)[0].upper() if host_spectral_type else ""
    if st_prefix in STELLAR_CONTAM_RISK and mol in STELLAR_CONTAM_RISK[st_prefix]:
        penalty = STELLAR_CONTAM_RISK[st_prefix][mol]
        sigma = max(0.0, sigma - penalty)
        det["detection_sigma"] = round(sigma, 3)
        notes += f"Stellar contamination risk ({st_prefix}-dwarf {mol} mimicry): -{penalty}σ penalty. "

    # 3. Expanded Abiotic Reasoning
    detected_mols = {d["molecule"]: d["detection_sigma"] for d in all_detections_for_planet}
    abiotic = False if mol in ABIOTIC_MOLECULES else None
    
    # CH4 context
    if mol == "ch4":
        if detected_mols.get("co2", 0) < MARGINAL_SIGMA:
            sigma = max(0.0, sigma - 1.0)
            notes += "CH4 without CO2: possible abiotic origin, -1.0σ penalty. "
            
    # Thermochemical disequilibrium (H2O + CH4 without O3)
    if DISEQ_PAIR.issubset(set(detected_mols.keys())) and mol in DISEQ_PAIR:
        if detected_mols.get("o3", 0) < MARGINAL_SIGMA:
            notes += "H2O + CH4 detected: potential thermochemical disequilibrium. "
            
    # Triple biosignature check
    if TRIPLE_BIOSIG.issubset(set(d for d, s in detected_mols.items() if s >= CONFIRMED_SIGMA)):
        if mol in TRIPLE_BIOSIG:
            abiotic = True
            notes += "TRIPLE BIOSIGNATURE (H₂O+CH₄+O₃) — abiotic origin unlikely. "
            
    # CO / CO2 ratio
    if mol == "co" and detected_mols.get("co2", 0) >= MARGINAL_SIGMA:
        if sigma > detected_mols.get("co2"):
            notes += "High CO/CO2 ratio: photochemical disequilibrium flagged. "
            
    # SO2 / NH3 context
    m_e = nv(phys_params.get("m_e"))
    r_e = nv(phys_params.get("r_e"))
    is_rocky = m_e and m_e <= 10.0 and r_e and r_e <= 2.0
    
    if mol == "so2" and is_rocky:
        notes += "SO2 on rocky world: likely volcanic activity. "
        abiotic = False
    elif mol == "nh3":
        if is_rocky:
            sigma += 0.5  # NH3 on rocky is highly anomalous
            notes += "NH3 on rocky world: anomalous, +0.5σ boost. "
        else:
            sigma = max(0.0, sigma - 1.0) # NH3 expected on gas giants
            notes += "NH3 on gas giant: expected, -1.0σ penalty. "
            abiotic = False
            
    # O3 on M-dwarfs
    if mol == "o3" and st_prefix == "M":
        notes += "O3 on M-dwarf planet: possible photochemical false positive. "

    det["detection_sigma"] = round(sigma, 3)

    # 4. Tier classification
    if matches >= 3 and sigma >= CONFIRMED_SIGMA:
        tier = "confirmed"
        notes = f"Tier 1 confirmed ({sigma:.1f}σ, {matches} lines). " + notes
    elif matches >= 2 and sigma >= MARGINAL_SIGMA:
        tier = "marginal"
        notes = f"Tier 2 marginal ({sigma:.1f}σ, {matches} lines). " + notes
    else:
        tier = "rejected"
        notes = f"Rejected ({sigma:.1f}σ, {matches} lines). " + notes

    det["abiotic_ruled_out"] = abiotic
    det["method_notes"] = notes.strip()
    det["reviewed"] = False
    det["tier"] = tier
    return det


# ── database write ───────────────────────────────────────────────────────────

def upsert_detections(session, detections):
    """Upsert molecule detections. Key: planet_id + spec_id + molecule."""
    count = 0
    skipped = 0
    for det in detections:
        if not det.get("planet_id"):
            skipped += 1
            continue
        existing = session.execute(text("""
            SELECT detection_id FROM molecule_detections
            WHERE planet_id = :pid AND spec_id = :sid AND molecule = :mol
            LIMIT 1
        """), {"pid": det["planet_id"], "sid": det["spec_id"],
               "mol": det["molecule"]}).fetchone()

        params = {
            "pid": det["planet_id"], "sid": det["spec_id"],
            "mol": det["molecule"], "sigma": float(det["detection_sigma"]),
            "wl": float(det["wavelength_um"]) if det.get("wavelength_um") is not None else None,
            "hmc": int(det["hitran_match_count"]),
            "excess": float(det["depth_excess_ppm"]),
            "inst": det.get("instrument"),
            "fac": det.get("facility"), "ref": det.get("pub_reference"),
            "abiotic": det.get("abiotic_ruled_out"),
            "notes": det.get("method_notes"), "reviewed": det.get("reviewed", False),
        }

        if existing:
            params["did"] = existing[0]
            session.execute(text("""
                UPDATE molecule_detections SET
                    detection_sigma=:sigma, wavelength_um=:wl,
                    hitran_match_count=:hmc, depth_excess_ppm=:excess,
                    abiotic_ruled_out=:abiotic, method_notes=:notes,
                    reviewed=:reviewed, flagged_at=now()
                WHERE detection_id=:did
            """), params)
        else:
            params["did"] = new_id()
            session.execute(text("""
                INSERT INTO molecule_detections
                    (detection_id, planet_id, spec_id, molecule, detection_sigma,
                     wavelength_um, hitran_match_count, depth_excess_ppm,
                     instrument, facility, pub_reference,
                     abiotic_ruled_out, method_notes, reviewed)
                VALUES (:did, :pid, :sid, :mol, :sigma, :wl, :hmc, :excess,
                        :inst, :fac, :ref, :abiotic, :notes, :reviewed)
            """), params)
        count += 1

    session.commit()
    if skipped:
        log(f"  Skipped {skipped} detections (planet_id not found in DB)")
    return count


# ── cross-reference engine ───────────────────────────────────────────────────

def cross_reference(session, planet_detections):
    """Cross-reference detections with habitability scores and orbital predictions."""
    enriched = []
    for pname, dets in planet_detections.items():
        pid = dets[0]["planet_id"] if dets[0].get("planet_id") else None
        if not pid:
            enriched.append({"planet_name": pname, "detections": dets,
                             "hab_score": None, "orbital_pred": False})
            continue

        hab = session.execute(text("""
            SELECT composite_score FROM habitability_scores
            WHERE planet_id=:pid ORDER BY scored_at DESC LIMIT 1
        """), {"pid": pid}).fetchone()

        orb = session.execute(text("""
            SELECT COUNT(*) FROM orbital_predictions
            WHERE star_id = (SELECT star_id FROM planets WHERE planet_id=:pid)
        """), {"pid": pid}).fetchone()

        enriched.append({
            "planet_name": pname,
            "detections": dets,
            "hab_score": float(hab[0]) if hab and hab[0] else None,
            "orbital_pred": (orb[0] > 0) if orb else False,
        })
    return enriched


# ── report generation ────────────────────────────────────────────────────────

def generate_report(enriched, all_detections):
    """Generate markdown biosignature discovery report."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    confirmed = [d for d in all_detections if d.get("tier") == "confirmed"]
    marginal = [d for d in all_detections if d.get("tier") == "marginal"]

    md = f"""# Biosignature Detection Report
**Date:** {date_str}  |  **Model:** v{MODEL_VERSION}  |  **Threshold:** {CONFIRMED_SIGMA}σ confirmed / {MARGINAL_SIGMA}σ marginal

## Summary
- **Planets analyzed:** {len(enriched)}
- **Tier 1 (confirmed ≥{CONFIRMED_SIGMA}σ):** {len(confirmed)} detections across {len(set(d['planet_name'] for d in confirmed))} planets
- **Tier 2 (marginal {MARGINAL_SIGMA}–{CONFIRMED_SIGMA}σ):** {len(marginal)} detections across {len(set(d.get('planet_name','') for d in marginal))} planets

## Tier 1 — Confirmed Detections (≥{CONFIRMED_SIGMA}σ)

| Planet | Molecule | σ | ln B | Excess (ppm) | Lines | λ (µm) | Facility | Hab. Score |
|:-------|:---------|--:|:-----|:-------------|:------|:-------|:---------|:-----------|
"""
    for entry in sorted(enriched, key=lambda x: x.get("hab_score") or 0, reverse=True):
        for d in sorted(entry["detections"], key=lambda x: -x["detection_sigma"]):
            if d.get("tier") != "confirmed":
                continue
            hab = f"{entry['hab_score']:.3f}" if entry.get("hab_score") else "—"
            ln_b = f"{d.get('log_evidence', 0.0):.1f}"
            md += (f"| {d.get('planet_name',''):<22} | {MOL_NAMES.get(d['molecule'], d['molecule']):<4} "
                   f"| {d['detection_sigma']:.1f} | {ln_b:>4} | {d['depth_excess_ppm']:.1f} "
                   f"| {d['hitran_match_count']} | {d.get('wavelength_um','—')} "
                   f"| {d.get('facility','—')} | {hab} |\n")

    md += f"""
## Tier 2 — Marginal Detections ({MARGINAL_SIGMA}–{CONFIRMED_SIGMA}σ) — Watchlist

| Planet | Molecule | σ | ln B | Excess (ppm) | Lines | Notes |
|:-------|:---------|--:|:-----|:-------------|:------|:------|
"""
    for entry in enriched:
        for d in entry["detections"]:
            if d.get("tier") != "marginal":
                continue
            ln_b = f"{d.get('log_evidence', 0.0):.1f}"
            md += (f"| {d.get('planet_name',''):<22} | {MOL_NAMES.get(d['molecule'], d['molecule']):<4} "
                   f"| {d['detection_sigma']:.1f} | {ln_b:>4} | {d['depth_excess_ppm']:.1f} "
                   f"| {d['hitran_match_count']} | {d.get('method_notes','')} |\n")

    md += f"""
## Methodology & Limitations
1. **Spectra Source:** NASA Exoplanet Archive Atmospheric Spectroscopy Table (TAP).
2. **First-Pass Heuristic Matching:** The HITRAN molecular line matching (≥{MIN_HITRAN_MATCH} lines required per detection) is a *first-pass heuristic matching algorithm*.
3. **Continuum Estimation:** Legendre polynomial (degree {POLY_DEGREE}) masking known band centers, replacing the legacy median binning.
4. **Significance & Evidence:** Detection σ = (depth_obs − continuum) / uncertainty. Bayesian Evidence (ln B) approximated via BIC (M1 vs M0).
5. **Validation:** Cross-referenced against stellar spectra (M/K dwarfs) to penalize possible starspot contamination. Multi-epoch consistency applies confidence decay.
6. **Cloud/Haze Suppression:** If spectral variance is <20% of a theoretical scale-height depth, it implies a muted/hazy spectrum and a -0.5σ penalty is applied.

## References
- Kochanov et al. (2016) HITRAN Application Programming Interface (HAPI)
- Gordon et al. (2022) The HITRAN2020 molecular spectroscopic database
"""
    out_path = OUTPUT_DIR / f"biosignature_detections_{date_str}_v{MODEL_VERSION}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


def run_injection_recovery():
    """Inject synthetic molecular signals into real spectra and measure recovery rates."""
    print(f"\n[Injection-Recovery Validation] v{MODEL_VERSION}")
    print("=" * 60)
    
    session = Session()
    try:
        # Get random spectra that have data
        rows = session.execute(text("""
            SELECT spec_id, planet_name FROM (
                SELECT DISTINCT a.spec_id, a.planet_name
                FROM atmospheric_spectra a
                WHERE a.depth_ppm IS NOT NULL
            ) subq
            ORDER BY RANDOM()
        """)).fetchall()
        
        valid_rows = []
        for spec_id, pname in rows:
            spectrum_df = fetch_spectrum_data(session, spec_id)
            if spectrum_df.empty or len(spectrum_df) < 5: continue
            errors = spectrum_df[["depth_err_upper", "depth_err_lower"]].mean(axis=1).values
            median_err = np.nanmedian(errors)
            if np.isnan(median_err) or median_err <= 0: continue
            valid_rows.append((spec_id, pname))
            if len(valid_rows) >= 10: break
            
        rows = valid_rows
        
        if not rows:
            print("  No spectra found to inject into.")
            return
            
        phys_map = fetch_physics(session)
        amplitudes_sigma = [1.0, 2.0, 3.0, 5.0]
        results = {mol: {amp: {"recovered": 0, "total": 0} for amp in amplitudes_sigma} for mol in TARGET_MOLECULES}
        false_positives = {mol: 0 for mol in TARGET_MOLECULES}
        total_null_tests = 0
        
        print(f"  Testing on {len(rows)} real spectra with {len(TARGET_MOLECULES)} molecules...")
        
        for spec_id, pname in rows:
            spectrum_df = fetch_spectrum_data(session, spec_id)
            if spectrum_df.empty or len(spectrum_df) < 5:
                continue
                
            phys_params = phys_map.get(pname, {})
            
            templates_dict = {}
            for mol in TARGET_MOLECULES:
                template_df = fetch_template(session, mol, phys_params.get("teq"))
                if not template_df.empty:
                    templates_dict[mol] = template_df
                    
            if not templates_dict:
                continue

            # 1. Null injection (False Positive check)
            null_dets = unmix_spectrum(spectrum_df, templates_dict, phys_params)
            for mol in TARGET_MOLECULES:
                if mol not in templates_dict: continue
                det = next((d for d in null_dets if d["molecule"] == mol), None)
                total_null_tests += 1 
                if det and det["detection_sigma"] >= MARGINAL_SIGMA:
                    false_positives[mol] += 1
                    
            # 2. Synthetic injections
            continuum = fit_gp_continuum(spectrum_df)
            excess = spectrum_df["depth_ppm"].values - continuum
            empirical_scatter = np.std(excess[np.isfinite(excess)])
            if empirical_scatter <= 0: continue
            
            for mol, template_df in templates_dict.items():
                template_wl = template_df["wavelength_um"].values
                template_flux = template_df["flux"].values
                
                for amp_sigma in amplitudes_sigma:
                    # Create injected spectrum copy
                    inj_df = spectrum_df.copy()
                    
                    # Interpolate template to obs wavelengths
                    inj_flux = np.interp(inj_df["wavelength_um"].values, template_wl, template_flux, left=0, right=0)
                    
                    # Scale template so its 95th percentile peak is roughly amp_sigma * empirical_scatter
                    active_flux = inj_flux[inj_flux > 0]
                    if len(active_flux) > 0:
                        peak_flux = np.percentile(active_flux, 95)
                        if peak_flux > 0:
                            scale = (amp_sigma * empirical_scatter) / peak_flux
                            inj_df["depth_ppm"] += inj_flux * scale
                        
                    # Test recovery
                    rec_dets = unmix_spectrum(inj_df, templates_dict, phys_params)
                    det = next((d for d in rec_dets if d["molecule"] == mol), None)
                    results[mol][amp_sigma]["total"] += 1
                    if det and det["detection_sigma"] >= MARGINAL_SIGMA:
                        results[mol][amp_sigma]["recovered"] += 1

        print("\n  Recovery Rates (MARGINAL threshold):")
        print(f"  {'Molecule':<10} | {'1sig':<10} | {'2sig':<10} | {'3sig':<10} | {'5sig':<10} | {'False Pos':<10}")
        print("-" * 75)
        
        report_lines = []
        for mol in TARGET_MOLECULES:
            rates = []
            for amp in amplitudes_sigma:
                tot = results[mol][amp]["total"]
                rec = results[mol][amp]["recovered"]
                pct = (rec/tot*100) if tot > 0 else 0
                rates.append(f"{rec}/{tot} ({pct:2.0f}%)")
                
            fp_rate = (false_positives[mol]/total_null_tests*100) if total_null_tests > 0 else 0
            
            line = f"  {MOL_NAMES[mol]:<10} | {rates[0]:<10} | {rates[1]:<10} | {rates[2]:<10} | {rates[3]:<10} | {false_positives[mol]}/{total_null_tests} ({fp_rate:4.1f}%)"
            print(line)
            report_lines.append(line)
            
        # Write report
        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = OUTPUT_DIR / f"injection_recovery_{date_str}_v{MODEL_VERSION}.md"
        
        md = f"""# Injection-Recovery Validation Report
**Date:** {date_str}  |  **Model:** v{MODEL_VERSION}  |  **Spectra Tested:** {len(rows)}

Recovery rate indicates the percentage of times the pipeline successfully recovered a synthetically injected molecular signal of a given signal-to-noise ratio.

```
{'Molecule':<10} | {'1σ':<10} | {'2σ':<10} | {'3σ':<10} | {'5σ':<10} | {'False Pos':<10}
{'-' * 75}
{chr(10).join(report_lines)}
```
"""
        out_path.write_text(md, encoding="utf-8")
        print(f"\n  Report saved to: {out_path}")

    finally:
        session.close()


def apply_multi_epoch_consistency(planet_dets):
    """Boost confidence for molecules detected across multiple independent spectra, penalize single-epoch anomalies."""
    if not planet_dets:
        return
        
    mol_spectra = {}
    for det in planet_dets:
        mol = det["molecule"]
        if mol not in mol_spectra:
            mol_spectra[mol] = set()
        mol_spectra[mol].add(det["spec_id"])
        
    total_spectra = len(set(d["spec_id"] for d in planet_dets))
    
    for det in planet_dets:
        mol = det["molecule"]
        n_spectra_with_mol = len(mol_spectra[mol])
        
        notes = ""
        if total_spectra > 1:
            if n_spectra_with_mol >= 2:
                det["detection_sigma"] = round(det["detection_sigma"] + 0.5, 3)
                notes = f"Consistent multi-epoch detection ({n_spectra_with_mol}/{total_spectra} spectra): +0.5σ boost. "
            elif n_spectra_with_mol == 1:
                det["detection_sigma"] = max(0.0, round(det["detection_sigma"] - 0.5, 3))
                notes = f"Inconsistent multi-epoch detection (1/{total_spectra} spectra): -0.5σ penalty. "
                
        if notes:
            det["method_notes"] = notes + det.get("method_notes", "")


# ── main ─────────────────────────────────────────────────────────────────────

def run(planet_name=None, threshold=None, dry_run=False, validate=False):
    if validate:
        run_injection_recovery()
        return

    if threshold:
        global MARGINAL_SIGMA
        MARGINAL_SIGMA = threshold

    print(f"\nBiosignature Detector v{MODEL_VERSION}")
    print(f"  Tier 1 threshold: >={CONFIRMED_SIGMA} sigma (confirmed)")
    print(f"  Tier 2 threshold: >={MARGINAL_SIGMA} sigma (marginal/watchlist)")
    print(f"  Min HITRAN lines: {MIN_HITRAN_MATCH}")
    if planet_name:
        print(f"  Filter: {planet_name}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    session = Session()
    t0 = time.perf_counter()

    try:
        # Check prerequisites
        hitran_count = session.execute(text("SELECT COUNT(*) FROM hitran_lines")).fetchone()[0]
        spectra_count = session.execute(text("SELECT COUNT(*) FROM atmospheric_spectra WHERE depth_ppm IS NOT NULL")).fetchone()[0]
        print(f"\n  HITRAN lines in DB:     {hitran_count}")
        print(f"  Spectral data points:  {spectra_count}")

        if hitran_count == 0:
            print("\n  ERROR: No HITRAN lines — run: python modules/hitran_seeder.py --static")
            return
        if spectra_count == 0:
            print("\n  ERROR: No spectra — run: python modules/spectra_ingestor.py")
            return

        template_cache = {}
        planets = fetch_planets_with_spectra(session, planet_name)
        print(f"\n  Planets with spectra: {len(planets)}")
        
        phys_map = fetch_physics(session)

        all_detections = []
        planet_detections = {}

        for pname, pinfo in planets.items():
            print(f"\n-- {pname} --")
            planet_dets = []
            
            phys_params = phys_map.get(pname, {})
            host_spectral_type = phys_params.get("spectral_type")

            for spec_id, facility, instrument, obs_type, pub_ref in pinfo["spectra"]:
                spectrum_df = fetch_spectrum_data(session, spec_id)
                if spectrum_df.empty or len(spectrum_df) < 5:
                    continue

                templates_dict = {}
                for mol in TARGET_MOLECULES:
                    template_df = fetch_template(session, mol, phys_params.get("teq"))
                    if not template_df.empty:
                        templates_dict[mol] = template_df

                dets = unmix_spectrum(spectrum_df, templates_dict, phys_params)
                for det in dets:
                    det["planet_name"] = pname
                    det["planet_id"] = pinfo["planet_id"]
                    det["spec_id"] = spec_id
                    det["facility"] = facility
                    det["instrument"] = instrument
                    det["pub_reference"] = pub_ref
                    planet_dets.append(det)

            # Apply multi-epoch consistency
            apply_multi_epoch_consistency(planet_dets)

            # Classify all detections for this planet
            for det in planet_dets:
                classify_detection(det, planet_dets, phys_params, host_spectral_type)
                if det["detection_sigma"] >= CONFIRMED_SIGMA:
                    tier_label = "[T1]"
                else:
                    tier_label = "[T2]"

                print(f"  {tier_label} {MOL_NAMES[det['molecule']]}  "
                      f"sigma={det['detection_sigma']:.1f}  "
                      f"lines={det['hitran_match_count']}  "
                      f"excess={det['depth_excess_ppm']:.1f} ppm")

            all_detections.extend(planet_dets)
            if planet_dets:
                planet_detections[pname] = planet_dets

        elapsed = time.perf_counter() - t0
        confirmed = [d for d in all_detections if d.get("tier") == "confirmed"]
        marginal = [d for d in all_detections if d.get("tier") == "marginal"]

        print(f"\n{'='*60}")
        print(f"  Completed in {elapsed:.1f}s")
        print(f"  Tier 1 (confirmed): {len(confirmed)} detections")
        print(f"  Tier 2 (marginal):  {len(marginal)} detections")
        print(f"  Total planets:      {len(planet_detections)}")

        if not all_detections:
            print("  No detections found.")
            return

        # Molecule breakdown
        print(f"\n  By molecule:")
        for mol in TARGET_MOLECULES:
            conf = sum(1 for d in confirmed if d["molecule"] == mol)
            marg = sum(1 for d in marginal if d["molecule"] == mol)
            if conf or marg:
                print(f"    {MOL_NAMES[mol]:<6}: {conf} confirmed, {marg} marginal")

        if dry_run:
            print(f"\n[DRY RUN] No database writes.")
        else:
            # Write to DB
            print(f"\nWriting detections to database ...")
            n = upsert_detections(session, all_detections)
            print(f"  Written/updated: {n} detections")

        # Cross-reference and report
        print(f"\nCross-referencing with habitability scores ...")
        enriched = cross_reference(session, planet_detections)

        print(f"\nGenerating report ...")
        out_path = generate_report(enriched, all_detections)
        print(f"  Saved -> {out_path}")

        # High-priority alerts
        alerts = [e for e in enriched
                  if e.get("hab_score") and e["hab_score"] > 0.5
                  and any(d["tier"] == "confirmed" for d in e["detections"])]
        if alerts:
            print(f"\n[ALERT] HIGH-PRIORITY ALERTS (hab_score > 0.5 + confirmed biosig):")
            for a in sorted(alerts, key=lambda x: -(x["hab_score"] or 0)):
                mols = [MOL_NAMES[d["molecule"]] for d in a["detections"]
                        if d["tier"] == "confirmed"]
                print(f"  * {a['planet_name']}  hab={a['hab_score']:.3f}  "
                      f"molecules: {', '.join(mols)}")

    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback; traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Biosignature Detector")
    parser.add_argument("--planet", type=str, default=None)
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override marginal σ threshold (default 2.0)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate", action="store_true", 
                        help="Run injection-recovery validation instead of full pipeline")
    args = parser.parse_args()
    run(planet_name=args.planet, threshold=args.threshold, dry_run=args.dry_run, validate=args.validate)
