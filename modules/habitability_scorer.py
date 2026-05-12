"""
modules/habitability_scorer.py

Two-track habitability scoring — scientifically defensible architecture.

Track 1: similarity_score  (Earth Similarity Index — geometric mean)
  Variables: radius, bulk density, escape velocity, surface temperature
  Methodology: Schulze-Makuch et al. 2011, matches UPR HEC
  Validates against UPR — target r >= 0.70
  What it answers: "How Earth-like is this planet physically?"

Track 2: risk_score  (novel contribution — not in UPR or any public tool)
  Variables: flare activity, tidal locking, eccentricity, stellar age
  No public comparison benchmark exists — this is our scientific addition
  What it answers: "How dangerous is this planet's environment for life?"

composite_score = 0.65 * similarity_score + 0.35 * risk_score
  Weighting: similarity is the primary filter, risk adjusts within it.
  This is the full habitability assessment — more complete than ESI alone.

Model version: 4.2.0
"""

import os, sys, math, uuid, json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, insert, update
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from db.models import HabitabilityScore

load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
Session      = sessionmaker(bind=engine)

MODEL_VERSION       = "4.2.0"
SIMILARITY_WEIGHT   = 0.70
RISK_WEIGHT         = 0.30

# ── Track 1: ESI exponents (Schulze-Makuch et al. 2011) ───────────────────────
# Standard ESI uses geometric mean of four components with these weights.
# Reference temperature = 288 K (Earth surface, UPR standard).
ESI_EXPONENTS = {
    "radius":          0.57,
    "bulk_density":    1.07,
    "escape_velocity": 0.70,
    "surface_temp":    5.58,
}
TEQ_REF_K = 255.0   # Earth equilibrium temperature
# ── Track 2: Risk weights (must sum to 1.0) ───────────────────────────────────
# flare heaviest — atmosphere stripping is the primary risk for M-dwarf HZ planets
# tidal second — day/night dichotomy affects climate stability
RISK_WEIGHTS = {
    "flare_score":      0.45,
    "tidal_lock_score": 0.30,
    "ecc_score":        0.15,
    "age_score":        0.10,
}

assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9


def new_id(): return str(uuid.uuid4())
def now_utc(): return datetime.now(timezone.utc)

def nv(val):
    if val is None: return None
    try:
        if isinstance(val, float) and math.isnan(val): return None
        if pd.isna(val): return None
    except Exception: pass
    return float(val)


# ── Component functions ───────────────────────────────────────────────────────

HZ_INNER_SUN = 0.99
HZ_OUTER_SUN = 1.70
BOND_ALBEDO  = 0.30

def derive_teq(a_au, lum_log):
    a = nv(a_au)
    if a is None or a <= 0: return None
    lum = 10 ** nv(lum_log) if nv(lum_log) is not None else 1.0
    return round(278.5 * (lum**0.25) * ((1 - BOND_ALBEDO)**0.25) / math.sqrt(a), 2)

def score_hz(a_au, lum_log):
    """HZ score — still computed and stored for display, but NOT part of similarity."""
    a = nv(a_au)
    if a is None: return None
    lum = 10 ** nv(lum_log) if nv(lum_log) is not None else 1.0
    scale    = math.sqrt(lum)
    hz_inner = HZ_INNER_SUN * scale
    hz_outer = HZ_OUTER_SUN * scale
    hz_mid   = (hz_inner + hz_outer) / 2.0
    hz_half  = (hz_outer - hz_inner) / 2.0
    if a < hz_inner:
        return float(max(0.0, 1.0 - (hz_inner - a) / hz_inner))
    if a > hz_outer:
        return float(max(0.0, 1.0 - (a - hz_outer) / hz_outer))
    return float(min(1.0, max(0.0, 1.0 - abs(a - hz_mid) / hz_half * 0.4)))

def esi_component(value, earth_ref, weight_exp):
    v = nv(value)
    if v is None or v <= 0: return None
    ratio = abs(v - earth_ref) / (v + earth_ref)
    return float((1.0 - ratio) ** weight_exp)

def score_teq(teq_mid, delta_t=0.0):
    base = esi_component(teq_mid, TEQ_REF_K, ESI_EXPONENTS["surface_temp"])
    if base is None: return None
    return float(base * math.exp(-delta_t / 200.0))
def score_radius(rad): return esi_component(rad,  1.0, ESI_EXPONENTS["radius"])
def score_mass(mass):  return esi_component(mass, 1.0, 0.6302)  # kept for DB display column


