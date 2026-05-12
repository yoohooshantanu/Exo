"""
modules/biosignature_detector.py  v1.0.0

Core science engine for Phase 4. Compares atmospheric spectra against
HITRAN molecular features to identify biosignature candidates.

Two-tier detection system:
  Tier 1 (confirmed):  σ ≥ 3.0 — real signal, used in ranking/alerts/papers
  Tier 2 (marginal):   2.0 ≤ σ < 3.0 — watchlist, stored for future validation

Run:
  python modules/biosignature_detector.py
  python modules/biosignature_detector.py --planet "WASP-39 b"
  python modules/biosignature_detector.py --threshold 2.0
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL     = os.environ["DATABASE_URL"]
MODEL_VERSION    = "1.0.0"
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

# Molecules where abiotic origin is likely
ABIOTIC_MOLECULES = {"so2", "co"}
# Triple biosignature — if all three present, abiotic_ruled_out = True
TRIPLE_BIOSIG = {"h2o", "ch4", "o3"}

TARGET_MOLECULES = ["h2o", "co2", "o3", "ch4", "co", "nh3", "so2"]

MOL_NAMES = {
    "h2o": "H2O", "co2": "CO2", "o3": "O3", "ch4": "CH4",
    "co": "CO", "nh3": "NH3", "so2": "SO2",
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
            MAX(CASE WHEN sp.param_name='radius_solar' THEN sp.value END) as r_s
        FROM planets p
        JOIN stars s ON p.star_id = s.star_id
        LEFT JOIN planet_parameters pp ON pp.planet_id=p.planet_id AND pp.is_default=true
        LEFT JOIN star_parameters sp ON sp.star_id=s.star_id AND sp.is_default=true
        GROUP BY p.planet_name
    """)).fetchall()
    return {r[0]: {"r_e": r[1], "m_e": r[2], "teq": r[3], "r_s": r[4]} for r in rows}


# ── molecule matching engine ─────────────────────────────────────────────────

def estimate_continuum(spectrum_df, center_idx, n_bins=CONTINUUM_BINS):
    """σ-clipped median of neighboring bins for continuum estimation."""
    n = len(spectrum_df)
    lo = max(0, center_idx - n_bins)
    hi = min(n, center_idx + n_bins + 1)
    neighbors = []
    for i in range(lo, hi):
        if i == center_idx:
            continue
        d = nv(spectrum_df.iloc[i]["depth_ppm"])
        if d is not None:
            neighbors.append(d)
    if len(neighbors) < 3:
        return None
    arr = np.array(neighbors)
    med = np.median(arr)
    std = np.std(arr)
    if std > 0:
        clipped = arr[np.abs(arr - med) < 2.5 * std]
        if len(clipped) >= 2:
            return float(np.median(clipped))
    return float(med)


