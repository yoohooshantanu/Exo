"""
JWST Cycle 1-3 Allocation Validation Module.

Validates Exo's discovery prioritization against real-world spectroscopic proposals
approved across JWST Cycles 1, 2, and 3.

Scientific Methodology & Limitations:
1. Target Selection Context:
   JWST target allocations reflect decisions by Telescope Allocation Committees (TAC),
   balancing transit signal-to-noise (S/N), host star brightness, scheduling windows,
   and community proposal interest. Historical selection is an operational benchmark
   measuring observability capture, NOT physical ground truth for habitability.
2. Temporal Constraint:
   Only exoplanets discovered on or before 2023 (discovery_year <= 2023) are evaluated to
   prevent post-cycle discovery look-ahead leakage.
3. Intra-System Correlation:
   Standard errors are clustered on host stars (star_id) to account for correlated
   allocation probability among planets orbiting the same host star.
4. Selection Orthogonality:
   The selection independence track analyzes whether physical triage ranking is decoupled
   from operational transit bias (OR ~ 1.0, 95% CI containing 1.0).
"""
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sqlalchemy import create_engine
import dotenv
import matplotlib.pyplot as plt
import seaborn as sns


def _get_csv_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent / "jwst_targets.csv",
        Path(__file__).resolve().parent.parent / "jwst_targets.csv",
        Path("jwst_targets.csv"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError("Could not locate jwst_targets.csv in validation module or workspace root")


def compute_jwst_validation_metrics(engine):
    """
    Compute live logistic regression metrics for JWST Cycle 1-3 allocations.
    
    Returns structured dictionary with odds ratios, p-values, 95% confidence intervals,
    sample counts, and evaluation status.
    """
    csv_path = _get_csv_path()
    jwst_df = pd.read_csv(csv_path)
    jwst_targets = set(jwst_df['pl_name'].str.strip())

    query = """
    SELECT 
        p.planet_name,
        p.star_id,
        p.discovery_year,
        mvs.physical_triage_index,
        mvs.observability_index
    FROM planets p
    LEFT JOIN mv_discovery_scores mvs ON mvs.planet_id = p.planet_id
    WHERE p.status = 'confirmed' 
      AND mvs.physical_triage_index IS NOT NULL 
      AND mvs.observability_index IS NOT NULL
    """

    df = pd.read_sql(query, engine)
    # Temporal filtering: restrict to planets discovered on or before 2023
    df = df[df['discovery_year'] <= 2023].copy()
    df['is_jwst_target'] = df['planet_name'].isin(jwst_targets).astype(int)

    n_samples = len(df)
    n_targets = int(df['is_jwst_target'].sum())

    # Robustness checks: guard against insufficient samples, zero variance, complete separation, or collinear predictors
    if (
        n_samples < 20
        or n_targets == 0
        or n_targets == n_samples
        or df['observability_index'].std() == 0
        or df['physical_triage_index'].std() == 0
    ):
        return {
            "obs_or": 1.0,
            "obs_p": "1.00e+00",
            "obs_p_val": 1.0,
            "obs_ci": [1.0, 1.0],
            "triage_or": 1.0,
            "triage_p": "1.00e+00",
            "triage_p_val": 1.0,
            "triage_ci": [1.0, 1.0],
            "n_samples": n_samples,
            "passed": False,
            "inference_method": "insufficient_data",
        }

    # Standardize continuous predictors
    df['triage_z'] = (df['physical_triage_index'] - df['physical_triage_index'].mean()) / df['physical_triage_index'].std()
    df['obs_z'] = (df['observability_index'] - df['observability_index'].mean()) / df['observability_index'].std()

    X = sm.add_constant(df[['triage_z', 'obs_z']])
    y = df['is_jwst_target']

    # Clustered standard errors by host star (star_id)
    groups = pd.factorize(df['star_id'])[0]
    inference_method = "cluster_robust"
    try:
        res = sm.Logit(y, X).fit(cov_type='cluster', cov_kwds={'groups': groups}, disp=0)
    except Exception:
        try:
            res = sm.Logit(y, X).fit(cov_type='HC1', disp=0)
            inference_method = "HC1_robust_fallback"
        except Exception:
            res = sm.Logit(y, X).fit(disp=0)
            inference_method = "ordinary_fallback"

    obs_or = float(np.exp(res.params['obs_z']))
    obs_p = float(res.pvalues['obs_z'])
    triage_or = float(np.exp(res.params['triage_z']))
    triage_p = float(res.pvalues['triage_z'])

    conf = res.conf_int()
    # Unrounded raw confidence intervals used for statistical equivalence testing
    obs_ci_raw = [float(np.exp(conf.loc['obs_z'][0])), float(np.exp(conf.loc['obs_z'][1]))]
    triage_ci_raw = [float(np.exp(conf.loc['triage_z'][0])), float(np.exp(conf.loc['triage_z'][1]))]

    # Decision criteria evaluated on UNROUNDED parameters:
    # 1. Observability power: OR >= 2.0 and p < 1e-4 (strong positive capture of operational observability)
    # 2. Historical Selection Independence (Equivalence Testing):
    #    Evaluates whether physical triage ranking is decoupled from historical operational transit bias.
    #    Equivalence bounds: OR in [0.70, 1.45] (symmetric interval on log-odds scale |beta| < 0.37).
    #    Passed when both the unrounded point estimate and unrounded 95% CI fall within [0.70, 1.45].
    obs_passed = bool(obs_or >= 2.0 and obs_p < 1e-4)
    triage_passed = bool(
        0.70 <= triage_or <= 1.45
        and triage_ci_raw[0] >= 0.70
        and triage_ci_raw[1] <= 1.45
    )

    # Round only the display values
    obs_ci = [round(obs_ci_raw[0], 2), round(obs_ci_raw[1], 2)]
    triage_ci = [round(triage_ci_raw[0], 2), round(triage_ci_raw[1], 2)]

    return {
        "obs_or": round(obs_or, 2),
        "obs_p": f"{obs_p:.2e}",
        "obs_p_val": obs_p,
        "obs_ci": obs_ci,
        "triage_or": round(triage_or, 2),
        "triage_p": f"{triage_p:.2e}",
        "triage_p_val": triage_p,
        "triage_ci": triage_ci,
        "n_samples": n_samples,
        "passed": bool(obs_passed and triage_passed),
        "obs_passed": obs_passed,
        "triage_passed": triage_passed,
        "inference_method": inference_method,
    }


def main():
    dotenv.load_dotenv('.env')
    db_url = os.environ.get('DATABASE_URL')
    if db_url and db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    engine = create_engine(db_url)
    metrics = compute_jwst_validation_metrics(engine)

    print("=" * 70)
    print("JWST CYCLE 1-3 TARGET ALLOCATION EMPIRICAL VALIDATION")
    print("=" * 70)
    print(f"Sample Size (pre-2024 confirmed systems): {metrics['n_samples']}")
    print(f"Observability Power: OR = {metrics['obs_or']} (95% CI: {metrics['obs_ci']}, p = {metrics['obs_p']})")
    print(f"Selection Independence: OR = {metrics['triage_or']} (95% CI: {metrics['triage_ci']}, p = {metrics['triage_p']})")
    print(f"Validation Status: {'PASS' if metrics['passed'] else 'FAIL'}")


if __name__ == '__main__':
    main()