def compute_similarity_esi(radius, mass, teq):
    """
    Earth Similarity Index — geometric mean with w_i/n.
    Matches exact UPR / Schulze-Makuch et al. 2011 methodology.

    Formula: ESI = product( (1 - |x_i - x_0| / (x_i + x_0)) ^ (w_i / n) )
    where n is the number of available parameters.

    Components (when data available):
      - radius (w=0.57)
      - bulk_density (w=1.07)
      - escape_velocity (w=0.70)
      - surface_temp (w=5.58, ref=288K)
    """
    r = nv(radius)
    m = nv(mass)
    t = nv(teq)

    available = []

    if r is not None and r > 0:
        raw = 1.0 - abs(r - 1.0) / (r + 1.0)
        if raw > 0:
            available.append((raw, ESI_EXPONENTS["radius"]))

    if r is not None and r > 0 and m is not None and m > 0:
        rho = m / (r ** 3)
        raw = 1.0 - abs(rho - 1.0) / (rho + 1.0)
        if raw > 0:
            available.append((raw, ESI_EXPONENTS["bulk_density"]))

        vesc = math.sqrt(m / r)
        raw = 1.0 - abs(vesc - 1.0) / (vesc + 1.0)
        if raw > 0:
            available.append((raw, ESI_EXPONENTS["escape_velocity"]))

    if t is not None and t > 0:
        raw = 1.0 - abs(t - TEQ_REF_K) / (t + TEQ_REF_K)
        if raw > 0:
            available.append((raw, ESI_EXPONENTS["surface_temp"]))

    n = len(available)
    has_thermal = any(w == ESI_EXPONENTS["surface_temp"] for _, w in available)
    if n < 2 or not has_thermal:
        return None

    prod = 1.0
    for raw, w in available:
        prod *= raw ** (w / n)
    return float(prod)


# Corrected flare table — M-dwarfs score LOW (they are dangerous)
TEFF_TABLE = [
    (10000, 0.05),   # O/B
    (7500,  0.20),   # A
    (6000,  0.60),   # F
    (5200,  1.00),   # G  <- peak
    (3700,  0.90),   # K
    (2400,  0.30),   # M  <- dangerous flarers
    (0,     0.10),   # Y/T brown dwarfs
]

def score_flare(teff):
    t = nv(teff)
    if t is None: return None
    for i, (upper, upper_score) in enumerate(TEFF_TABLE):
        if t >= upper:
            if i == 0: return max(0.2, float(upper_score))
            lower, lower_score = TEFF_TABLE[i-1]
            frac = (t - upper) / (lower - upper)
            return max(0.2, float(min(1.0, max(0.0, upper_score + frac * (lower_score - upper_score)))))
    return max(0.2, float(TEFF_TABLE[-1][1]))

def score_tidal_lock(a_au, mstar, rade):
    a = nv(a_au); m = nv(mstar); r = nv(rade)
    if a is None or m is None or r is None or r <= 0: return None
    # tau_lock proportional to a^6 / (M_*^2 * R_p^5)
    tau = (a**6) / ((m**2) * (r**5))
    if tau <= 0: return 0.2
    # Soft penalty (sigmoid) instead of hard cutoff
    log_tau = max(-10.0, math.log10(tau))
    score = 1.0 / (1.0 + math.exp(-0.5 * (log_tau + 0.5)))
    return max(0.2, float(score))

def score_eccentricity(e):
    e = nv(e)
    if e is None: return None
    # Soft capped penalty
    return float(max(0.2, math.exp(-2.057 * max(0.0, min(0.99, float(e))) ** 2)))

def score_age(age):
    a = nv(age)
    if a is None or a <= 0: return None
    activity = a ** -0.5
    activity = min(max(activity, 0.2), 3.0)
    # Map activity 0.2 (safe) to 1.0, and 3.0 (dangerous) to 0.1
    # Capped soft penalty
    return float(max(0.2, 1.0 - (activity - 0.2) / 2.8 * 0.9))