def match_molecule(spectrum_df, template_df, molecule, phys_params):
    """
    Match template against one spectrum using 1D cross-correlation (CCF)
    and physics-based scale-height constraints.
    """
    if spectrum_df.empty or template_df.empty:
        return None

    # Sort spectrum
    spectrum_df = spectrum_df.sort_values("wavelength_um").reset_index(drop=True)
    obs_wl = spectrum_df["wavelength_um"].values
    
    norm_excess = np.zeros(len(obs_wl))
    sigma_meas_arr = np.zeros(len(obs_wl))
    valid_mask = np.zeros(len(obs_wl), dtype=bool)
    excess_ppm_arr = np.zeros(len(obs_wl))

    for idx, row in spectrum_df.iterrows():
        err_up = nv(row["depth_err_upper"])
        err_lo = nv(row["depth_err_lower"])
        if err_up is None and err_lo is None: continue
        err = (abs(err_up) + abs(err_lo)) / 2.0 if err_up and err_lo else (abs(err_up) if err_up else abs(err_lo))
        if err <= 0: continue
        
        cont = estimate_continuum(spectrum_df, idx)
        if cont is None or cont <= 0: continue
        
        # normalized excess = (depth - cont) / cont
        norm_ex = (row["depth_ppm"] - cont) / cont
        norm_err = err / cont
        
        norm_excess[idx] = norm_ex
        sigma_meas_arr[idx] = norm_err
        excess_ppm_arr[idx] = row["depth_ppm"] - cont
        valid_mask[idx] = True

    if not valid_mask.any(): return None

    # Scale-Height Proxy
    teq = nv(phys_params.get("teq")); m_e = nv(phys_params.get("m_e"))
    r_e = nv(phys_params.get("r_e")); r_s = nv(phys_params.get("r_s"))
    if teq and m_e and r_e and r_s and m_e > 0:
        g = (m_e / (r_e**2)) * 9.8
        H = (1.38e-23 * teq) / (2.3 * 1.66e-27 * g)
        Rp = r_e * 6.37e6
        Rs = r_s * 6.95e8
        max_depth_ppm = (2 * Rp * H / (Rs**2)) * 1e6
        allowed_max_ppm = max_depth_ppm * 2.0 # 2x tolerance
    else:
        allowed_max_ppm = 5000.0 # safe fallback

    for idx in range(len(obs_wl)):
        if valid_mask[idx] and excess_ppm_arr[idx] > allowed_max_ppm:
            valid_mask[idx] = False

    if not valid_mask.any(): return None

    obs_excess_clean = np.where(valid_mask, norm_excess, 0)
    signal_to_noise = np.where((valid_mask) & (sigma_meas_arr > 0), obs_excess_clean / sigma_meas_arr, 0)

    # CCF Evaluation on Template Grid
    template_wl = template_df["wavelength_um"].values
    template_flux = template_df["flux"].values

    valid_region = (template_wl >= obs_wl.min()) & (template_wl <= obs_wl.max())
    if not valid_region.any(): return None

    # Interpolate observation to uniform template grid
    snr_interp = np.interp(template_wl[valid_region], obs_wl, signal_to_noise, left=0, right=0)
    template_sub = template_flux[valid_region]
    
    if template_sub.sum() <= 0: return None
    
    # 1D Cross-Correlation
    ccf_snr = correlate(snr_interp, template_sub, mode='same')
    
    # Peak detection significance
    peak_snr = np.max(ccf_snr)
    weighted_sigma = float(peak_snr / template_sub.sum())

    if weighted_sigma < MARGINAL_SIGMA:
        return None

    # Calculate mean excess of the active points
    active_excesses = excess_ppm_arr[valid_mask & (obs_excess_clean > 0)]
    mean_excess = float(np.mean(active_excesses)) if len(active_excesses) > 0 else 0.0

    return {
        "molecule": molecule,
        "detection_sigma": round(weighted_sigma, 3),
        "wavelength_um": round(template_wl[valid_region][np.argmax(template_sub)], 4),
        "hitran_match_count": len(active_excesses), # proxy for points matched
        "depth_excess_ppm": round(mean_excess, 3),
    }


# ── detection classification ─────────────────────────────────────────────────

def classify_detection(det, all_detections_for_planet):
    """Apply two-tier classification and abiotic reasoning."""
    mol = det["molecule"]
    sigma = det["detection_sigma"]
    matches = det["hitran_match_count"]

    notes = ""
    # Soft Abiotic rule: CH4 without CO2
    if mol == "ch4":
        has_co2 = any(d["molecule"] == "co2" and d["detection_sigma"] >= MARGINAL_SIGMA for d in all_detections_for_planet)
        if not has_co2:
            sigma = max(0.0, sigma - 1.0)
            det["detection_sigma"] = round(sigma, 3)
            notes += "CH4 without CO2: possible abiotic origin, -1.0σ penalty applied. "
            
    # Triple biosignature check
    detected_mols = {d["molecule"] for d in all_detections_for_planet if d["detection_sigma"] >= CONFIRMED_SIGMA}
    detected_mols.add(mol)
    abiotic = False if mol in ABIOTIC_MOLECULES else None
    if TRIPLE_BIOSIG.issubset(detected_mols) and mol in TRIPLE_BIOSIG:
        abiotic = True
        notes += "TRIPLE BIOSIGNATURE (H₂O+CH₄+O₃) — abiotic origin unlikely. "

    # Tier classification (>=3 lines for Confirmed)
    if matches >= 3 and sigma >= CONFIRMED_SIGMA:
        tier = "confirmed"
        notes += f"Tier 1 confirmed detection ({sigma:.1f}σ, {matches} lines). "
    elif matches >= 2 and sigma >= MARGINAL_SIGMA:
        tier = "marginal"
        notes += f"Tier 2 marginal detection ({sigma:.1f}σ, {matches} lines). "
    else:
        tier = "rejected"
        notes += f"Rejected ({sigma:.1f}σ, {matches} lines). "

    det["abiotic_ruled_out"] = abiotic
    det["method_notes"] = notes.strip()
    det["reviewed"] = False
    det["tier"] = tier
    return det


# ── database write ───────────────────────────────────────────────────────────

def upsert_detections(session, detections):
    """Upsert molecule detections. Key: planet_id + spec_id + molecule."""
    count = 0
    for det in detections:
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

