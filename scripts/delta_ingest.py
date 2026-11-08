import sys, os, math, uuid, json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "modules"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from db_sync import create_sync_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

def run_delta_ingestion():
    engine = create_sync_engine()
    Session = sessionmaker(bind=engine)
    session = Session()

    run_id = str(uuid.uuid4())
    session.execute(text("""
        INSERT INTO ingestion_runs (run_id, pipeline_version, source, status)
        VALUES (:rid, '3.0.1', 'nasa_exoplanet_archive_delta', 'running')
    """), {"rid": run_id})
    session.commit()

    url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=SELECT+pl_name,hostname,pl_rade,pl_masse,pl_orbper,pl_eqt,st_rad,st_teff,st_spectype,sy_dist,ra,dec,discoverymethod,disc_year+FROM+pscomppars&format=json"
    req = urllib.request.Request(url)
    print("Downloading catalog from NASA Exoplanet Archive...")
    data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    print(f"Fetched {len(data)} records.")

    existing_stars = {r[0]: str(r[1]) for r in session.execute(text("SELECT hip_name, star_id FROM stars")).fetchall()}
    existing_planets = {r[0]: str(r[1]) for r in session.execute(text("SELECT planet_name, planet_id FROM planets")).fetchall()}

    new_stars = []
    new_planets = []
    new_planet_params = []
    new_star_params = []

    for row in data:
        hn = row.get("hostname")
        pn = row.get("pl_name")
        if not hn or not pn:
            continue
        
        star_id = existing_stars.get(hn)
        if not star_id:
            star_id = str(uuid.uuid4())
            existing_stars[hn] = star_id
            new_stars.append({
                "sid": star_id, "hn": hn, 
                "ra": row.get("ra", 0) or 0, "dec": row.get("dec", 0) or 0, "dist": row.get("sy_dist")
            })
            if row.get("st_rad") is not None and not math.isnan(row.get("st_rad")):
                new_star_params.append({"star_id": star_id, "rid": run_id, "pname": "radius_solar", "val": row.get("st_rad"), "unit": "Solar Radii"})
            if row.get("st_teff") is not None and not math.isnan(row.get("st_teff")):
                new_star_params.append({"star_id": star_id, "rid": run_id, "pname": "teff_best_k", "val": row.get("st_teff"), "unit": "K"})
                
        if pn not in existing_planets:
            planet_id = str(uuid.uuid4())
            existing_planets[pn] = planet_id
            new_planets.append({
                "pid": planet_id, "sid": star_id, "pn": pn,
                "dm": row.get("discoverymethod"), "dy": row.get("disc_year")
            })
            for pkey, col, unit in [
                ("radius_earth", "pl_rade", "Earth Radii"),
                ("mass_earth", "pl_masse", "Earth Masses"),
                ("period_days", "pl_orbper", "Days"),
                ("eq_temperature_k", "pl_eqt", "K")
            ]:
                val = row.get(col)
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    new_planet_params.append({"planet_id": planet_id, "rid": run_id, "pname": pkey, "val": val, "unit": unit})

    print(f"New stars to insert: {len(new_stars)}")
    print(f"New planets to insert: {len(new_planets)}")

    if new_stars:
        session.execute(text("INSERT INTO stars (star_id, hip_name, ra, dec, distance_pc) VALUES (:sid, :hn, :ra, :dec, :dist)"), new_stars)
        session.commit()

    if new_planets:
        session.execute(text("INSERT INTO planets (planet_id, star_id, planet_name, status, discovery_method, discovery_year) VALUES (:pid, :sid, :pn, 'confirmed', :dm, :dy)"), new_planets)
        session.commit()

    if new_star_params:
        session.execute(text("INSERT INTO star_parameters (star_id, run_id, param_name, value, unit, is_default) VALUES (:star_id, :rid, :pname, :val, :unit, true)"), new_star_params)
        session.commit()

    if new_planet_params:
        session.execute(text("INSERT INTO planet_parameters (planet_id, run_id, param_name, value, unit, is_default) VALUES (:planet_id, :rid, :pname, :val, :unit, true)"), new_planet_params)
        session.commit()

    session.execute(text("""
        UPDATE ingestion_runs 
        SET status = 'completed', finished_at = :now, records_affected = :ra
        WHERE run_id = :rid
    """), {"now": datetime.now(timezone.utc), "ra": len(new_planets), "rid": run_id})
    session.commit()
    session.close()
    print("Ingestion successful!")

if __name__ == "__main__":
    run_delta_ingestion()
