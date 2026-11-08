import pandas as pd
import numpy as np
import statsmodels.api as sm
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

def main():
    data_path = Path("outputs/snapshots/discovery_outcome_data_decircularized.csv")
    if not data_path.exists():
        print(f"Data file {data_path} not found.")
        return
        
    df = pd.read_csv(data_path)
    
    n_total = len(df)
    n_jwst = df['has_jwst_spectra'].sum()
    
    print("="*50)
    print("DE-CIRCULARIZED DISCOVERY SCORE OUTCOME STUDY")
    print("="*50)
    print(f"Total Pre-2022 Planets with complete data: {n_total}")
    print(f"Total JWST Targets: {n_jwst}")
    
    # Standardize the predictors so coefficients are comparable
    # We standardize observability proxy and a_priori_score (mean 0, std 1)
    df['obs_z'] = (df['observability_proxy'] - df['observability_proxy'].mean()) / df['observability_proxy'].std()
    df['score_z'] = (df['a_priori_score'] - df['a_priori_score'].mean()) / df['a_priori_score'].std()
    
    # Logistic Regression: has_jwst_spectra ~ a_priori_score + observability_proxy
    # We include a constant
    X = df[['score_z', 'obs_z']]
    X = sm.add_constant(X)
    y = df['has_jwst_spectra']
    
    logit_model = sm.Logit(y, X)
    result = logit_model.fit(disp=0)
    
    print("\nLogistic Regression Results:")
    print(result.summary())
    
    # Calculate Odds Ratios
    params = result.params
    conf = result.conf_int()
    conf['OR'] = params
    conf.columns = ['2.5%', '97.5%', 'OR']
    odds_ratios = np.exp(conf)
    pvalues = result.pvalues
    
    print("\nAdjusted Odds Ratios (per 1 Std Dev increase):")
    print(f"  A Priori Score (z): OR = {odds_ratios.loc['score_z', 'OR']:.2f} (95% CI: {odds_ratios.loc['score_z', '2.5%']:.2f}-{odds_ratios.loc['score_z', '97.5%']:.2f}), p = {pvalues['score_z']:.2e}")
    print(f"  Observability (z):  OR = {odds_ratios.loc['obs_z', 'OR']:.2f} (95% CI: {odds_ratios.loc['obs_z', '2.5%']:.2f}-{odds_ratios.loc['obs_z', '97.5%']:.2f}), p = {pvalues['obs_z']:.2e}")
    
    # Collinearity check
    corr = df[['score_z', 'obs_z']].corr().iloc[0, 1]
    print(f"\nCollinearity Check (Pearson r between Score and Observability): {corr:.3f}")
    
    # Leverage check: Drop top multi-planet systems (TRAPPIST-1, TOI-270, K2-18, etc.)
    # We'll just drop anything with "TRAPPIST-1", "TOI-270", "K2-18", "Kepler-11", "Kepler-90"
    famous_systems = ['TRAPPIST-1', 'TOI-270', 'K2-18', 'Kepler-11', 'Kepler-90']
    mask = df['planet_name'].str.contains('|'.join(famous_systems), case=False, na=False)
    df_no_leverage = df[~mask].copy()
    
    # Refit
    X_no = sm.add_constant(df_no_leverage[['score_z', 'obs_z']])
    y_no = df_no_leverage['has_jwst_spectra']
    res_no = sm.Logit(y_no, X_no).fit(disp=0)
    
    print("\nRefit Excluding Top Multi-Planet Systems (TRAPPIST-1, TOI-270, K2-18, etc.):")
    print(f"  A Priori Score (z) OR: {np.exp(res_no.params['score_z']):.2f} (p = {res_no.pvalues['score_z']:.2e})")
    
    # Plotting
    # We still want to show the distribution of targets across quintiles for the visual
    df_sorted = df.sort_values(by='a_priori_score', ascending=False).reset_index(drop=True)
    df_sorted['quintile'] = pd.qcut(df_sorted.index, q=5, labels=['Q1 (Top 20%)', 'Q2', 'Q3', 'Q4', 'Q5 (Bottom 20%)'])
    
    q_stats = df_sorted.groupby('quintile', observed=True).agg(
        total_planets=('planet_id', 'count'),
        jwst_targets=('has_jwst_spectra', 'sum')
    ).reset_index()
    
    print("\nA Priori Score Quintile Breakdown:")
    for _, row in q_stats.iterrows():
        pct = (row['jwst_targets'] / n_jwst) * 100
        print(f"  {row['quintile']}: {row['jwst_targets']} JWST targets ({pct:.1f}% of total targets)")
        
    plt.figure(figsize=(10, 6))
    
    # Bar plot of JWST count per quintile
    ax = sns.barplot(x='quintile', y='jwst_targets', data=q_stats, hue='quintile', palette='viridis', legend=False)
    plt.title('JWST Target Distribution across A Priori Score Quintiles\n(De-Circularized, Pre-2022 Catalog)', fontsize=14, pad=15)
    plt.xlabel('A Priori Score Rank', fontsize=12)
    plt.ylabel('Number of JWST Targets', fontsize=12)
    
    # Add percentage labels on top of bars
    for i, p in enumerate(ax.patches):
        pct = (q_stats['jwst_targets'].iloc[i] / n_jwst) * 100
        ax.annotate(f"{q_stats['jwst_targets'].iloc[i]}\n({pct:.1f}%)", 
                    (p.get_x() + p.get_width() / 2., p.get_height()), 
                    ha='center', va='bottom', fontsize=11, xytext=(0, 5), 
                    textcoords='offset points')
                    
    # Extend y-axis slightly to fit labels
    plt.ylim(0, q_stats['jwst_targets'].max() * 1.2)
    
    plt.tight_layout()
    plot_path = Path("outputs/discovery_quintiles.png")
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"\nPlot saved to {plot_path}")

if __name__ == "__main__":
    main()