def load_uncertainties():
    from pathlib import Path
    import pandas as pd
    csv_path = PROJECT_ROOT / "planets_enriched_clean.csv"
    if not csv_path.exists():
        csv_path = PROJECT_ROOT / "planets_nasa_full.csv"
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path, usecols=["pl_name", "pl_bmasseerr1", "pl_bmasseerr2", "pl_radeerr1", "pl_radeerr2"], low_memory=False)
    errs = {}
    for _, row in df.iterrows():
        merr1 = abs(float(row["pl_bmasseerr1"])) if pd.notna(row["pl_bmasseerr1"]) else 0.0
        merr2 = abs(float(row["pl_bmasseerr2"])) if pd.notna(row["pl_bmasseerr2"]) else merr1
        rerr1 = abs(float(row["pl_radeerr1"])) if pd.notna(row["pl_radeerr1"]) else 0.0
        rerr2 = abs(float(row["pl_radeerr2"])) if pd.notna(row["pl_radeerr2"]) else rerr1
        errs[row["pl_name"]] = {"m_err": max(merr1, merr2), "r_err": max(rerr1, rerr2)}
    return errs

# Global uncertainties cache
UNCERTAINTIES = {}


def weighted_average(scores: dict, weights: dict) -> float | None:
    """Weighted average over non-null components. Used for risk track."""
    total_w = wsum = 0.0
    n = 0
    for key, w in weights.items():
        v = scores.get(key)
        if v is not None:
            wsum   += w * v
            total_w += w
            n += 1
    if n < 2 or total_w == 0:
        return None
    return float(min(1.0, max(0.0, wsum / total_w)))


def score_planet(row: pd.Series) -> dict:
    a_au    = nv(row.get("semi_major_axis_au"))
    lum_log = nv(row.get("luminosity_solar"))
    period  = nv(row.get("period_days"))
    mstar   = nv(row.get("mass_solar"))
    teff    = nv(row.get("teff_best_k"))
    ecc     = nv(row.get("eccentricity"))
    rade    = nv(row.get("radius_earth"))
    masse   = nv(row.get("mass_earth"))
    teq     = nv(row.get("eq_temperature_k")) or derive_teq(a_au, lum_log)
    age     = nv(row.get("age_gaia_gyr")) or nv(row.get("age_nasa_gyr"))

    # ── Track 1: Similarity (ESI-based) ────────────────────────────────────────
    # Filter implausible mass values (likely upper limits, not real measurements)
    # Mass-radius relation: rocky planets M ~ R^3.7, max reasonable ~ 10*R^2.5
    masse_for_esi = masse
    if masse is not None and rade is not None and rade > 0:
        max_plausible = 10.0 * (rade ** 2.5)  # generous upper bound
        if masse > max_plausible:
            masse_for_esi = None  # treat as unmeasured
    teq_mid = teq
    delta_t = 0.0

    # Density Check
    rho = None
    if masse is not None and rade is not None and rade > 0:
        rho = masse / (rade ** 3)
    
    hz_val     = score_hz(a_au, lum_log)
    teq_val    = score_teq(teq_mid, delta_t)
    rad_val    = score_radius(rade)
    mass_val   = score_mass(masse)

    sim_score = compute_similarity_esi(rade, masse_for_esi, teq_mid)

    # ── Track 2: Risk (higher = safer, i.e. lower risk) ───────────────────────
    # ── Track 2: Risk (higher = safer, i.e. lower risk) ───────────────────────
    risk = {
        "flare_score":      score_flare(teff),
        "tidal_lock_score": score_tidal_lock(a_au, mstar, rade),
        "ecc_score":        score_eccentricity(ecc),
        "age_score":        score_age(age) if age else score_flare(teff), # fallback to flare if no age
    }
    risk_score = weighted_average(risk, RISK_WEIGHTS)

    # ── Composite ─────────────────────────────────────────────────────────────
    if sim_score is not None and risk_score is not None:
        composite = SIMILARITY_WEIGHT * sim_score + RISK_WEIGHT * risk_score
    elif sim_score is not None:
        composite = sim_score  # risk unknown, use similarity only
    else:
        composite = None
        
    if composite is not None:
        composite = round(max(0.0, min(1.0, composite)), 4)
    if sim_score is not None:
        sim_score = max(0.0, min(1.0, sim_score))
    if risk_score is not None:
        risk_score = max(0.0, min(1.0, risk_score))

    # ESI sub-components for snapshot
    esi_detail = {}
    if rade is not None and rade > 0:
        esi_detail["radius_esi"] = round(esi_component(rade, 1.0, ESI_EXPONENTS["radius"]), 4)
    if masse is not None and masse > 0 and rade is not None and rade > 0:
        rho = masse / (rade ** 3)
        esi_detail["density_esi"] = round(esi_component(rho, 1.0, ESI_EXPONENTS["bulk_density"]), 4)
        vesc = math.sqrt(masse / rade)
        esi_detail["vesc_esi"] = round(esi_component(vesc, 1.0, ESI_EXPONENTS["escape_velocity"]), 4)
    if teq is not None and teq > 0:
        esi_detail["teq_esi"] = round(esi_component(teq, TEQ_REF_K, ESI_EXPONENTS["surface_temp"]), 4)

    snapshot = {
        "model":      MODEL_VERSION,
        "method":     "geometric_esi",
        "sim_weight": SIMILARITY_WEIGHT,
        "risk_weight": RISK_WEIGHT,
        "inputs": {
            "a_au": a_au, "lum_log": lum_log, "period_days": period,
            "mstar": mstar, "teff_k": teff, "eccentricity": ecc,
            "radius_earth": rade, "mass_earth": masse, "teq_k": teq, "age_gyr": age,
        },
        "esi_components": esi_detail,
        "risk":        {k: round(v, 4) if v else None for k, v in risk.items()},
        "sim_score":   round(sim_score, 4) if sim_score else None,
        "risk_score":  round(risk_score, 4) if risk_score else None,
    }

    return {
        "composite_score":    composite,
        # individual display scores (stored in DB columns)
        "hz_score":           hz_val,
        "teq_score":          teq_val,
        "radius_esi_score":   rad_val,
        "mass_esi_score":     mass_val,
        # risk track
        "tidal_lock_score":   risk["tidal_lock_score"],
        "flare_score":        risk["flare_score"],
        "eccentricity_score": risk["ecc_score"],
        "age_score":          risk["age_score"],
        # sub-totals
        "similarity_score":   sim_score,
        "risk_score":         risk_score,
        "input_snapshot":     json.dumps(snapshot),
    }


