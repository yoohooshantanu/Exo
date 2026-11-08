import sys
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
from pathlib import Path

# Fix path to import modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.xuv_escape_model import run_model
from modules.habitability_scorer import score_flare

def spectral_class(teff):
    if teff >= 5200: return 'G'
    if teff >= 3700: return 'K'
    return 'M'

def bootstrap_spearman(x, y, n_iter=1000, ci=0.95):
    """Compute Spearman rho with bootstrap confidence interval."""
    # Remove NaNs
    mask = ~np.isnan(x) & ~np.isnan(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 5:
        return np.nan, (np.nan, np.nan)
        
    rho_point, _ = stats.spearmanr(x, y)
    
    rhos = []
    for _ in range(n_iter):
        idx = np.random.randint(0, n, n)
        r, _ = stats.spearmanr(x[idx], y[idx])
        rhos.append(r)
        
    alpha = (1.0 - ci) / 2.0
    lower = np.percentile(rhos, alpha * 100)
    upper = np.percentile(rhos, (1.0 - alpha) * 100)
    return rho_point, (lower, upper)

def partial_spearman(x, y, covar):
    """
    Compute partial Spearman correlation between x and y controlling for covar.
    Rank-residualize both against covar and correlate the residuals.
    """
    mask = ~np.isnan(x) & ~np.isnan(y) & ~np.isnan(covar)
    x, y, c = x[mask], y[mask], covar[mask]
    if len(x) < 5:
        return np.nan
        
    rx, ry, rc = stats.rankdata(x), stats.rankdata(y), stats.rankdata(c)
    
    res_x = rx - (np.polyfit(rc, rx, 1)[0] * rc + np.polyfit(rc, rx, 1)[1])
    res_y = ry - (np.polyfit(rc, ry, 1)[0] * rc + np.polyfit(rc, ry, 1)[1])
    
    rho, _ = stats.pearsonr(res_x, res_y)
    return rho

def run_validation():
    snapshot_path = Path("outputs/snapshots/latest_snapshot.csv")
    if not snapshot_path.exists():
        print(f"Error: Snapshot not found at {snapshot_path}")
        return
        
    df = pd.read_csv(snapshot_path)
    print(f"Loaded snapshot with {len(df)} planets.")
    
    # Run independent XUV physical model
    model_df = run_model(df)
    
    # Merge and calculate heuristic scores
    df = df.merge(model_df[['planet_id', 'retention_prob']], on='planet_id')
    df['flare_score'] = df['teff'].apply(score_flare)
    df['spectral_class'] = df['teff'].apply(spectral_class)
    
    # Remove NaNs from scores
    df = df.dropna(subset=['flare_score', 'retention_prob', 'teff'])
    
    n_total = len(df)
    
    # 1. Primary Test: Raw Spearman (flare_score vs retention)
    rho_flare, (ci_low, ci_high) = bootstrap_spearman(df['flare_score'].values, df['retention_prob'].values)
    
    # 2. Baseline Test: Raw Spearman (Teff vs retention)
    rho_teff, (teff_low, teff_high) = bootstrap_spearman(df['teff'].values, df['retention_prob'].values)
    
    # 3. Decoupling Check: Are Teq and Teff coupled in the HZ sample?
    rho_teq_teff, (teq_teff_low, teq_teff_high) = bootstrap_spearman(df['teq_k'].values, df['teff'].values)
    
    # Check G-dwarf leverage
    df_no_g = df[df['spectral_class'] != 'G']
    rho_no_g, _ = bootstrap_spearman(df_no_g['flare_score'].values, df_no_g['retention_prob'].values)
    
    print("\n" + "="*50)
    print("ENVIRONMENTAL RISK TRACK CROSS-VALIDATION")
    print("="*50)
    print(f"Sample: N={n_total} Rocky HZ Planets (M-dominated Study - G regime unconstrained)")
    
    counts = df['spectral_class'].value_counts()
    for cls in ['G', 'K', 'M']:
        c = counts.get(cls, 0)
        print(f"  {cls} dwarfs: {c}")
        
    print("\n--- Correlation Results ---")
    print(f"Heuristic flare_score vs Physical retention:")
    print(f"  Spearman rho = {rho_flare:.3f} (95% CI: [{ci_low:.3f}, {ci_high:.3f}])")
    
    print(f"\nBaseline Teff vs Physical retention (Shared Axis Check):")
    print(f"  Spearman rho = {rho_teff:.3f} (95% CI: [{teff_low:.3f}, {teff_high:.3f}])")
    
    print(f"\nJackknife G-dwarfs excluded (flare vs retention):")
    print(f"  Spearman rho = {rho_no_g:.3f}")
    
    print(f"\nDecoupling Check:")
    print(f"  Raw rho(Teq, Teff) = {rho_teq_teff:.3f} (95% CI: [{teq_teff_low:.3f}, {teq_teff_high:.3f}])")
    
    passed = rho_flare >= 0.70
    print(f"\nVerdict: {'PASS' if passed else 'FAIL - fails to demonstrate'} (Threshold: rho >= 0.70)")
    print("="*50)
    
    # Generate scatter plot
    plt.figure(figsize=(8, 6))
    
    colors = {'G': '#FDB813', 'K': '#F27127', 'M': '#C1272D'}
    for cls in ['M', 'K', 'G']:
        mask = df['spectral_class'] == cls
        plt.scatter(df[mask]['flare_score'], df[mask]['retention_prob'], 
                    c=colors[cls], label=f'{cls}-type (N={mask.sum()})', 
                    alpha=0.7, edgecolors='k')
                    
    plt.xlabel('Heuristic Flare Safety Score (Higher is safer)')
    plt.ylabel('Modeled Retention Probability (Higher is better)')
    plt.title('Cross-Validation of Flare Heuristic vs Physical Escape Model')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plot_path = Path("outputs/risk_validation_plot.png")
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"\nPlot saved to {plot_path}")
    
    # Save statistics for writeup
    stats_out = {
        "N": n_total,
        "N_G": int(counts.get('G', 0)),
        "N_K": int(counts.get('K', 0)),
        "N_M": int(counts.get('M', 0)),
        "rho_flare": float(rho_flare),
        "rho_flare_ci": [float(ci_low), float(ci_high)],
        "rho_teff": float(rho_teff),
        "rho_no_g": float(rho_no_g),
        "rho_teq_teff": float(rho_teq_teff),
        "rho_teq_teff_ci": [float(teq_teff_low), float(teq_teff_high)],
        "passed": bool(passed)
    }
    with open("outputs/risk_validation_stats.json", "w") as f:
        json.dump(stats_out, f, indent=2)

if __name__ == "__main__":
    run_validation()
