import pandas as pd
from sqlalchemy import create_engine
import dotenv
import os
from pathlib import Path
import numpy as np

# Import the actual version string
import sys
sys.path.append(os.path.abspath('.'))
from modules.config import HABITABILITY_MODEL_VERSION

def main():
    dotenv.load_dotenv('.env')
    db_url = os.environ.get('DATABASE_URL')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    engine = create_engine(db_url)
    
    query = f"""
    SELECT 
        p.planet_id,
        p.planet_name,
        ROUND(GREATEST(0, LEAST((
            COALESCE(hs.composite_score, 0) * 40
            + LEAST((
                SELECT COUNT(DISTINCT pp2.param_name)
                FROM planet_parameters pp2
                WHERE pp2.planet_id = p.planet_id
                    AND pp2.is_default = true
                    AND pp2.value IS NOT NULL
                    AND pp2.param_name IN (
                        'radius_earth', 'mass_earth', 'period_days',
                        'eq_temperature_k', 'semi_major_axis_au'
                    )
            ), 5)
            + LEAST(
                (SELECT COUNT(*) FROM planets p2 WHERE p2.star_id = p.star_id AND p2.status = 'confirmed') * 1.5
                + (SELECT COUNT(*) FROM orbital_predictions op WHERE op.star_id = p.star_id) * 2.0
              , 10)
            - LEAST((SELECT COUNT(*) FROM anomaly_flags af WHERE af.planet_id = p.planet_id) * 3.0, 10)
        ), 65))::numeric, 1) AS a_priori_score,
        
        CASE WHEN EXISTS(
            SELECT 1 FROM atmospheric_spectra asp
            WHERE asp.planet_id = p.planet_id 
              AND (LOWER(asp.facility) LIKE '%%jwst%%' OR LOWER(asp.instrument) LIKE '%%jwst%%')
        ) THEN 1 ELSE 0 END as has_jwst_spectra,
        
        s.distance_pc,
        
        (SELECT value FROM planet_parameters pp 
         WHERE pp.planet_id = p.planet_id AND pp.param_name = 'radius_earth' AND pp.is_default = true LIMIT 1) as radius_earth,
         
        (SELECT value FROM star_parameters sp 
         WHERE sp.star_id = s.star_id AND sp.param_name = 'radius_solar' AND sp.is_default = true LIMIT 1) as radius_solar
        
    FROM planets p
    JOIN stars s ON p.star_id = s.star_id
    LEFT JOIN habitability_scores hs 
        ON hs.planet_id = p.planet_id 
        AND hs.model_version = '{HABITABILITY_MODEL_VERSION}'
    WHERE p.status = 'confirmed' AND p.discovery_year <= 2021
    """
    
    df = pd.read_sql(query, engine)
    
    # Process Observability Proxy
    # Drop rows without distance or radius for the logistic regression
    df = df.dropna(subset=['distance_pc', 'radius_earth', 'radius_solar'])
    
    # 1 R_solar = 109.2 R_earth
    df['r_ratio'] = df['radius_earth'] / (df['radius_solar'] * 109.2)
    
    # Prevent divide by zero if distance_pc is 0 (unlikely but possible)
    df['distance_pc'] = df['distance_pc'].replace(0, np.nan)
    df = df.dropna(subset=['distance_pc'])
    
    # TSM Proxy: (Rp/Rs)^2 / d^2
    # We log10 it because SNR spans many orders of magnitude
    df['observability_proxy'] = np.log10( (df['r_ratio']**2) / (df['distance_pc']**2) )
    
    # Drop intermediate columns
    df = df.drop(columns=['r_ratio'])
    
    # Sanity check: Ensure habitability is not zeroed out
    # Note: hs.composite_score is incorporated into a_priori_score, but let's query it explicitly to check
    # Wait, I need to extract composite_score from DB. Let's do a fast query just for this assert.
    comp_check_query = f"SELECT AVG(composite_score) FROM habitability_scores WHERE model_version='{HABITABILITY_MODEL_VERSION}'"
    avg_comp = engine.execute(comp_check_query).scalar() if hasattr(engine, 'execute') else pd.read_sql(comp_check_query, engine).iloc[0,0]
    assert avg_comp is not None and avg_comp > 0, "Habitability composite scores are null or zero!"

    
    out_dir = Path("outputs/snapshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "discovery_outcome_data_decircularized.csv"
    
    df.to_csv(out_path, index=False)
    print(f"Extracted {len(df)} planets discovered <= 2021 with observability data.")
    print(f"Planets with JWST spectra: {df['has_jwst_spectra'].sum()}")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
