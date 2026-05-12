"""
modules/anomaly_detector.py  v1.0.0

Phase 5 — Step 1: Flags physically anomalous exoplanets.

Three detection engines:
  1a  Mass-radius composition deviation  (Zeng et al. 2016)
  1b  Orbital eccentricity-period stability
  1c  Density outlier per planet type (>3 sigma)

Writes to anomaly_flags table.

Run:
  python modules/anomaly_detector.py
  python modules/anomaly_detector.py --dry-run
  python modules/anomaly_detector.py --type mass_radius
  python modules/anomaly_detector.py --type ecc_period
  python modules/anomaly_detector.py --type density
"""

import os, sys, io, uuid, math, argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, insert, update
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from db.models import AnomalyFlag

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL  = os.environ["DATABASE_URL"]
MODEL_VERSION = "1.0.0"

engine  = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def new_id(): return str(uuid.uuid4())
def now_utc(): return datetime.now(timezone.utc)
def log(msg): print(f"  {datetime.now(timezone.utc).strftime('%H:%M:%S')}  {msg}")

def nv(val):
    if val is None: return None
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)): return None
        if pd.isna(val): return None
    except Exception: pass
    return float(val)


# ── Zeng et al. 2016 composition curves ──────────────────────────────────────
# Polynomial fits to log(M/M_earth) = f(log(R/R_earth))
# From Table 3 of Zeng et al. 2016, ApJ, 819, 127
# DOI: 10.3847/0004-637X/819/2/127

ZENG_DOI = "10.3847/0004-637X/819/2/127"

def zeng_pure_iron(log_r):
    """Pure iron composition: log(M) from log(R)."""
    return 0.0592 + 3.7679 * log_r + 0.4599 * log_r**2

def zeng_earth_like(log_r):
    """Earth-like (32.5% Fe + 67.5% silicate): log(M) from log(R)."""
    return 0.0912 + 3.5573 * log_r + 0.3788 * log_r**2

def zeng_pure_water(log_r):
    """Pure water composition: log(M) from log(R)."""
    return 0.1603 + 3.2363 * log_r + 0.3106 * log_r**2


def distance_to_composition(radius, mass, mass_err=None, is_direct_mass=True):
    """
    Compute minimum distance (in sigma) from observed (R, M)
    to the nearest Zeng composition curve.

    mass_err:        1-sigma mass uncertainty in M_earth (from archive)
    is_direct_mass:  True if mass from RV/TTV (measured), False if inferred

    Returns (min_sigma, nearest_curve_name).
    """
    r = nv(radius)
    m = nv(mass)
    if r is None or m is None or r <= 0 or m <= 0:
        return None, None

    log_r = math.log10(r)
    log_m = math.log10(m)

    # Mass uncertainty in log space
    # Priority: use archive error -> else generous fallback
    MIN_FRAC_ERR = 0.10  # 10% floor for suspiciously small errors
    if mass_err is not None and mass_err > 0:
        frac_err = max(mass_err / m, MIN_FRAC_ERR)
    else:
        # No error available -- assume 50% (generous for unmeasured masses)
        frac_err = 0.50

    # Widen acceptance for inferred masses (model-dependent, not measured)
    if not is_direct_mass:
        frac_err = max(frac_err, 0.60)  # at least 60% for inferred masses

    sigma_log_m = frac_err / math.log(10)

    curves = {
        "pure_iron":  zeng_pure_iron(log_r),
        "earth_like": zeng_earth_like(log_r),
        "pure_water": zeng_pure_water(log_r),
    }

    min_sigma = float('inf')
    nearest = None

    for name, expected_log_m in curves.items():
        deviation = abs(log_m - expected_log_m)
        sigma = deviation / sigma_log_m if sigma_log_m > 0 else float('inf')
        if sigma < min_sigma:
            min_sigma = sigma
            nearest = name

    return round(min_sigma, 2), nearest


# ── Mass error loading ───────────────────────────────────────────────────────

