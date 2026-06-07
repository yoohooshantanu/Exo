"""FastAPI gateway for the Exoplanet Discovery Platform."""
import math
import os
from typing import List, Optional

from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.db import get_db
from api import queries as q
from api.models import (
    PlanetListItem, PlanetProfileVector, ProfileHabitability, ProfileBiosignatures, ProfileConfidence, ProfileAnomalyRisk, StarItem,
    SpectrumView, SpectrumPoint, MoleculeDetectionItem, HitranLineItem,
    RankingItem, AlertItem, PlatformStats, PaginatedResponse,
    StarPositionItem, StarPositionsResponse, PriorityTarget,
    SystemPlanet, StarSystemResponse, AtmosphericRetrievalItem
)

app = FastAPI(
    title="Exoplanet Discovery Platform API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://exo-gudeg8rer-piroshadows-projects.vercel.app"
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCORE_VERSION = "4.2.0"
PRED_VERSION = "3.1.0"


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Platform Stats ───────────────────────────────────────────────────────────

@app.get("/api/stats", response_model=PlatformStats)
async def get_stats(session: AsyncSession = Depends(get_db)):
    row = (await session.execute(
        q.PLATFORM_STATS,
        {"score_version": SCORE_VERSION, "pred_version": PRED_VERSION}
    )).mappings().one()
    return PlatformStats(**row)


# ── Planets Catalog ──────────────────────────────────────────────────────────

@app.get("/api/planets", response_model=PaginatedResponse)
async def list_planets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    method: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    min_score: Optional[float] = None,
    session: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size

    count_row = (await session.execute(
        q.PLANET_LIST_COUNT,
        {
            "score_version": SCORE_VERSION,
            "method": method,
            "year_min": year_min,
            "year_max": year_max,
            "min_score": min_score,
        }
    )).scalar()

    rows = (await session.execute(
        q.PLANET_LIST,
        {
            "score_version": SCORE_VERSION,
            "method": method,
            "year_min": year_min,
            "year_max": year_max,
            "min_score": min_score,
            "limit": page_size,
            "offset": offset,
        }
    )).mappings().all()

    items = [PlanetListItem(**dict(r)) for r in rows]
    total = count_row or 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@app.get("/api/planets/{planet_name}", response_model=PlanetProfileVector)
async def get_planet(planet_name: str, session: AsyncSession = Depends(get_db)):
    # Main detail
    row = (await session.execute(
        q.PLANET_DETAIL,
        {"planet_name": planet_name, "score_version": SCORE_VERSION}
    )).mappings().one_or_none()

    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Planet not found")

    d = dict(row)

    # Run sub-queries concurrently to solve the N+1 latency bottleneck
    import asyncio
    from .db import AsyncSessionLocal

    async def fetch_all(query, params):
        async with AsyncSessionLocal() as s:
            return (await s.execute(query, params)).mappings().all()

    a_rows, b_rows, specs, sys_planets_rows, sys_gaps_rows = await asyncio.gather(
        fetch_all(q.PLANET_ANOMALIES, {"planet_name": planet_name}),
        fetch_all(q.PLANET_BIOSIGS, {"planet_name": planet_name}),
        fetch_all(q.SPECTRA_FOR_PLANET, {"planet_name": planet_name}),
        fetch_all(q.SYSTEM_PLANETS, {"planet_name": planet_name}),
        fetch_all(q.PLANET_GAPS, {"planet_name": planet_name, "pred_version": "3.1.0"})
    )

    # Anomalies
    anomaly_count = len(a_rows)
    anomaly_types = [r["anomaly_type"] for r in a_rows]

    # Biosigs
    biosig_count = len(b_rows)
    molecules = [r["molecule"] for r in b_rows]
    max_sigma = max([r["detection_sigma"] for r in b_rows]) if b_rows else None

    # Confidence calculation
    core_params = [d.get("radius_earth"), d.get("mass_earth"), d.get("period_days"), d.get("eq_temperature_k"), d.get("density_earth")]
    known_params = sum(1 for p in core_params if p is not None)
    data_completeness = (known_params / 5.0) * 100.0

    has_spectra = len(specs) > 0
    
    inst_best = None
    if has_spectra:
        for s in specs:
            inst = str(s.get("instrument") or "").lower()
            fac = str(s.get("facility") or "").lower()
            if "jwst" in fac or "jwst" in inst:
                inst_best = "JWST"
                break
        if not inst_best:
            inst_best = specs[0].get("facility")

    # Fetch System Architecture
    from .models import SystemPlanetItem, OrbitalGapItem
    system_planets = [SystemPlanetItem(**dict(r)) for r in sys_planets_rows]
    orbital_gaps = [OrbitalGapItem(**dict(r)) for r in sys_gaps_rows]

    habitability = ProfileHabitability(
        composite_score=d.get("composite_score"),
        similarity_score=d.get("similarity_score"),
        hz_score=d.get("hz_score"),
        teq_score=d.get("teq_score"),
        radius_esi_score=d.get("radius_esi_score"),
        mass_esi_score=d.get("mass_esi_score")
    )
    
    biosignatures = ProfileBiosignatures(
        biosig_count=biosig_count,
        molecules=molecules,
        max_sigma=max_sigma
    )
    
    confidence = ProfileConfidence(
        has_spectra=has_spectra,
        data_completeness=data_completeness,
        instrument_best=inst_best
    )
    
    anomaly_risk = ProfileAnomalyRisk(
        anomaly_count=anomaly_count,
        anomaly_types=anomaly_types,
        risk_score=d.get("risk_score"),
        flare_score=d.get("flare_score"),
        tidal_lock_score=d.get("tidal_lock_score")
    )

    # ── Compute Unified Discovery Score Breakdown (matching SQL) ─────────
    from .models import ScoreBreakdown

    # 1. Habitability component (SQL: COALESCE(hs.composite_score, 0) * 40)
    hab_raw = d.get("composite_score") or 0.0
    hab_component = round(hab_raw * 40, 2)

    # 2. Biosignature component (SQL: LEAST(count_sigma_gt_3 * 5.0, 25))
    confirmed_mols = sum(1 for r in b_rows if r.get("detection_sigma", 0) >= 3.0)
    biosig_component = min(confirmed_mols * 5.0, 25.0)

    # 3. Data quality component (SQL: spectra existence + parameter count)
    # Note: planet_parameters count is fetched as data_completeness count in SQL.
    spectra_pts = 7.0 if has_spectra else 0.0
    # SQL uses all populated planet_parameters. We approximate it with known_params in the Python layer for the breakdown.
    data_component = spectra_pts + (known_params * 1.0)

    # 4. Orbital context component (SQL: sibling count * 1.5)
    n_siblings = len(sys_planets_rows)
    orbital_component = min(n_siblings * 1.5, 10.0)

    # 5. Anomaly penalty (SQL: min(anomaly_count * 3.0, 10))
    anomaly_penalty = -min(anomaly_count * 3.0, 10.0)

    # Use the EXACT score computed by the DB for consistency
    discovery_score = float(d.get("discovery_score") or 0.0)

    score_breakdown = ScoreBreakdown(
        habitability=hab_component,
        biosignature=biosig_component,
        data_quality=data_component,
        orbital_context=orbital_component,
        anomaly_penalty=anomaly_penalty
    )

    return PlanetProfileVector(
        planet_name=d["planet_name"],
        planet_id=d["planet_id"],
        hostname=d.get("hostname"),
        star_id=d.get("star_id"),
        status=d["status"],
        discovery_method=d.get("discovery_method"),
        discovery_year=d.get("discovery_year"),
        radius_earth=d.get("radius_earth"),
        mass_earth=d.get("mass_earth"),
        period_days=d.get("period_days"),
        eq_temperature_k=d.get("eq_temperature_k"),
        semi_major_axis_au=d.get("semi_major_axis_au"),
        eccentricity=d.get("eccentricity"),
        density_earth=d.get("density_earth"),
        cluster_label=d.get("cluster_label"),
        cluster_name=d.get("cluster_name"),
        distance_to_centroid=d.get("distance_to_centroid"),
        discovery_score=discovery_score,
        score_breakdown=score_breakdown,
        habitability=habitability,
        biosignatures=biosignatures,
        confidence=confidence,
        anomaly_risk=anomaly_risk,
        system_planets=system_planets,
        orbital_gaps=orbital_gaps
    )


# ── Spectrum ─────────────────────────────────────────────────────────────────

@app.get("/api/planets/{planet_name}/spectrum", response_model=SpectrumView)
async def get_spectrum(planet_name: str, session: AsyncSession = Depends(get_db)):
    specs = (await session.execute(
        q.SPECTRA_FOR_PLANET, {"planet_name": planet_name}
    )).mappings().all()

    if not specs:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No spectra found")

    spec = specs[0]
    spec_id = spec["spec_id"]

    points = (await session.execute(
        q.SPECTRUM_POINTS, {"spec_id": spec_id}
    )).mappings().all()

    detections = (await session.execute(
        q.SPECTRUM_DETECTIONS, {"planet_name": planet_name}
    )).mappings().all()

    hitran = (await session.execute(
        q.HITRAN_LINES_FOR_PLANET, {"planet_name": planet_name}
    )).mappings().all()

    return SpectrumView(
        spec_id=spec_id,
        instrument=spec.get("instrument"),
        facility=spec.get("facility"),
        obs_type=spec.get("obs_type"),
        points=[SpectrumPoint(**dict(r)) for r in points],
        detections=[MoleculeDetectionItem(**dict(r)) for r in detections],
        hitran_lines=[HitranLineItem(**dict(r)) for r in hitran],
    )


# ── Stars (3D Map) ───────────────────────────────────────────────────────────

@app.get("/api/stars", response_model=PaginatedResponse)
async def list_stars(
    page: int = Query(1, ge=1),
    page_size: int = Query(2000, ge=1, le=10000),
    session: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size

    count = (await session.execute(q.STAR_LIST_COUNT)).scalar()
    rows = (await session.execute(
        q.STAR_LIST, {"limit": page_size, "offset": offset}
    )).mappings().all()

    items = [StarItem(**dict(r)) for r in rows]
    total = count or 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


# ── Star Positions (3D Map) ──────────────────────────────────────────────────

@app.get("/api/stars/positions", response_model=StarPositionsResponse)
async def get_star_positions(
    limit: int = Query(6224, ge=1, le=10000),
    session: AsyncSession = Depends(get_db),
):
    rows = (await session.execute(
        q.STAR_POSITIONS,
        {"score_version": SCORE_VERSION, "limit": limit}
    )).mappings().all()

    stars = []
    for r in rows:
        dist = r["distance_pc"]
        if dist is None:
            continue
        dist = min(dist, 2000.0)
        ra_rad = math.radians(r["ra"])
        dec_rad = math.radians(r["dec"])
        x = dist * math.cos(dec_rad) * math.cos(ra_rad)
        y = dist * math.cos(dec_rad) * math.sin(ra_rad)
        z = dist * math.sin(dec_rad)
        stars.append(StarPositionItem(
            id=r["id"],
            hip_name=r["hip_name"] or "",
            x=round(x, 2),
            y=round(y, 2),
            z=round(z, 2),
            teff=r["teff"],
            radius_solar=r.get("radius_solar"),
            distance_pc=round(dist, 2),
            spectral_type=r.get("spectral_type"),
            n_planets=r["n_planets"],
            hab_score_max=round(float(r["hab_score_max"] or 0), 4),
            has_prediction=r["has_prediction"],
            has_biosig=r["has_biosig"],
        ))

    return StarPositionsResponse(stars=stars)


# ── Star System Detail (Zoom View) ───────────────────────────────────────────

@app.get("/api/stars/{star_id}/system", response_model=StarSystemResponse)
async def get_star_system(star_id: str, session: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    row = (await session.execute(
        q.STAR_SYSTEM,
        {"star_id": star_id}
    )).mappings().one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Star not found")

    planets_rows = (await session.execute(
        q.STAR_SYSTEM_PLANETS,
        {"star_id": star_id, "score_version": SCORE_VERSION}
    )).mappings().all()

    planets = [SystemPlanet(**dict(r)) for r in planets_rows]

    return StarSystemResponse(
        star_id=row["star_id"],
        hip_name=row["hip_name"],
        ra=row["ra"],
        dec=row["dec"],
        distance_pc=row["distance_pc"],
        teff=row["teff"],
        radius_solar=row["radius_solar"],
        mass_solar=row["mass_solar"],
        planets=planets,
    )


# ── Priority Target (Dashboard Hero) ─────────────────────────────────────────

@app.get("/api/priority-target", response_model=PriorityTarget)
async def get_priority_target(session: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    row = (await session.execute(
        q.PRIORITY_TARGET,
        {"score_version": SCORE_VERSION}
    )).mappings().one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="No scored planets found")

    d = dict(row)

    # Construct scientific rationale
    parts = []
    if d.get("cluster_name"):
        parts.append(d["cluster_name"])
    if d.get("hz_score") and d["hz_score"] > 0.8:
        parts.append("within habitable zone")
    if d.get("eq_temperature_k"):
        parts.append(f"T_eq {d['eq_temperature_k']:.0f} K")
    if d.get("molecules_detected"):
        parts.append(f"atmospheric {d['molecules_detected'].upper()} detected")
    if d.get("anomaly_count", 0) > 0:
        parts.append(f"{d['anomaly_count']} anomaly flag(s)")

    d["rationale"] = " · ".join(parts) if parts else "Highest composite habitability score"

    return PriorityTarget(**d)


# ── Rankings ─────────────────────────────────────────────────────────────────

@app.get("/api/rankings", response_model=List[RankingItem])
async def get_rankings(
    category: str = Query("habitable", pattern="^(habitable|anomalous|biosignatures|novel|gaps)$"),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    if category == "habitable":
        query = q.RANKINGS_TOP_HABITABLE
    elif category == "anomalous":
        query = q.RANKINGS_ANOMALOUS
    elif category == "biosignatures":
        query = q.RANKINGS_BIOSIGNATURES
    elif category == "novel":
        query = q.RANKINGS_NOVEL
    else:
        query = q.RANKINGS_GAPS

    rows = (await session.execute(
        query,
        {"score_version": SCORE_VERSION, "pred_version": PRED_VERSION, "limit": limit}
    )).mappings().all()

    return [RankingItem(**dict(r)) for r in rows]


# ── Alerts ───────────────────────────────────────────────────────────────────

@app.get("/api/alerts", response_model=List[AlertItem])
async def get_alerts(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    rows = (await session.execute(
        q.ALERTS,
        {"score_version": SCORE_VERSION, "pred_version": PRED_VERSION, "limit": limit}
    )).mappings().all()

    return [AlertItem(**dict(r)) for r in rows]

# ── Atmospheric Retrievals ───────────────────────────────────────────────────

from fastapi import BackgroundTasks
from modules.platon_retrieval import new_id
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipe.celery_worker import run_platon_retrieval_task

@app.post("/api/planets/{planet_name}/spectra/{spec_id}/retrieve", response_model=AtmosphericRetrievalItem)
async def start_retrieval(
    planet_name: str,
    spec_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    # Find planet_id
    planet = (await session.execute(
        text("SELECT planet_id FROM planets WHERE planet_name = :pname"),
        {"pname": planet_name}
    )).fetchone()
    
    if not planet:
        raise HTTPException(status_code=404, detail="Planet not found")
        
    planet_id = planet[0]
    retrieval_id = new_id()
    
    # Create record
    await session.execute(text("""
        INSERT INTO atmospheric_retrievals (retrieval_id, planet_id, spec_id, model_name, status)
        VALUES (:rid, :pid, :sid, 'PLATON_dynesty', 'running')
    """), {"rid": retrieval_id, "pid": planet_id, "sid": spec_id})
    await session.commit()
    
    run_platon_retrieval_task.delay(str(planet_id), str(spec_id), str(retrieval_id))
    
    return AtmosphericRetrievalItem(
        retrieval_id=retrieval_id,
        spec_id=spec_id,
        model_name='PLATON_dynesty',
        status='running'
    )

@app.get("/api/planets/{planet_name}/spectra/{spec_id}/retrievals", response_model=List[AtmosphericRetrievalItem])
async def get_retrievals(
    planet_name: str,
    spec_id: str,
    session: AsyncSession = Depends(get_db),
):
    rows = (await session.execute(text("""
        SELECT r.*
        FROM atmospheric_retrievals r
        JOIN planets p ON r.planet_id = p.planet_id
        WHERE p.planet_name = :pname AND r.spec_id = :sid
        ORDER BY r.created_at DESC
    """), {"pname": planet_name, "sid": spec_id})).mappings().all()
    
    return [AtmosphericRetrievalItem(**{**dict(r), "retrieval_id": str(r["retrieval_id"]), "spec_id": str(r["spec_id"])}) for r in rows]

@app.get("/api/retrievals/{retrieval_id}/posterior")
async def get_retrieval_posterior(
    retrieval_id: str,
    session: AsyncSession = Depends(get_db),
):
    row = (await session.execute(text("""
        SELECT posterior_file FROM atmospheric_retrievals
        WHERE retrieval_id = :rid
    """), {"rid": retrieval_id})).fetchone()
    
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Posterior file not found")
        
    import json
    try:
        with open(row[0], 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Validation Metrics ──────────────────────────────────────────────────────

@app.get("/api/validation/metrics")
async def get_validation_metrics(session: AsyncSession = Depends(get_db)):
    """Aggregate real statistics from all scientific modules for the Validation dashboard."""

    # --- Biosignature Detection ---
    mol_rows = (await session.execute(text("""
        SELECT molecule, COUNT(*)::int as total,
               ROUND(AVG(detection_sigma)::numeric, 2) as avg_sigma,
               SUM(CASE WHEN detection_sigma >= 3 THEN 1 ELSE 0 END)::int as confirmed,
               SUM(CASE WHEN detection_sigma >= 2 AND detection_sigma < 3 THEN 1 ELSE 0 END)::int as marginal
        FROM molecule_detections GROUP BY molecule ORDER BY total DESC
    """))).fetchall()

    biosig_by_molecule = [
        {"molecule": r[0], "total": r[1], "avg_sigma": float(r[2]) if r[2] else 0, 
         "confirmed": r[3], "marginal": r[4]}
        for r in mol_rows
    ]
    total_detections = sum(m["total"] for m in biosig_by_molecule)
    total_confirmed = sum(m["confirmed"] for m in biosig_by_molecule)

    # --- Orbital Gap Predictions ---
    orb_stats = (await session.execute(text("""
        SELECT COUNT(*)::int, 
               ROUND(AVG(stability_confidence)::numeric, 4),
               AVG(n_body_runs)::int,
               SUM(CASE WHEN stability_confidence >= 0.9 THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN stability_confidence >= 0.8 AND stability_confidence < 0.9 THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN stability_confidence < 0.8 THEN 1 ELSE 0 END)::int
        FROM orbital_predictions
    """))).fetchone()

    orb_resonance = (await session.execute(text("""
        SELECT detection_method_hint, COUNT(*)::int
        FROM orbital_predictions GROUP BY detection_method_hint ORDER BY COUNT(*) DESC
    """))).fetchall()

    orbital = {
        "total_predictions": orb_stats[0] if orb_stats else 0,
        "avg_confidence": float(orb_stats[1]) if orb_stats and orb_stats[1] else 0,
        "avg_nbody_runs": orb_stats[2] if orb_stats else 0,
        "high_confidence": orb_stats[3] if orb_stats else 0,
        "mid_confidence": orb_stats[4] if orb_stats else 0,
        "low_confidence": orb_stats[5] if orb_stats else 0,
        "by_resonance": [{"resonance": r[0], "count": r[1]} for r in orb_resonance]
    }

    # --- Habitability Scoring ---
    hab_stats = (await session.execute(text("""
        SELECT COUNT(*)::int,
               ROUND(AVG(composite_score)::numeric, 4),
               ROUND(MIN(composite_score)::numeric, 4),
               ROUND(MAX(composite_score)::numeric, 4),
               SUM(CASE WHEN composite_score >= 0.7 THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN composite_score >= 0.4 AND composite_score < 0.7 THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN composite_score < 0.4 THEN 1 ELSE 0 END)::int
        FROM habitability_scores
    """))).fetchone()

    hab_histogram = (await session.execute(text("""
        SELECT 
            FLOOR(composite_score * 10)::int as bin,
            COUNT(*)::int
        FROM habitability_scores
        WHERE composite_score IS NOT NULL
        GROUP BY bin ORDER BY bin
    """))).fetchall()

    habitability = {
        "total_scored": hab_stats[0] if hab_stats else 0,
        "avg_score": float(hab_stats[1]) if hab_stats and hab_stats[1] else 0,
        "min_score": float(hab_stats[2]) if hab_stats and hab_stats[2] else 0,
        "max_score": float(hab_stats[3]) if hab_stats and hab_stats[3] else 0,
        "tier1_count": hab_stats[4] if hab_stats else 0,
        "tier2_count": hab_stats[5] if hab_stats else 0,
        "tier3_count": hab_stats[6] if hab_stats else 0,
        "histogram": [{"bin": f"{r[0]*10}-{r[0]*10+10}%", "count": r[1]} for r in hab_histogram if r[0] is not None]
    }

    # --- Anomaly Detection ---
    anom_rows = (await session.execute(text("""
        SELECT anomaly_type, COUNT(*)::int, ROUND(AVG(deviation_sigma)::numeric, 2)
        FROM anomaly_flags GROUP BY anomaly_type ORDER BY COUNT(*) DESC
    """))).fetchall()

    anomalies = {
        "total_flags": sum(r[1] for r in anom_rows),
        "by_type": [{"type": r[0], "count": r[1], "avg_sigma": float(r[2]) if r[2] else 0} for r in anom_rows]
    }

    # --- PLATON Retrievals ---
    ret_stats = (await session.execute(text("""
        SELECT COUNT(*)::int,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN status='running' THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)::int
        FROM atmospheric_retrievals
    """))).fetchone()

    retrievals = {
        "total": ret_stats[0] if ret_stats else 0,
        "completed": ret_stats[1] if ret_stats else 0,
        "running": ret_stats[2] if ret_stats else 0,
        "failed": ret_stats[3] if ret_stats else 0,
    }

    return {
        "biosignatures": {
            "total_detections": total_detections,
            "total_confirmed": total_confirmed,
            "by_molecule": biosig_by_molecule,
        },
        "orbital": orbital,
        "habitability": habitability,
        "anomalies": anomalies,
        "retrievals": retrievals,
    }
