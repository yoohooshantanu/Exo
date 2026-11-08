import os
import sys
import json
from datetime import datetime
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
import dotenv

def main():
    dotenv.load_dotenv('.env')
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("Error: DATABASE_URL not found in .env")
        sys.exit(1)
        
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
    engine = create_engine(db_url)
    
    query = text('''
        SELECT 
            p.planet_id,
            p.planet_name,
            s.star_id,
            s.spectral_type,
            (SELECT value FROM star_parameters sp WHERE sp.star_id = s.star_id AND sp.param_name = 'teff_best_k' AND sp.is_default = true LIMIT 1) AS teff,
            (SELECT value FROM star_parameters sp WHERE sp.star_id = s.star_id AND sp.param_name = 'age_gaia_gyr' AND sp.is_default = true LIMIT 1) AS age_gyr,
            (SELECT is_imputed FROM star_parameters sp WHERE sp.star_id = s.star_id AND sp.param_name = 'age_gaia_gyr' AND sp.is_default = true LIMIT 1) AS age_is_imputed,
            (SELECT value FROM planet_parameters pp WHERE pp.planet_id = p.planet_id AND pp.param_name = 'radius_earth' AND pp.is_default = true LIMIT 1) AS radius_earth,
            (SELECT value FROM planet_parameters pp WHERE pp.planet_id = p.planet_id AND pp.param_name = 'mass_earth' AND pp.is_default = true LIMIT 1) AS mass_earth,
            (SELECT value FROM planet_parameters pp WHERE pp.planet_id = p.planet_id AND pp.param_name = 'semi_major_axis_au' AND pp.is_default = true LIMIT 1) AS sma_au,
            (SELECT value FROM planet_parameters pp WHERE pp.planet_id = p.planet_id AND pp.param_name = 'eq_temperature_k' AND pp.is_default = true LIMIT 1) AS teq_k
        FROM planets p
        JOIN stars s ON p.star_id = s.star_id
        WHERE p.status = 'confirmed'
    ''')
    
    print("Executing query to freeze snapshot...")
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
        
    # Filter for Rocky (R < 1.6 or M < 3.0) and G/K/M (Teff < 6000)
    df = df[(df['teff'].notnull()) & (df['teff'] <= 6000)]
    df = df[((df['radius_earth'].notnull()) & (df['radius_earth'] <= 1.6)) | 
            ((df['mass_earth'].notnull()) & (df['mass_earth'] <= 3.0))]
    
    # HZ approx filter just to keep the sample focused on our target 
    df = df[(df['teq_k'].notnull()) & (df['teq_k'] >= 200) & (df['teq_k'] <= 300)]
    
    out_dir = Path("outputs/snapshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = out_dir / f"exo_archive_snapshot_{timestamp}.csv"
    
    df.to_csv(file_path, index=False)
    print(f"Snapshot frozen: {len(df)} rocky G/K/M HZ planets saved to {file_path}")
    
    # Generate metadata JSON
    meta_path = out_dir / f"exo_archive_snapshot_{timestamp}_meta.json"
    meta = {
        "title": "Exoplanet Archive Frozen Snapshot (Rocky G/K/M HZ)",
        "description": "A versioned snapshot for reproducible environmental-risk cross-validation.",
        "created_at": datetime.now().isoformat(),
        "n_records": len(df),
        "columns": list(df.columns)
    }
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
        
    # Also save a 'latest' symlink/copy for easy reading in scripts
    df.to_csv(out_dir / "latest_snapshot.csv", index=False)

if __name__ == "__main__":
    main()
