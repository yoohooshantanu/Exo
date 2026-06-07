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
        
        new_stars = []
        new_planets = []
        planet_params = []
        star_params = []
        
        for row in data:
            hostname = row.get('hostname')
            planet_name = row.get('pl_name')
            
            if not hostname or not planet_name: continue
            
            # 1. Star
            star_id = stars_cache.get(hostname)
            if not star_id:
                star_id = new_id()
                new_stars.append({
                    "sid": star_id, "hn": hostname, 
                    "ra": row.get('ra', 0), "dec": row.get('dec', 0), "dist": row.get('sy_dist')
                })
                stars_cache[hostname] = star_id
            
            # 2. Planet
            planet_id = planets_cache.get(planet_name)
            if not planet_id:
                planet_id = new_id()
                new_planets.append({
                    "pid": planet_id, "sid": star_id, "pn": planet_name,
                    "dm": row.get('discoverymethod'), "dy": row.get('disc_year')
                })
                planets_cache[planet_name] = planet_id
                
            def add_param(lst, id_col, obj_id, param_name, value, unit):
                if value is None or (isinstance(value, float) and math.isnan(value)): return
                lst.append({
                    id_col: obj_id, "rid": run_id, "pname": param_name, 
                    "val": value, "unit": unit
                })
                
            add_param(planet_params, 'planet_id', planet_id, 'radius_earth', row.get('pl_rade'), 'Earth Radii')
            add_param(planet_params, 'planet_id', planet_id, 'mass_earth', row.get('pl_masse'), 'Earth Masses')
            add_param(planet_params, 'planet_id', planet_id, 'period_days', row.get('pl_orbper'), 'Days')
            add_param(planet_params, 'planet_id', planet_id, 'eq_temperature_k', row.get('pl_eqt'), 'K')
            
            add_param(star_params, 'star_id', star_id, 'radius_solar', row.get('st_rad'), 'Solar Radii')
            add_param(star_params, 'star_id', star_id, 'teff_best_k', row.get('st_teff'), 'K')
            
            records_affected += 1

        # Bulk execute
        if new_stars:
            session.execute(text("""
                INSERT INTO stars (star_id, hip_name, ra, dec, distance_pc)
                VALUES (:sid, :hn, :ra, :dec, :dist)
            """), new_stars)
        
        if new_planets:
            session.execute(text("""
                INSERT INTO planets (planet_id, star_id, planet_name, status, discovery_method, discovery_year)
                VALUES (:pid, :sid, :pn, 'confirmed', :dm, :dy)
            """), new_planets)

        if planet_params:
            session.execute(text("""
                UPDATE planet_parameters SET is_default = false 
                WHERE planet_id = :planet_id AND param_name = :pname AND is_default = true
            """), [{"planet_id": p["planet_id"], "pname": p["pname"]} for p in planet_params])
            
            session.execute(text("""
                INSERT INTO planet_parameters (planet_id, run_id, param_name, value, unit, is_default)
                VALUES (:planet_id, :rid, :pname, :val, :unit, true)
            """), planet_params)
            
        if star_params:
            session.execute(text("""
                UPDATE star_parameters SET is_default = false 
                WHERE star_id = :star_id AND param_name = :pname AND is_default = true
            """), [{"star_id": p["star_id"], "pname": p["pname"]} for p in star_params])
            
            session.execute(text("""
                INSERT INTO star_parameters (star_id, run_id, param_name, value, unit, is_default)
                VALUES (:star_id, :rid, :pname, :val, :unit, true)
            """), star_params)
            
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