def load_mass_errors():
    """
    Load per-planet mass uncertainties from the enriched CSV.
    Returns {planet_name: mass_err_1sigma} using max(|err1|, |err2|).
    """
    csv_path = PROJECT_ROOT / "planets_enriched_clean.csv"
    if not csv_path.exists():
        csv_path = PROJECT_ROOT / "planets_nasa_full.csv"
    if not csv_path.exists():
        print("  WARNING: No CSV found for mass errors -- using fallback")
        return {}

    df = pd.read_csv(csv_path,
                     usecols=["pl_name", "pl_bmasseerr1", "pl_bmasseerr2"],
                     low_memory=False)
    errors = {}
    for _, row in df.dropna(subset=["pl_bmasseerr1"]).iterrows():
        err1 = abs(float(row["pl_bmasseerr1"]))
        err2 = abs(float(row["pl_bmasseerr2"])) if pd.notna(row["pl_bmasseerr2"]) else err1
        errors[row["pl_name"]] = max(err1, err2)

    return errors


# Discovery methods where mass is directly measured
DIRECT_MASS_METHODS = {
    "Radial Velocity",
    "Transit Timing Variations",
    "Eclipse Timing Variations",
    "Astrometry",
    "Pulsar Timing",
}


# ── Data fetching ────────────────────────────────────────────────────────────

def fetch_planet_data(session):
    """Fetch all confirmed planets with physical parameters."""
    rows = session.execute(text("""
        SELECT
            p.planet_id, p.planet_name, p.discovery_method,
            MAX(CASE WHEN pp.param_name='radius_earth'      THEN pp.value END) AS radius_earth,
            MAX(CASE WHEN pp.param_name='mass_earth'        THEN pp.value END) AS mass_earth,
            MAX(CASE WHEN pp.param_name='density_earth'     THEN pp.value END) AS density_earth,
            MAX(CASE WHEN pp.param_name='eccentricity'      THEN pp.value END) AS eccentricity,
            MAX(CASE WHEN pp.param_name='period_days'       THEN pp.value END) AS period_days,
            MAX(CASE WHEN pp.param_name='eq_temperature_k'  THEN pp.value END) AS eq_temperature_k,
            MAX(CASE WHEN pp.param_name='semi_major_axis_au' THEN pp.value END) AS semi_major_axis_au
        FROM planets p
        LEFT JOIN planet_parameters pp
            ON pp.planet_id=p.planet_id AND pp.is_default=true AND pp.valid_to IS NULL
        WHERE p.status='confirmed'
        GROUP BY p.planet_id, p.planet_name, p.discovery_method
    """)).fetchall()
    return pd.DataFrame(rows, columns=[
        "planet_id", "planet_name", "discovery_method",
        "radius_earth", "mass_earth", "density_earth",
        "eccentricity", "period_days", "eq_temperature_k", "semi_major_axis_au"
    ])


# ── Engine 1a: Mass-Radius Composition ──────────────────────────────────────

# Pre-filter thresholds for data quality
MASS_HARD_CAP = 3000.0        # > ~10 Mjup = brown dwarf or data error
MASS_RADIUS_RATIO_CAP = 100.0 # max plausible M/R^3 ratio (100x Earth density)

def detect_mass_radius_anomalies(df, mass_errors, threshold=3.0):
    """
    Flag planets deviating from ALL Zeng composition curves by >threshold sigma.
    Uses actual per-planet mass uncertainties where available.
    """
    subset = df.dropna(subset=["radius_earth", "mass_earth"])
    # Only consider planets < 4 R_earth (composition curves are not valid for gas giants)
    subset = subset[subset["radius_earth"] < 4.0]
    # Pre-filter: exclude data errors
    subset = subset[subset["mass_earth"] <= MASS_HARD_CAP]
    # Exclude physically impossible mass/radius ratios (> 100x theoretical max density)
    subset = subset[(subset["mass_earth"] / subset["radius_earth"]**3) <= MASS_RADIUS_RATIO_CAP]

    n_with_err = 0
    n_direct = 0
    anomalies = []
    for _, row in subset.iterrows():
        pname = row["planet_name"]
        method = row["discovery_method"] or ""
        is_direct = method in DIRECT_MASS_METHODS
        mass_err = mass_errors.get(pname)

        if mass_err is not None:
            n_with_err += 1
        if is_direct:
            n_direct += 1

        sigma, nearest = distance_to_composition(
            row["radius_earth"], row["mass_earth"],
            mass_err=mass_err, is_direct_mass=is_direct
        )
        if sigma is not None and sigma >= threshold:
            log_r = math.log10(row["radius_earth"])
            expected_mass = 10 ** zeng_earth_like(log_r)
            err_str = f"{mass_err:.1f}" if mass_err else "none"
            anomalies.append({
                "planet_id":       row["planet_id"],
                "planet_name":     pname,
                "anomaly_type":    "mass_radius_outlier",
                "deviation_sigma": sigma,
                "expected_value":  round(expected_mass, 3),
                "observed_value":  round(row["mass_earth"], 3),
                "unit":            "mass_earth",
                "model_reference": ZENG_DOI,
                "nearest_curve":   nearest,
                "mass_err":        err_str,
                "is_direct":       is_direct,
            })

    log(f"Candidates: {len(subset)} (with errors: {n_with_err}, direct mass: {n_direct})")
    return anomalies