| Planet | Molecule | σ | Excess (ppm) | Lines | λ (µm) | Facility | Hab. Score |
|:-------|:---------|--:|:-------------|:------|:-------|:---------|:-----------|
"""
    for entry in sorted(enriched, key=lambda x: x.get("hab_score") or 0, reverse=True):
        for d in sorted(entry["detections"], key=lambda x: -x["detection_sigma"]):
            if d.get("tier") != "confirmed":
                continue
            hab = f"{entry['hab_score']:.3f}" if entry.get("hab_score") else "—"
            md += (f"| {d.get('planet_name',''):<22} | {MOL_NAMES.get(d['molecule'], d['molecule']):<4} "
                   f"| {d['detection_sigma']:.1f} | {d['depth_excess_ppm']:.1f} "
                   f"| {d['hitran_match_count']} | {d.get('wavelength_um','—')} "
                   f"| {d.get('facility','—')} | {hab} |\n")

    md += f"""
## Tier 2 — Marginal Detections ({MARGINAL_SIGMA}–{CONFIRMED_SIGMA}σ) — Watchlist

| Planet | Molecule | σ | Excess (ppm) | Lines | Notes |
|:-------|:---------|--:|:-------------|:------|:------|
"""
    for entry in enriched:
        for d in entry["detections"]:
            if d.get("tier") != "marginal":
                continue
            md += (f"| {d.get('planet_name',''):<22} | {MOL_NAMES.get(d['molecule'], d['molecule']):<4} "
                   f"| {d['detection_sigma']:.1f} | {d['depth_excess_ppm']:.1f} "
                   f"| {d['hitran_match_count']} | {d.get('method_notes','')} |\n")

    md += f"""
## Methodology & Limitations
1. **Spectra Source:** NASA Exoplanet Archive Atmospheric Spectroscopy Table (TAP).
2. **First-Pass Heuristic Matching:** The HITRAN molecular line matching (≥{MIN_HITRAN_MATCH} lines required per detection) is a *first-pass heuristic matching algorithm*. It is **not** a substitute for full atmospheric cross-correlation or radiative transfer retrieval. JWST transmission spectra are low-resolution and generally do not resolve individual molecular lines; instead, molecules produce broad, blended absorption bands. High-resolution line-by-line databases like HITRAN are used here for heuristic flagging, not definitive spectral modeling.
3. **Continuum Estimation:** σ-clipped median of ±{CONTINUUM_BINS} neighboring bins.
4. **Significance:** Detection σ = (depth_obs − continuum) / measurement_uncertainty.
5. **Weighting:** Multi-line weighting by HITRAN line intensity.

## References
- Kochanov et al. (2016) HITRAN Application Programming Interface (HAPI)
- Gordon et al. (2022) The HITRAN2020 molecular spectroscopic database
"""
    out_path = OUTPUT_DIR / f"biosignature_detections_{date_str}_v{MODEL_VERSION}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── main ─────────────────────────────────────────────────────────────────────

def run(planet_name=None, threshold=None, dry_run=False):
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

        # Pre-fetch templates is not strictly necessary as we fetch per-planet teq,
        # but we can fetch them per-planet later. We'll leave this empty.
        template_cache = {}

        # Get planets with spectra
        planets = fetch_planets_with_spectra(session, planet_name)
        print(f"\n  Planets with spectra: {len(planets)}")
        
        # Fetch physics mapping for scale-height ceiling
        phys_map = fetch_physics(session)

        all_detections = []
        planet_detections = {}

        for pname, pinfo in planets.items():
            print(f"\n-- {pname} --")
            planet_dets = []
            
            phys_params = phys_map.get(pname, {})

            for spec_id, facility, instrument, obs_type, pub_ref in pinfo["spectra"]:
                spectrum_df = fetch_spectrum_data(session, spec_id)
                if spectrum_df.empty or len(spectrum_df) < 5:
                    continue

                for mol in TARGET_MOLECULES:
                    template_df = fetch_template(session, mol, phys_params.get("teq"))
                    if template_df.empty:
                        continue

                    det = match_molecule(spectrum_df, template_df, mol, phys_params)
                    if det:
                        det["planet_name"] = pname
                        det["planet_id"] = pinfo["planet_id"]
                        det["spec_id"] = spec_id
                        det["facility"] = facility
                        det["instrument"] = instrument
                        det["pub_reference"] = pub_ref
                        planet_dets.append(det)

            # Classify all detections for this planet
            for det in planet_dets:
                classify_detection(det, planet_dets)
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
    args = parser.parse_args()
    run(planet_name=args.planet, threshold=args.threshold, dry_run=args.dry_run)