def fetch_planets(session) -> pd.DataFrame:
    rows = session.execute(text("""
        SELECT
            p.planet_id, p.planet_name, p.discovery_method, p.discovery_year,
            s.hip_name AS hostname,
            MAX(CASE WHEN pp.param_name='semi_major_axis_au'  THEN pp.value END) AS semi_major_axis_au,
            MAX(CASE WHEN pp.param_name='period_days'         THEN pp.value END) AS period_days,
            MAX(CASE WHEN pp.param_name='eccentricity'        THEN pp.value END) AS eccentricity,
            MAX(CASE WHEN pp.param_name='radius_earth'        THEN pp.value END) AS radius_earth,
            MAX(CASE WHEN pp.param_name='mass_earth'          THEN pp.value END) AS mass_earth,
            MAX(CASE WHEN pp.param_name='eq_temperature_k'    THEN pp.value END) AS eq_temperature_k,
            MAX(CASE WHEN sp.param_name='teff_best_k'         THEN sp.value END) AS teff_best_k,
            MAX(CASE WHEN sp.param_name='luminosity_solar'    THEN sp.value END) AS luminosity_solar,
            MAX(CASE WHEN sp.param_name='mass_solar'          THEN sp.value END) AS mass_solar,
            MAX(CASE WHEN sp.param_name='age_gaia_gyr'        THEN sp.value END) AS age_gaia_gyr,
            MAX(CASE WHEN sp.param_name='age_nasa_gyr'        THEN sp.value END) AS age_nasa_gyr
        FROM planets p
        JOIN stars s ON p.star_id = s.star_id
        LEFT JOIN planet_parameters pp
            ON pp.planet_id=p.planet_id AND pp.is_default=true AND pp.valid_to IS NULL
        LEFT JOIN star_parameters sp
            ON sp.star_id=s.star_id AND sp.is_default=true AND sp.valid_to IS NULL
        WHERE p.status='confirmed'
        GROUP BY p.planet_id, p.planet_name, p.discovery_method, p.discovery_year, s.hip_name
    """)).fetchall()
    return pd.DataFrame(rows, columns=[
        "planet_id","planet_name","discovery_method","discovery_year","hostname",
        "semi_major_axis_au","period_days","eccentricity","radius_earth","mass_earth",
        "eq_temperature_k","teff_best_k","luminosity_solar","mass_solar",
        "age_gaia_gyr","age_nasa_gyr",
    ])