# ── Engine 1b: Eccentricity-Period Stability ────────────────────────────────

WINN_DOI = "10.1146/annurev-astro-081817-051853"

def detect_ecc_period_anomalies(df, period_threshold=10.0, ecc_threshold=0.3):
    """
    Flag short-period planets with anomalously high eccentricity.
    Tidal circularization should make P < 10d planets nearly circular.
    """
    subset = df.dropna(subset=["eccentricity", "period_days"])
    subset = subset[(subset["period_days"] < period_threshold) &
                    (subset["eccentricity"] > ecc_threshold)]

    anomalies = []
    for _, row in subset.iterrows():
        # Rough sigma: how many sigma above the expected ~0.05 circular orbit
        expected_ecc = 0.05
        ecc_spread = 0.08  # typical scatter for short-period planets
        sigma = (row["eccentricity"] - expected_ecc) / ecc_spread

        anomalies.append({
            "planet_id":       row["planet_id"],
            "planet_name":     row["planet_name"],
            "anomaly_type":    "ecc_period_unstable",
            "deviation_sigma": round(sigma, 2),
            "expected_value":  expected_ecc,
            "observed_value":  round(row["eccentricity"], 4),
            "period_days":     round(float(row["period_days"]), 4),
            "unit":            "eccentricity",
            "model_reference": WINN_DOI,
        })

    return anomalies


# ── Engine 1c: Density Outlier ──────────────────────────────────────────────

RADIUS_BINS = [
    (0.0,  1.5,  "Rocky"),
    (1.5,  4.0,  "Sub-Neptune"),
    (4.0,  11.0, "Neptune-class"),
    (11.0, 999,  "Giant"),
]

def detect_density_outliers(df, threshold=3.0):
    """Flag planets whose density deviates >3 sigma from their type group mean."""
    subset = df.dropna(subset=["density_earth", "radius_earth"])

    # Assign type bins
    def get_type(r):
        for lo, hi, name in RADIUS_BINS:
            if lo <= r < hi:
                return name
        return "Giant"

    subset = subset.copy()
    subset["planet_type"] = subset["radius_earth"].apply(get_type)

    anomalies = []
    for ptype, group in subset.groupby("planet_type"):
        if len(group) < 10:
            continue

        mean_d = group["density_earth"].mean()
        std_d = group["density_earth"].std()
        if std_d <= 0:
            continue

        for _, row in group.iterrows():
            sigma = abs(row["density_earth"] - mean_d) / std_d
            if sigma >= threshold:
                anomalies.append({
                    "planet_id":       row["planet_id"],
                    "planet_name":     row["planet_name"],
                    "anomaly_type":    "density_outlier",
                    "deviation_sigma": round(sigma, 2),
                    "expected_value":  round(mean_d, 3),
                    "observed_value":  round(row["density_earth"], 3),
                    "unit":            "rho_earth",
                    "model_reference": f"population_{ptype.lower().replace('-','_')}_mean",
                })

    return anomalies


# ── Database write ───────────────────────────────────────────────────────────

