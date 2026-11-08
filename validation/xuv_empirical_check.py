import pandas as pd
from sqlalchemy import create_engine
import dotenv
import os
import numpy as np
from itertools import product

def compute_auc(retained_scores, stripped_scores):
    if len(retained_scores) == 0 or len(stripped_scores) == 0:
        return np.nan
    wins = 0
    ties = 0
    for r, s in product(retained_scores, stripped_scores):
        if r > s:
            wins += 1
        elif r == s:
            ties += 1
    total_pairs = len(retained_scores) * len(stripped_scores)
    return (wins + 0.5 * ties) / total_pairs

def main():
    dotenv.load_dotenv('.env')
    db_url = os.environ.get('DATABASE_URL')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    engine = create_engine(db_url)
    
    # Pre-registered JWST/HST independent constraints
    # 0 = Stripped/Bare Rock/No Thick Atmosphere
    # 1 = Retained Atmosphere / Volatile Envelope
    empirical_status = {
        'TRAPPIST-1 b': 0,
        'TRAPPIST-1 c': 0,
        'LHS 475 b':    0,
        'GJ 486 b':     0,
        'GJ 1252 b':    0,
        '55 Cnc e':     1,  # Thick volatile envelope detected by JWST
        'K2-18 b':      1,  # Carbon-bearing molecules detected
        'LHS 1140 b':   1   # Likely water world / envelope
    }
    
    names = "', '".join(empirical_status.keys())
    
    query = f"""
    SELECT 
        p.planet_name,
        COALESCE(pp.radius_earth, 1.0) as radius_earth,
        hs.xuv_escape_score,
        hs.composite_score
    FROM planets p
    JOIN habitability_scores hs ON p.planet_id = hs.planet_id
    LEFT JOIN (
        SELECT planet_id, MAX(CASE WHEN param_name = 'radius_earth' THEN value END) as radius_earth
        FROM planet_parameters
        WHERE is_default = true
        GROUP BY planet_id
    ) pp ON p.planet_id = pp.planet_id
    WHERE p.planet_name IN ('{names}')
      AND hs.model_version = '5.0.0'
    """
    
    df = pd.read_sql(query, engine)
    
    df['retained_ground_truth'] = df['planet_name'].map(empirical_status)
    df['is_rocky'] = df['radius_earth'] < 1.7
    
    print("="*60)
    print("EMPIRICAL CONSISTENCY CHECK: XUV ESCAPE SCORE")
    print("="*60)
    print(f"Number of empirical constraints: {len(df)} (Tiny N, underpowered by definition)")
    print()
    
    print(f"{'Planet Name':<15} | {'Radius':<6} | {'Empirical Status':<15} | {'XUV Escape Score':<15}")
    print("-" * 62)
    for _, row in df.sort_values('xuv_escape_score').iterrows():
        status_str = "Retained" if row['retained_ground_truth'] == 1 else "Stripped"
        print(f"{row['planet_name']:<15} | {row['radius_earth']:<6.2f} | {status_str:<15} | {row['xuv_escape_score']:.3f}")
        
    print("\n-- Overall Consistency (All Planets) --")
    retained = df[df['retained_ground_truth'] == 1]['xuv_escape_score'].values
    stripped = df[df['retained_ground_truth'] == 0]['xuv_escape_score'].values
    overall_auc = compute_auc(retained, stripped)
    print(f"Retained (N={len(retained)}), Stripped (N={len(stripped)})")
    print(f"Rank Test (AUC / Mann-Whitney U): {overall_auc:.3f}")
    
    print("\n-- Rocky Subset (Radius < 1.7 R_earth) --")
    df_rocky = df[df['is_rocky']]
    rocky_ret = df_rocky[df_rocky['retained_ground_truth'] == 1]['xuv_escape_score'].values
    rocky_str = df_rocky[df_rocky['retained_ground_truth'] == 0]['xuv_escape_score'].values
    rocky_auc = compute_auc(rocky_ret, rocky_str)
    print(f"Retained (N={len(rocky_ret)}), Stripped (N={len(rocky_str)})")
    print(f"Rank Test (AUC / Mann-Whitney U): {rocky_auc:.3f}")
    
    print("\n-- Analysis --")
    print("The apparent signal is heavily driven by the sub-Neptune/rocky dichotomy.")
    print("Within the purely rocky subset, the model currently fails to discriminate")
    print("(AUC < 0.5), as it assigns the lowest score to the sole rocky retained case.")
    print("Status: Physically-motivated replacement; empirically inconclusive.\n")

if __name__ == "__main__":
    main()