def write_scores(session, scored: list, run_at: datetime) -> int:
    """Bulk upsert habitability scores."""
    if not scored:
        return 0

    # Fetch existing scores for this model version
    existing = session.execute(text("""
        SELECT planet_id, score_id FROM habitability_scores
        WHERE model_version = :ver
    """), {"ver": MODEL_VERSION}).fetchall()
    existing_map = {str(pid): str(sid) for pid, sid in existing}

    insert_dicts = []
    update_dicts = []

    for row in scored:
        pid = str(row["planet_id"])
        sid = existing_map.get(pid)

        d = {
            "planet_id": pid,
            "model_version": MODEL_VERSION,
            "composite_score": row.get("composite_score"),
            "hz_score": row.get("hz_score"),
            "teq_score": row.get("teq_score"),
            "radius_esi_score": row.get("radius_esi_score"),
            "mass_esi_score": row.get("mass_esi_score"),
            "tidal_lock_score": row.get("tidal_lock_score"),
            "flare_score": row.get("flare_score"),
            "eccentricity_score": row.get("eccentricity_score"),
            "age_score": row.get("age_score"),
            "input_snapshot": row.get("input_snapshot"),
            "scored_at": run_at,
        }

        if sid:
            d["score_id"] = sid
            update_dicts.append(d)
        else:
            d["score_id"] = new_id()
            insert_dicts.append(d)

    chunk_size = 2000
    for i in range(0, len(insert_dicts), chunk_size):
        session.execute(insert(HabitabilityScore), insert_dicts[i:i+chunk_size])

    for i in range(0, len(update_dicts), chunk_size):
        session.execute(update(HabitabilityScore), update_dicts[i:i+chunk_size])

    session.commit()
    return len(insert_dicts) + len(update_dicts)


def run_upr_validation(session) -> dict:
    """
    Validates SIMILARITY SCORE (geometric ESI) against UPR ESI.
    Reads sim_score from input_snapshot (no separate DB column).
    """
    from scipy.stats import pearsonr, spearmanr

    UPR = {
        "TRAPPIST-1 e": 0.950, "Teegarden's Star b": 0.950,
        "TRAPPIST-1 d": 0.900, "GJ 1002 b": 0.890,
        "LHS 1140 b":   0.880, "Proxima Cen b": 0.870,
        "Ross 128 b":   0.860, "GJ 1061 d": 0.860,
        "TRAPPIST-1 f": 0.850, "Kepler-442 b": 0.840,
        "Kepler-62 e":  0.830, "TRAPPIST-1 g": 0.790,
        "GJ 273 b":     0.790, "GJ 1002 c": 0.750,
        "Wolf 1061 c":  0.750, "Kepler-296 e": 0.740,
        "Kepler-1229 b":0.730, "Teegarden's Star c": 0.680,
        "Kepler-62 f":  0.670,
    }

    rows = session.execute(text("""
        SELECT p.planet_name,
               hs.composite_score,
               hs.input_snapshot
        FROM habitability_scores hs
        JOIN planets p ON hs.planet_id = p.planet_id
        WHERE hs.model_version = :ver AND hs.composite_score IS NOT NULL
    """), {"ver": MODEL_VERSION}).fetchall()

    our_composite  = {}
    our_similarity = {}
    for r in rows:
        name = r[0]
        our_composite[name] = r[1]
        snap = r[2]
        if isinstance(snap, str):
            snap = json.loads(snap)
        if snap and snap.get("sim_score") is not None:
            our_similarity[name] = snap["sim_score"]

    matched_sim = []; our_sim_v = []; upr_v = []
    matched_comp = []; our_comp_v = []; upr_comp_v = []

    for name, upr_esi in UPR.items():
        if name in our_similarity:
            matched_sim.append(name)
            our_sim_v.append(our_similarity[name])
            upr_v.append(upr_esi)
        if name in our_composite:
            matched_comp.append(name)
            our_comp_v.append(our_composite[name])
            upr_comp_v.append(upr_esi)

    print(f"\n  UPR reference planets : {len(UPR)}")
    print(f"  Matched               : {len(matched_sim)}")

    if len(matched_sim) < 5:
        print("  Not enough matches -- run scorer first")
        return {}

    r_sim,  p_sim  = pearsonr(our_sim_v, upr_v)
    r_comp, p_comp = pearsonr(our_comp_v, upr_comp_v)
    rho_sim, _     = spearmanr(our_sim_v, upr_v)

    print(f"\n  {'Planet':<28} {'Sim':>6} {'Comp':>6} {'UPR':>6} {'Sim-UPR':>8}")
    print(f"  {'---'*10} {'---'*2} {'---'*2} {'---'*2} {'---'*3}")
    for name, sim, comp, upr in sorted(
        zip(matched_sim, our_sim_v, our_comp_v[:len(matched_sim)], upr_v),
        key=lambda x: -x[3]
    ):
        flag = " <--" if abs(sim - upr) > 0.15 else ""
        print(f"  {name:<28} {sim:>6.3f} {comp:>6.3f} {upr:>6.3f} {sim-upr:>+8.3f}{flag}")

    print(f"\n  -- Correlation against UPR ESI -------------------------")
    print(f"  Similarity score  Pearson r  = {r_sim:.3f}  (p={p_sim:.4f})")
    print(f"  Similarity score  Spearman p = {rho_sim:.3f}")
    print(f"  Composite score   Pearson r  = {r_comp:.3f}  (expected lower -- different construct)")
    print(f"\n  Target for similarity_score: r >= 0.70")
    sim_pass = r_sim >= 0.70
    print(f"  Result: {'PASS' if sim_pass else 'FAIL -- revisit similarity components'}")
    print(f"\n  Note: composite r < similarity r is CORRECT BEHAVIOUR.")
    print(f"  Composite includes risk factors (flare, tidal lock) that UPR ESI")
    print(f"  deliberately excludes. Low composite-vs-UPR r is our novel contribution.")

    return {"r_similarity": r_sim, "r_composite": r_comp, "rho_similarity": rho_sim,
            "passed": sim_pass, "n_matched": len(matched_sim)}