def write_anomalies(session, anomalies):
    """Upsert anomaly flags. Key: planet_id + anomaly_type."""
    if not anomalies:
        return 0
        
    def to_native(v):
        """Convert numpy types to Python native for psycopg2."""
        if v is None: return None
        if isinstance(v, (np.floating, np.integer)): return float(v)
        if isinstance(v, np.bool_): return bool(v)
        return v

    existing = session.execute(text(
        "SELECT planet_id, anomaly_type, anomaly_id FROM anomaly_flags"
    )).fetchall()
    existing_map = {(str(pid), atype): str(aid) for pid, atype, aid in existing}

    insert_dicts = []
    update_dicts = []
    for a in anomalies:
        pid = str(a["planet_id"])
        atype = a["anomaly_type"]
        aid = existing_map.get((pid, atype))

        d = {
            "planet_id": pid,
            "anomaly_type": atype,
            "deviation_sigma": to_native(a["deviation_sigma"]),
            "expected_value": to_native(a.get("expected_value")),
            "observed_value": to_native(a.get("observed_value")),
            "unit": a.get("unit"),
            "model_reference": a.get("model_reference"),
            "flagged_at": datetime.now(timezone.utc)
        }

        if aid:
            d["anomaly_id"] = aid
            update_dicts.append(d)
        else:
            d["anomaly_id"] = new_id()
            insert_dicts.append(d)

    chunk_size = 2000
    for i in range(0, len(insert_dicts), chunk_size):
        session.execute(insert(AnomalyFlag), insert_dicts[i:i+chunk_size])
        
    for i in range(0, len(update_dicts), chunk_size):
        session.execute(update(AnomalyFlag), update_dicts[i:i+chunk_size])

    session.commit()
    return len(insert_dicts)


# ── Report ───────────────────────────────────────────────────────────────────

def generate_report(anomalies):
    """Generate markdown anomaly report."""
    date_str = datetime.now().strftime("%Y-%m-%d")

    by_type = {}
    for a in anomalies:
        t = a["anomaly_type"]
        by_type.setdefault(t, []).append(a)

    md = f"""# Anomaly Detection Report
**Date:** {date_str}  |  **Model:** v{MODEL_VERSION}

## Summary
- **Total anomalies flagged:** {len(anomalies)}
- **Mass-radius outliers:** {len(by_type.get('mass_radius_outlier', []))}
- **Ecc-period unstable:** {len(by_type.get('ecc_period_unstable', []))}
- **Density outliers:** {len(by_type.get('density_outlier', []))}

## Mass-Radius Composition Outliers (Zeng et al. 2016)
Planets deviating >3 sigma from ALL solid-sphere composition curves, using per-planet mass uncertainties. These are not "impossible" planets, but rather candidates that likely possess light envelopes (H/He) causing compositional degeneracy. Atmospheric modeling is required to break this degeneracy and determine their true interior structure.

| Planet | Obs M (M_E) | Exp M (M_E) | Sigma | Mass Err | Direct? |
|:-------|:-----------|:-----------|------:|:---------|:--------|
"""
    for a in sorted(by_type.get("mass_radius_outlier", []),
                    key=lambda x: -x["deviation_sigma"])[:30]:
        err_s = a.get('mass_err', '--')
        direct_s = 'Yes' if a.get('is_direct', False) else 'No'
        md += f"| {a['planet_name']:<25s} | {a['observed_value']:.2f} | {a['expected_value']:.2f} | {a['deviation_sigma']:.1f} | {err_s} | {direct_s} |\n"

    md += f"""
## Eccentricity-Period Instability
Short-period planets (P < 10d) with anomalously high eccentricity (e > 0.3).

| Planet | Period (d) | Eccentricity | Deviation (sigma) |
|:-------|:-----------|:-------------|:-------------------|
"""
    for a in sorted(by_type.get("ecc_period_unstable", []),
                    key=lambda x: -x["deviation_sigma"])[:30]:
        p_str = f"{a['period_days']:.2f}" if a.get('period_days') else "--"
        md += f"| {a['planet_name']:<25s} | {p_str} | {a['observed_value']:.3f} | {a['deviation_sigma']:.1f} |\n"

    md += f"""
## Density Outliers (>3 sigma from type mean)

| Planet | Type | Observed (rho_E) | Expected (rho_E) | Deviation (sigma) |
|:-------|:-----|:-----------------|:-----------------|:-------------------|
"""
    for a in sorted(by_type.get("density_outlier", []),
                    key=lambda x: -x["deviation_sigma"])[:30]:
        ptype = a.get("model_reference", "").replace("population_", "").replace("_mean", "")
        md += f"| {a['planet_name']:<25s} | {ptype:<12s} | {a['observed_value']:.2f} | {a['expected_value']:.2f} | {a['deviation_sigma']:.1f} |\n"

    md += f"""
## References
- Zeng et al. (2016) Mass-Radius Relation for Rocky Planet Interiors. DOI: {ZENG_DOI}
- Winn & Fabrycky (2015) Occurrence and Architecture of Exoplanetary Systems. DOI: {WINN_DOI}
"""

    out_path = OUTPUT_DIR / f"anomaly_report_{date_str}_v{MODEL_VERSION}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── Main ─────────────────────────────────────────────────────────────────────

