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
    PlanetListItem, PlanetDetail, StarItem,
    SpectrumView, SpectrumPoint, MoleculeDetectionItem, HitranLineItem,
    RankingItem, AlertItem, PlatformStats, PaginatedResponse,
    StarPositionItem, StarPositionsResponse, PriorityTarget,
    SystemPlanet, StarSystemResponse,
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
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
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


@app.get("/api/planets/{planet_name}", response_model=PlanetDetail)
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

    # Anomalies
    a_rows = (await session.execute(
        q.PLANET_ANOMALIES, {"planet_name": planet_name}
    )).mappings().all()
    d["anomaly_count"] = len(a_rows)
    d["anomaly_types"] = [r["anomaly_type"] for r in a_rows]

    # Biosigs
    b_rows = (await session.execute(
        q.PLANET_BIOSIGS, {"planet_name": planet_name}
    )).mappings().all()
    d["biosig_count"] = len(b_rows)
    d["molecules"] = [r["molecule"] for r in b_rows]

    # Gaps
    g_rows = (await session.execute(
        q.PLANET_GAPS, {"planet_name": planet_name, "pred_version": PRED_VERSION}
    )).mappings().all()
    d["gap_count"] = len(g_rows)

    return PlanetDetail(**d)


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