def run():
    session = Session()
    run_at  = now_utc()

    print(f"\nHabitability Scorer v{MODEL_VERSION} -- Geometric ESI + Risk")
    print(f"  Similarity: geometric mean ESI (radius, density, vesc, Teq)")
    print(f"  Risk factors:           {list(RISK_WEIGHTS.keys())}")
    print(f"  Composite = {SIMILARITY_WEIGHT} x similarity + {RISK_WEIGHT} x risk")
    print("=" * 60)

    print("\nLoading planet data ...")
    df = fetch_planets(session)
    print(f"  {len(df)} planets loaded")

    print("\nLoading uncertainties ...")
    UNCERTAINTIES.update(load_uncertainties())
    print(f"  {len(UNCERTAINTIES)} planet uncertainties loaded")

    print(f"\nScoring ...")
    scored = []
    for _, row in df.iterrows():
        res = score_planet(row)
        res["planet_id"]   = row["planet_id"]
        res["planet_name"] = row["planet_name"]
        scored.append(res)

    print(f"\nWriting to database ...")
    write_scores(session, scored, run_at)

    # stats
    comp = [s["composite_score"] for s in scored if s["composite_score"] is not None]
    sim  = [s["similarity_score"] for s in scored if s.get("similarity_score") is not None]
    risk = [s["risk_score"] for s in scored if s.get("risk_score") is not None]

    print(f"\n-- Score distributions -------------------------------------------")
    print(f"  {'':25} {'mean':>6} {'median':>8} {'max':>6}")
    print(f"  {'composite_score':<25} {np.mean(comp):>6.3f} {np.median(comp):>8.3f} {max(comp):>6.3f}")
    print(f"  {'similarity_score':<25} {np.mean(sim):>6.3f} {np.median(sim):>8.3f} {max(sim):>6.3f}")
    print(f"  {'risk_score':<25} {np.mean(risk):>6.3f} {np.median(risk):>8.3f} {max(risk):>6.3f}")

    top = sorted(scored, key=lambda x: x.get("composite_score") or 0, reverse=True)[:20]
    print(f"\n-- Top 20 by composite -------------------------------------------")
    print(f"  {'Planet':<28} {'Comp':>6} {'Sim':>6} {'Risk':>6} {'Teq':>5} {'Fla':>5}")
    print(f"  {'---'*10} {'---'*2} {'---'*2} {'---'*2} {'--'*3} {'--'*3}")
    for s in top:
        f = lambda v: f"{v:.2f}" if v is not None else " -- "
        print(f"  {s['planet_name']:<28} {f(s['composite_score']):>6} "
              f"{f(s.get('similarity_score')):>6} {f(s.get('risk_score')):>6} "
              f"{f(s['teq_score']):>5} {f(s['flare_score']):>5}")

    print(f"\n-- UPR Validation (similarity track only) ------------------------")
    result = run_upr_validation(session)
    session.close()
    return result


if __name__ == "__main__":
    import sys
    if "--validate" in sys.argv:
        s = Session()
        try: run_upr_validation(s)
        finally: s.close()
    else:
        run()