def run(anomaly_type=None, dry_run=False):
    print(f"\nAnomaly Detector v{MODEL_VERSION}")
    print(f"  Type filter: {anomaly_type or 'all'}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    session = Session()
    try:
        print("\nLoading planet data ...")
        df = fetch_planet_data(session)
        print(f"  {len(df)} planets loaded")
        print(f"  With radius+mass: {df.dropna(subset=['radius_earth','mass_earth']).shape[0]}")
        print(f"  With ecc+period:  {df.dropna(subset=['eccentricity','period_days']).shape[0]}")
        print(f"  With density:     {df.dropna(subset=['density_earth']).shape[0]}")

        all_anomalies = []

        # Load mass errors from enriched CSV
        mass_errors = {}
        if anomaly_type in (None, "mass_radius"):
            print("\nLoading mass uncertainties from CSV ...")
            mass_errors = load_mass_errors()
            print(f"  {len(mass_errors)} planets with archive mass errors")

        # 1a: Mass-radius
        if anomaly_type in (None, "mass_radius"):
            print(f"\n[1/3] Mass-radius composition check (per-planet sigma) ...")
            mr = detect_mass_radius_anomalies(df, mass_errors)
            print(f"  Flagged: {len(mr)} mass-radius outliers")
            for a in sorted(mr, key=lambda x: -x["deviation_sigma"])[:5]:
                dm = 'D' if a.get('is_direct') else 'I'
                print(f"    {a['planet_name']:<25s}  {a['deviation_sigma']:.1f} sigma  "
                      f"obs={a['observed_value']:.1f}  exp={a['expected_value']:.1f} M_E  "
                      f"err={a.get('mass_err','?')}  [{dm}]")
            all_anomalies.extend(mr)

        # 1b: Ecc-period
        if anomaly_type in (None, "ecc_period"):
            print(f"\n[2/3] Eccentricity-period stability check ...")
            ep = detect_ecc_period_anomalies(df)
            print(f"  Flagged: {len(ep)} ecc-period unstable")
            for a in sorted(ep, key=lambda x: -x["deviation_sigma"])[:5]:
                print(f"    {a['planet_name']:<25s}  e={a['observed_value']:.3f}  "
                      f"{a['deviation_sigma']:.1f} sigma")
            all_anomalies.extend(ep)

        # 1c: Density
        if anomaly_type in (None, "density"):
            print(f"\n[3/3] Density outlier detection ...")
            do = detect_density_outliers(df)
            print(f"  Flagged: {len(do)} density outliers")
            for a in sorted(do, key=lambda x: -x["deviation_sigma"])[:5]:
                print(f"    {a['planet_name']:<25s}  {a['deviation_sigma']:.1f} sigma  "
                      f"obs={a['observed_value']:.2f}  exp={a['expected_value']:.2f} rho_E")
            all_anomalies.extend(do)

        print(f"\n{'='*60}")
        print(f"  Total anomalies: {len(all_anomalies)}")

        if dry_run:
            print(f"\n[DRY RUN] No database writes.")
        elif all_anomalies:
            print(f"\nWriting to database ...")
            n = write_anomalies(session, all_anomalies)
            print(f"  Written/updated: {n} anomaly flags")

        print(f"\nGenerating report ...")
        out_path = generate_report(all_anomalies)
        print(f"  Saved -> {out_path}")

    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback; traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Anomaly Detector")
    parser.add_argument("--type", type=str, default=None,
                        choices=["mass_radius", "ecc_period", "density"],
                        help="Run only one detection engine")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(anomaly_type=args.type, dry_run=args.dry_run)
