import pandas as pd
import numpy as np
import statsmodels.api as sm
from sqlalchemy import create_engine
import dotenv
import os
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

def main():
    dotenv.load_dotenv('.env')
    db_url = os.environ.get('DATABASE_URL')
    if db_url and db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    
    engine = create_engine(db_url)
    
    # 1. Load the JWST target list
    jwst_df = pd.read_csv('jwst_targets.csv')
    jwst_targets = set(jwst_df['pl_name'].str.strip())
    
    # 2. Query the DB for the indices for all confirmed planets
    query = """
    SELECT 
        p.planet_name,
        p.discovery_year,
        mvs.physical_triage_index,
        mvs.observability_index
    FROM planets p
    LEFT JOIN mv_discovery_scores mvs ON mvs.planet_id = p.planet_id
    WHERE p.status = 'confirmed' AND mvs.physical_triage_index IS NOT NULL AND mvs.observability_index IS NOT NULL
    """
    
    df = pd.read_sql(query, engine)
    
    # Filter to discovery year <= 2023 
    df = df[df['discovery_year'] <= 2023].copy()
    
    # 3. Create boolean target
    df['is_jwst_target'] = df['planet_name'].isin(jwst_targets).astype(int)
    
    n_total = len(df)
    n_jwst = df['is_jwst_target'].sum()
    
    print("="*60)
    print("JWST CYCLE 1-3 ALLOCATION VALIDATION")
    print("="*60)
    print(f"Total Pre-2024 Planets: {n_total}")
    print(f"JWST Cycle 1-3 Targets: {n_jwst}")
    
    df['triage_z'] = (df['physical_triage_index'] - df['physical_triage_index'].mean()) / df['physical_triage_index'].std()
    df['obs_z'] = (df['observability_index'] - df['observability_index'].mean()) / df['observability_index'].std()
    
    X = sm.add_constant(df[['triage_z', 'obs_z']])
    y = df['is_jwst_target']
    
    res = sm.Logit(y, X).fit(disp=0)
    print("\n--- Full Catalog ---")
    print(res.summary())
    
    print("\nAdjusted Odds Ratios (per 1 Std Dev increase):")
    print(f"  Physical Triage (z): OR = {np.exp(res.params['triage_z']):.2f} (p = {res.pvalues['triage_z']:.2e})")
    print(f"  Observability (z):   OR = {np.exp(res.params['obs_z']):.2f} (p = {res.pvalues['obs_z']:.2e})")
    
    # Drop famous multi-planet systems
    famous = ['TRAPPIST-1', 'TOI-270', 'K2-18', 'Kepler-11', 'Kepler-90', 'LHS 1140', 'WASP-39']
    mask = df['planet_name'].str.contains('|'.join(famous), case=False, na=False)
    df_no = df[~mask].copy()
    X_no = sm.add_constant(df_no[['triage_z', 'obs_z']])
    y_no = df_no['is_jwst_target']
    res_no = sm.Logit(y_no, X_no).fit(disp=0)
    
    print("\n--- Excluding Famous Multi-Planet Outliers ---")
    print(res_no.summary())
    
    print("\nAdjusted Odds Ratios (per 1 Std Dev increase):")
    print(f"  Physical Triage (z): OR = {np.exp(res_no.params['triage_z']):.2f} (p = {res_no.pvalues['triage_z']:.2e})")
    print(f"  Observability (z):   OR = {np.exp(res_no.params['obs_z']):.2f} (p = {res_no.pvalues['obs_z']:.2e})")

    # Quintile plot
    df_sorted = df.sort_values(by='physical_triage_index', ascending=False).reset_index(drop=True)
    df_sorted['quintile'] = pd.qcut(df_sorted.index, q=5, labels=['Q1 (Top 20%)', 'Q2', 'Q3', 'Q4', 'Q5 (Bottom 20%)'])
    
    q_stats = df_sorted.groupby('quintile', observed=True).agg(
        total_planets=('planet_name', 'count'),
        jwst_targets=('is_jwst_target', 'sum')
    ).reset_index()
    
    plt.figure(figsize=(10, 6))
    ax = sns.barplot(x='quintile', y='jwst_targets', data=q_stats, hue='quintile', palette='viridis', legend=False)
    plt.title('JWST Cycle 1-3 Allocations across Physical Triage Quintiles\n(Ground Truth vs. New Decision Layer)', fontsize=14, pad=15)
    plt.xlabel('Physical Triage Rank', fontsize=12)
    plt.ylabel('Number of JWST Targets Allocated', fontsize=12)
    
    for i, p in enumerate(ax.patches):
        pct = (q_stats['jwst_targets'].iloc[i] / n_jwst) * 100
        ax.annotate(f"{q_stats['jwst_targets'].iloc[i]}\n({pct:.1f}%)", 
                    (p.get_x() + p.get_width() / 2., p.get_height()), 
                    ha='center', va='bottom', fontsize=11, xytext=(0, 5), 
                    textcoords='offset points')
                    
    plt.ylim(0, q_stats['jwst_targets'].max() * 1.2)
    plt.tight_layout()
    plot_path = Path("outputs/jwst_cycle_1_3_allocation.png")
    plot_path.parent.mkdir(exist_ok=True, parents=True)
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved to {plot_path}")

if __name__ == '__main__':
    main()
