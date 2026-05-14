import os, sys, urllib.request, json, uuid
from datetime import datetime, timezone
from pathlib import Path
import math

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def new_id(): return str(uuid.uuid4())

def run_ingestion(limit=None):
    session = SessionLocal()
    print("Starting NASA Exoplanet Archive Ingestion...")
    
    # Create an ingestion run record
    run_id = new_id()
    session.execute(text("""
        INSERT INTO ingestion_runs (run_id, pipeline_version, source, status)
        VALUES (:rid, '3.0.0', 'nasa_exoplanet_archive', 'running')
    """), {"rid": run_id})
    session.commit()
    
    limit_clause = f"top+{limit}+" if limit else ""
    url = f"https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=SELECT+{limit_clause}pl_name,hostname,pl_rade,pl_masse,pl_orbper,pl_eqt,st_rad,st_teff,st_spectype,sy_dist,ra,dec,discoverymethod,disc_year+FROM+pscomppars&format=json"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        print(f"Fetched {len(data)} records from NASA Exoplanet Archive.")
        
        # We need a quick cache of existing stars and planets to avoid constant SELECTs
        stars_cache = {}
        planets_cache = {}
        
        # Load existing stars
        existing_stars = session.execute(text("SELECT hip_name, star_id FROM stars")).fetchall()
        for r in existing_stars:
            stars_cache[r[0]] = str(r[1])
            
        # Load existing planets
        existing_planets = session.execute(text("SELECT planet_name, planet_id FROM planets")).fetchall()
        for r in existing_planets:
            planets_cache[r[0]] = str(r[1])
            
        records_affected = 0
        
        for row in data:
            hostname = row.get('hostname')
            planet_name = row.get('pl_name')
            
            if not hostname or not planet_name: continue
            
            # 1. Star
            star_id = stars_cache.get(hostname)
            if not star_id:
                star_id = new_id()
                session.execute(text("""
                    INSERT INTO stars (star_id, hip_name, ra, dec, distance_pc)
                    VALUES (:sid, :hn, :ra, :dec, :dist)
                """), {
                    "sid": star_id, "hn": hostname, 
                    "ra": row.get('ra', 0), "dec": row.get('dec', 0), "dist": row.get('sy_dist')
                })
                stars_cache[hostname] = star_id
            
            # 2. Planet
            planet_id = planets_cache.get(planet_name)
            if not planet_id:
                planet_id = new_id()
                session.execute(text("""
                    INSERT INTO planets (planet_id, star_id, planet_name, status, discovery_method, discovery_year)
                    VALUES (:pid, :sid, :pn, 'confirmed', :dm, :dy)
                """), {
                    "pid": planet_id, "sid": star_id, "pn": planet_name,
                    "dm": row.get('discoverymethod'), "dy": row.get('disc_year')
                })
                planets_cache[planet_name] = planet_id
                
            # Helper to upsert params
            def upsert_param(table, id_col, obj_id, param_name, value, unit):
                if value is None or (isinstance(value, float) and math.isnan(value)): return
                # We will mark existing as non-default, and insert new as default
                session.execute(text(f"""
                    UPDATE {table} SET is_default = false 
                    WHERE {id_col} = :oid AND param_name = :pname AND is_default = true
                """), {"oid": obj_id, "pname": param_name})
                
                session.execute(text(f"""
                    INSERT INTO {table} ({id_col}, run_id, param_name, value, unit, is_default)
                    VALUES (:oid, :rid, :pname, :val, :unit, true)
                """), {"oid": obj_id, "rid": run_id, "pname": param_name, "val": value, "unit": unit})
                
            upsert_param('planet_parameters', 'planet_id', planet_id, 'radius_earth', row.get('pl_rade'), 'Earth Radii')
            upsert_param('planet_parameters', 'planet_id', planet_id, 'mass_earth', row.get('pl_masse'), 'Earth Masses')
            upsert_param('planet_parameters', 'planet_id', planet_id, 'period_days', row.get('pl_orbper'), 'Days')
            upsert_param('planet_parameters', 'planet_id', planet_id, 'eq_temperature_k', row.get('pl_eqt'), 'K')
            
            upsert_param('star_parameters', 'star_id', star_id, 'radius_solar', row.get('st_rad'), 'Solar Radii')
            upsert_param('star_parameters', 'star_id', star_id, 'teff_best_k', row.get('st_teff'), 'K')
            
            records_affected += 1
            
        session.execute(text("""
            UPDATE ingestion_runs 
            SET status = 'completed', finished_at = :now, records_affected = :ra
            WHERE run_id = :rid
        """), {"now": datetime.now(timezone.utc), "ra": records_affected, "rid": run_id})
        
        session.commit()
        print(f"NASA Ingestion completed successfully. {records_affected} records processed.")
        
    except Exception as e:
        session.rollback()
        print(f"Error during ingestion: {e}")
        session.execute(text("""
            UPDATE ingestion_runs 
            SET status = 'failed', error_detail = :err, finished_at = :now
            WHERE run_id = :rid
        """), {"err": str(e), "now": datetime.now(timezone.utc), "rid": run_id})
        session.commit()
    finally:
        session.close()

if __name__ == "__main__":
    limit = None
    if len(sys.argv) > 1 and sys.argv[1] == '--limit':
        limit = int(sys.argv[2])
    run_ingestion(limit)
