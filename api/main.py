from datetime import datetime, timezone
"""FastAPI gateway for the Exoplanet Discovery Platform."""
import asyncio
import json
import math
import os
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import csv
import io
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import queries as q
from api.db import AsyncSessionLocal, get_db
from api.models import (
    AlertItem,
    AtmosphericRetrievalItem,
    HitranLineItem,
    MoleculeDetectionItem,
    OrbitalGapItem,
    PaginatedResponse,
    PlanetListItem,
    PlanetProfileVector,
    PlatformStats,
    PriorityTarget,
    ProfileAnomalyRisk,
    ProfileBiosignatures,
    ProfileConfidence,
    ProfileHabitability,
    RankingItem,
    ScoreBreakdown,
    SpectrumPoint,
    SpectrumView,
    StarItem,
    StarPositionItem,
    StarPositionsResponse,
    StarSystemResponse,
    SystemPlanet,
    SystemPlanetItem,
    DataProvenance,
    ParamProvenance,
)
from modules.config import (
    HABITABILITY_MODEL_VERSION as SCORE_VERSION,
)
from modules.config import (
    ORBITAL_MODEL_VERSION as PRED_VERSION,
    BIOSIG_MODEL_VERSION as BIOSIG_VERSION,
)
from modules.config import (
    PROJECT_ROOT,
    RETRIEVAL_OUTPUT_DIR,
)
from modules.platon_retrieval import new_id
from modules.discovery_score import compute_data_quality_component

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Exoplanet Discovery Platform API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _cors_origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_posterior_path(path: str) -> Path:
    """Only serve posterior files stored under the configured retrieval output dir."""
    if not path:
        raise HTTPException(status_code=404, detail="Posterior file not found")

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    allowed_root = RETRIEVAL_OUTPUT_DIR.resolve()
    try:
        candidate.relative_to(allowed_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid posterior file path")

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Posterior file not found")
    return candidate


def _enqueue_retrieval(planet_id: str, spec_id: str, retrieval_id: str) -> str:
    """Queue a PLATON retrieval via Celery when available, else run inline."""
    try:
        from pipe.celery_worker import app as celery_app
        celery_app.send_task(
            "run_platon_retrieval_task",
            args=[planet_id, spec_id, retrieval_id],
        )
        return "celery"
    except Exception:
        from modules.platon_retrieval import run_platon_retrieval
        run_platon_retrieval(planet_id, spec_id, retrieval_id)
        return "inline"


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Platform Stats ───────────────────────────────────────────────────────────

@app.get("/api/stats", response_model=PlatformStats)
@limiter.limit("60/minute")
async def get_stats(request: Request, session: AsyncSession = Depends(get_db)):
    row = (await session.execute(
        q.PLATFORM_STATS,
        {"score_version": SCORE_VERSION, "pred_version": PRED_VERSION}
    )).mappings().one()
    return PlatformStats(**row)


@app.get("/api/taxonomy-stats")
async def get_taxonomy_stats(session: AsyncSession = Depends(get_db)):
    rows = (await session.execute(text("""
        WITH latest_taxonomy AS (
            SELECT DISTINCT ON (tc.planet_id)
                tc.planet_id,
                tc.cluster_label,
                tc.cluster_name
            FROM taxonomy_clusters tc
            ORDER BY tc.planet_id, tc.run_at DESC, tc.cluster_label DESC
        )
        SELECT 
            CASE 
                WHEN lt.cluster_label = -1 THEN 'Unassigned (HDBSCAN Noise)'
                ELSE COALESCE(lt.cluster_name, 'Unknown')
            END AS cluster_label, 
            COUNT(*)::int AS count
        FROM latest_taxonomy lt
        JOIN planets p ON lt.planet_id = p.planet_id
        WHERE p.status = 'confirmed'
        GROUP BY 
            CASE 
                WHEN lt.cluster_label = -1 THEN 'Unassigned (HDBSCAN Noise)'
                ELSE COALESCE(lt.cluster_name, 'Unknown')
            END
        ORDER BY count DESC
    """))).mappings().all()
    return [dict(r) for r in rows]


# ── Planets Catalog ──────────────────────────────────────────────────────────

@app.get("/api/planets", response_model=PaginatedResponse)
@limiter.limit("60/minute")
async def list_planets(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    method: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    min_score: Optional[float] = None,
    search: Optional[str] = None,
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
            "search": search,
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
            "search": search,
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


@app.get("/api/export/planets")
@limiter.limit("60/minute")
async def export_planets(
    request: Request,
    method: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    min_score: Optional[float] = None,
    search: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
):
    rows = (await session.execute(
        q.CSV_EXPORT,
        {
            "score_version": SCORE_VERSION,
            "method": method,
            "year_min": year_min,
            "year_max": year_max,
            "min_score": min_score,
            "search": search,
        }
    )).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No planets found matching criteria")

    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    headers = list(rows[0].keys())
    writer.writerow(headers)
    
    # Write rows
    for row in rows:
        writer.writerow([row[h] for h in headers])
        
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), 
        media_type="text/csv", 
        headers={"Content-Disposition": "attachment; filename=exo_planets_export.csv"}
    )



@app.get("/api/planets/{planet_name}", response_model=PlanetProfileVector)
@limiter.limit("120/minute")
async def get_planet(request: Request, planet_name: str, session: AsyncSession = Depends(get_db)):
    # Main detail
    row = (await session.execute(
        q.PLANET_DETAIL,
        {"planet_name": planet_name, "score_version": SCORE_VERSION}
    )).mappings().one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Planet not found")

    d = dict(row)

    async def fetch_all(query, params):
        return (await session.execute(query, params)).mappings().all()

    a_rows, b_rows, specs, sys_planets_rows, sys_gaps_rows, prov_rows = await asyncio.gather(
        fetch_all(q.PLANET_ANOMALIES, {"planet_name": planet_name}),
        fetch_all(q.PLANET_BIOSIGS, {"planet_name": planet_name}),
        fetch_all(q.SPECTRA_FOR_PLANET, {"planet_name": planet_name}),
        fetch_all(q.SYSTEM_PLANETS, {"planet_name": planet_name}),
        fetch_all(q.PLANET_GAPS, {"planet_name": planet_name, "pred_version": PRED_VERSION}),
        fetch_all(text("""
            SELECT pp.param_name, pp.uncertainty_upper, pp.uncertainty_lower, pp.is_imputed,
                   ir.source AS run_source, pa.doi, pa.title AS paper_title
            FROM planet_parameters pp
            JOIN ingestion_runs ir ON pp.run_id = ir.run_id
            LEFT JOIN papers pa ON pp.paper_id = pa.paper_id
            WHERE pp.planet_id = (SELECT planet_id FROM planets WHERE planet_name = :planet_name)
              AND pp.is_default = true AND pp.valid_to IS NULL
        """), {"planet_name": planet_name}),
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
    system_planets = [SystemPlanetItem(**dict(r)) for r in sys_planets_rows]
    orbital_gaps = [OrbitalGapItem(**dict(r)) for r in sys_gaps_rows]

    habitability = ProfileHabitability(
        composite_score=d.get("composite_score"),
        composite_score_iqr=d.get("composite_score_iqr"),
        is_imputed=d.get("is_imputed", False),
        similarity_score=d.get("similarity_score"),
        hz_score=d.get("hz_score"),
        teq_score=d.get("teq_score"),
        radius_esi_score=d.get("radius_esi_score"),
        mass_esi_score=d.get("mass_esi_score"),
        eccentricity_score=d.get("eccentricity_score"),
        age_score=d.get("age_score"),
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
        safety_score=d.get("safety_score"),
        xuv_escape_score=d.get("xuv_escape_score"),
        tidal_lock_score=d.get("tidal_lock_score")
    )

    # ── Compute Unified Discovery Score Breakdown (matching SQL) ─────────
    hab_raw = d.get("composite_score") or 0.0
    hab_component = round(hab_raw * 40, 2)

    confirmed_mols = [r for r in b_rows if (r.get("detection_sigma") or 0) >= 3.0 and (r.get("hitran_match_count") or 0) >= 3]
    n_mols = len(confirmed_mols)
    if n_mols > 0:
        avg_sigma = sum(r.get("detection_sigma", 3.0) for r in confirmed_mols) / n_mols
        avg_sigma = min(avg_sigma, 10.0)
        biosig_component = min(n_mols * 5.0 * (0.5 + 0.5 * avg_sigma / 5.0), 25.0)
    else:
        biosig_component = 0.0

    data_component = compute_data_quality_component(has_spectra, inst_best, known_params)

    n_siblings = len(sys_planets_rows)
    n_gaps = len(sys_gaps_rows)
    orbital_component = min(n_siblings * 1.5 + n_gaps * 2.0, 10.0)

    anomaly_penalty = -min(anomaly_count * 3.0, 10.0)

    discovery_score = float(d.get("discovery_score") or 0.0)

    score_breakdown = ScoreBreakdown(
        habitability=hab_component,
        biosignature=biosig_component,
        data_quality=data_component,
        orbital_context=orbital_component,
        anomaly_penalty=anomaly_penalty,
        data_confidence=round(data_completeness, 2),
    )

    # ── Provenance metadata ──────────────────────────────────────────────
    prov_map = {r["param_name"]: r for r in prov_rows}
    CORE_PARAM_NAMES = ["radius_earth", "mass_earth", "period_days",
                        "eq_temperature_k", "semi_major_axis_au", "eccentricity"]
    prov_dict = {}
    for pname in CORE_PARAM_NAMES:
        if pname in prov_map:
            pr = prov_map[pname]
            has_unc = pr.get("uncertainty_upper") is not None
            source_label = pr.get("run_source") or "unknown"
            if pr.get("doi"):
                source_label = f"{source_label} (DOI: {pr['doi']})"
            unc = None
            if has_unc:
                unc = [pr.get("uncertainty_lower") or 0, pr["uncertainty_upper"]]
            prov_dict[pname] = ParamProvenance(
                status="imputed" if pr.get("is_imputed") else "measured",
                source=source_label,
                uncertainty=unc,
            )
        elif d.get(pname) is not None and pname == "density_earth":
            prov_dict[pname] = ParamProvenance(status="derived", source="Computed from mass and radius")
    prov_dict["composite_score"] = ParamProvenance(
        status="heuristic",
        source=f"Two-track habitability model v{SCORE_VERSION}",
    )
    data_provenance = DataProvenance(**prov_dict)

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
        observability_index=d.get("observability_index"),
        physical_triage_index=d.get("physical_triage_index"),
        characterization_index=d.get("characterization_index"),
        score_breakdown=score_breakdown,
        habitability=habitability,
        biosignatures=biosignatures,
        confidence=confidence,
        anomaly_risk=anomaly_risk,
        system_planets=system_planets,
        orbital_gaps=orbital_gaps,
        data_provenance=data_provenance,
    )


# ── Spectrum ─────────────────────────────────────────────────────────────────

@app.get("/api/planets/{planet_name}/spectrum", response_model=SpectrumView)
@limiter.limit("120/minute")
async def get_spectrum(request: Request, planet_name: str, session: AsyncSession = Depends(get_db)):
    specs = (await session.execute(
        q.SPECTRA_FOR_PLANET, {"planet_name": planet_name}
    )).mappings().all()

    if not specs:
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
@limiter.limit("120/minute")
async def get_star_positions(
    request: Request,
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
        # Accurately describe as candidate molecular spectral features rather than confirmed atmospheric detections
        parts.append(f"candidate {d['molecules_detected'].upper()} spectral features (forward model benchmark)")
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
        {"score_version": SCORE_VERSION, "pred_version": PRED_VERSION, "biosig_version": BIOSIG_VERSION, "limit": limit}
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
        {"score_version": SCORE_VERSION, "pred_version": PRED_VERSION, "biosig_version": BIOSIG_VERSION, "limit": limit}
    )).mappings().all()

    return [AlertItem(**dict(r)) for r in rows]

# ── Atmospheric Retrievals ───────────────────────────────────────────────────

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


@app.post(
    "/api/planets/{planet_name}/spectra/{spec_id}/retrieve",
    response_model=AtmosphericRetrievalItem,
    status_code=202,
)
@limiter.limit("5/hour")
async def start_retrieval(
    request: Request,
    planet_name: str,
    spec_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
):
    """Queue a PLATON atmospheric retrieval for a validated planet/spectrum pair."""
    row = (await session.execute(text("""
        SELECT p.planet_id::text
        FROM planets p
        JOIN atmospheric_spectra a ON a.planet_id = p.planet_id
        WHERE p.planet_name = :pname AND a.spec_id = :sid
        LIMIT 1
    """), {"pname": planet_name, "sid": spec_id})).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Planet or spectrum not found")

    planet_id = row[0]

    running = (await session.execute(text("""
        SELECT retrieval_id::text, created_at
        FROM atmospheric_retrievals
        WHERE planet_id = :pid AND spec_id = :sid AND status = 'running'
        ORDER BY created_at DESC
        LIMIT 1
    """), {"pid": planet_id, "sid": spec_id})).mappings().one_or_none()

    if running:
        raise HTTPException(status_code=409, detail="Retrieval already in progress")

    retrieval_id = new_id()
    await session.execute(text("""
        INSERT INTO atmospheric_retrievals (
            retrieval_id, planet_id, spec_id, model_name, status
        ) VALUES (
            :rid, :pid, :sid, 'PLATON_v1', 'running'
        )
    """), {"rid": retrieval_id, "pid": planet_id, "sid": spec_id})
    await session.commit()

    def _run_retrieval():
        _enqueue_retrieval(planet_id, spec_id, retrieval_id)

    background_tasks.add_task(_run_retrieval)

    created = (await session.execute(text("""
        SELECT *
        FROM atmospheric_retrievals
        WHERE retrieval_id = :rid
    """), {"rid": retrieval_id})).mappings().one()

    item = dict(created)
    item["retrieval_id"] = str(item["retrieval_id"])
    item["spec_id"] = str(item["spec_id"])
    return AtmosphericRetrievalItem(**item)


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

    posterior_path = _safe_posterior_path(row[0])
    try:
        with open(posterior_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Posterior file is not valid JSON")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Validation Metrics ──────────────────────────────────────────────────────

@app.get("/api/validation/metrics")
async def get_validation_metrics(session: AsyncSession = Depends(get_db)):
    """Aggregate real statistics from all scientific modules for the Validation dashboard."""

    # --- Biosignature Detection ---
    mol_rows = (await session.execute(text("""
        SELECT molecule, COUNT(*)::int as total,
               ROUND(AVG(detection_sigma)::numeric, 2) as avg_sigma,
               SUM(CASE WHEN detection_tier = 'screening_candidate' THEN 1 ELSE 0 END)::int as confirmed,
               SUM(CASE WHEN detection_tier = 'marginal' THEN 1 ELSE 0 END)::int as marginal
        FROM molecule_detections
        WHERE biosig_model_version = :biosig_ver
        GROUP BY molecule ORDER BY total DESC
    """), {"biosig_ver": BIOSIG_VERSION})).fetchall()

    biosig_by_molecule = [
        {"molecule": r[0], "total": r[1], "avg_sigma": float(r[2]) if r[2] else 0,
         "screening_candidates": r[3], "confirmed": r[3], "marginal": r[4]}
        for r in mol_rows
    ]
    total_detections = sum(m["total"] for m in biosig_by_molecule)
    total_screening_candidates = sum(m["screening_candidates"] for m in biosig_by_molecule)
    total_confirmed = total_screening_candidates

    # --- Orbital Gap Predictions ---
    orb_stats = (await session.execute(text("""
        SELECT COUNT(*)::int,
               ROUND(AVG(stability_confidence)::numeric, 4),
               AVG(n_body_runs)::int,
               SUM(CASE WHEN stability_confidence >= 0.9 THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN stability_confidence >= 0.8 AND stability_confidence < 0.9 THEN 1 ELSE 0 END)::int,
               SUM(CASE WHEN stability_confidence < 0.8 THEN 1 ELSE 0 END)::int
        FROM orbital_predictions
        WHERE model_version = :pred_ver
    """), {"pred_ver": PRED_VERSION})).fetchone()

    orb_resonance = (await session.execute(text("""
        SELECT detection_method_hint, COUNT(*)::int
        FROM orbital_predictions
        WHERE model_version = :pred_ver
        GROUP BY detection_method_hint ORDER BY COUNT(*) DESC
    """), {"pred_ver": PRED_VERSION})).fetchall()

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
        WHERE model_version = :score_ver
    """), {"score_ver": SCORE_VERSION})).fetchone()

    hab_histogram = (await session.execute(text("""
        SELECT
            FLOOR(composite_score * 10)::int as bin,
            COUNT(*)::int
        FROM habitability_scores
        WHERE composite_score IS NOT NULL
          AND model_version = :score_ver
        GROUP BY bin ORDER BY bin
    """), {"score_ver": SCORE_VERSION})).fetchall()

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

    # Query live confirmed systems and latest pipeline run timestamp
    total_confirmed_planets = (await session.execute(text("SELECT COUNT(*) FROM planets WHERE status='confirmed'"))).scalar() or 0
    latest_eval_time = (await session.execute(text("SELECT MAX(finished_at) FROM ingestion_runs"))).scalar()
    if not latest_eval_time:
        latest_eval_time = (await session.execute(text("SELECT MAX(created_at) FROM habitability_scores"))).scalar()
    eval_iso_date = latest_eval_time.isoformat() if latest_eval_time else datetime.now(timezone.utc).isoformat()

    # Empirical scientific validation execution records from database
    val_run = (await session.execute(text("""
        SELECT run_id, engine_version, orbital_version, biosig_version,
               dataset_version, started_at, completed_at, total_samples, status
        FROM validation_runs
        ORDER BY completed_at DESC NULLS LAST, started_at DESC
        LIMIT 1
    """))).mappings().one_or_none()

    if val_run:
        val_results = (await session.execute(text("""
            SELECT benchmark_name, metric_name, expected_value, actual_value, tolerance, sample_count, status
            FROM validation_results
            WHERE run_id = :rid
        """), {"rid": val_run["run_id"]})).mappings().all()

        res_map = {f"{r['benchmark_name']}::{r['metric_name']}": r for r in val_results}

        # Track 1: ESI Pearson & Spearman Rank Order
        p_row = res_map.get("UPR ESI Benchmark Correlation::Pearson r")
        s_row = res_map.get("UPR ESI Benchmark Rank Order::Spearman rho")

        # Track 2: Geometric Observability Power
        obs_row = res_map.get("Geometric Observability Power::Odds Ratio")

        # Track 3: Decoupled Decision Purity
        triage_row = res_map.get("Decoupled Decision Purity::Triage Odds Ratio")

        # Track 4: Solar System Control Separation
        earth_row = res_map.get("Solar System Sanity Control::Earth Composite Score")
        mars_row = res_map.get("Solar System Sanity Control::Mars Composite Score")
        venus_row = res_map.get("Solar System Sanity Control::Venus Composite Score")
        jupiter_row = res_map.get("Solar System Sanity Control::Jupiter Composite Score")

        earth_c = earth_row["actual_value"] if earth_row and earth_row["actual_value"] is not None else None
        mars_c = mars_row["actual_value"] if mars_row and mars_row["actual_value"] is not None else None
        venus_c = venus_row["actual_value"] if venus_row and venus_row["actual_value"] is not None else None
        jupiter_c = jupiter_row["actual_value"] if jupiter_row and jupiter_row["actual_value"] is not None else None

        if all(v is not None for v in [earth_c, mars_c, venus_c, jupiter_c]):
            track4_actual = f"{earth_c:.2f} > {mars_c:.2f} > {venus_c:.2f} > {jupiter_c:.2f}"
            track4_pass = (earth_c > mars_c > venus_c > jupiter_c)
        else:
            track4_actual = None
            track4_pass = False

        eval_date = val_run["completed_at"].isoformat() if val_run.get("completed_at") else eval_iso_date
        run_status = val_run["status"]
        pipeline_status = "Online & Calibrated" if run_status == "completed" else "Failed"

        tracks = []
        if p_row and s_row:
            p_val = p_row["actual_value"]
            s_val = s_row["actual_value"]
            t1_status = "PASS" if (p_row["status"] == "PASS" and s_row["status"] == "PASS") else "FAIL"
            tracks.append({
                "track": "UPR ESI Benchmark Correlation",
                "target": "Pearson r >= 0.70 & Spearman rho >= 0.80",
                "actual": round(p_val, 3) if p_val is not None else "N/A",
                "spearman": round(s_val, 3) if s_val is not None else "N/A",
                "status": t1_status,
            })
        if obs_row:
            obs_val = obs_row["actual_value"]
            obs_p = f"{obs_row['tolerance']:.2e}" if obs_row.get('tolerance') is not None else "N/A"
            tracks.append({
                "track": "Geometric Observability Power",
                "target": "Odds Ratio >= 2.0 (p < 1e-4)",
                "actual": round(obs_val, 2) if obs_val is not None else "N/A",
                "p_value": obs_p,
                "status": obs_row["status"],
            })
        if triage_row:
            triage_val = triage_row["actual_value"]
            triage_p = f"{triage_row['tolerance']:.2e}" if triage_row.get('tolerance') is not None else "N/A"
            tracks.append({
                "track": "Decoupled Decision Purity",
                "target": "Habitability alone null (OR ~ 1.0)",
                "actual": round(triage_val, 2) if triage_val is not None else "N/A",
                "p_value": triage_p,
                "status": triage_row["status"],
            })
        if track4_actual:
            tracks.append({
                "track": "Solar System Control Separation",
                "target": "Earth > Mars > Venus > Jupiter",
                "actual": track4_actual,
                "status": "PASS" if track4_pass else "FAIL",
            })

        solar_system_controls = []
        if all(v is not None for v in [earth_c, mars_c, venus_c, jupiter_c]):
            solar_system_controls = [
                {"planet": "Earth", "sim": round(earth_row["expected_value"], 3), "safety": round(earth_row["tolerance"], 3), "composite": round(earth_c, 3), "rationale": "Primary positive control (canonical habitability reference). Maximum terrestrial similarity and balanced magnetic/thermal environment.", "status": earth_row["status"]},
                {"planet": "Mars", "sim": round(mars_row["expected_value"], 3), "safety": round(mars_row["tolerance"], 3), "composite": round(mars_c, 3), "rationale": "Sub-freezing terrestrial benchmark. High similarity index tempered by low surface pressure and atmospheric stripping.", "status": mars_row["status"]},
                {"planet": "Venus", "sim": round(venus_row["expected_value"], 3), "safety": round(venus_row["tolerance"], 3), "composite": round(venus_c, 3), "rationale": "Twin radius/mass, but extreme runaway greenhouse thermal penalty correctly demotes composite habitability.", "status": venus_row["status"]},
                {"planet": "Jupiter", "sim": round(jupiter_row["expected_value"], 3), "safety": round(jupiter_row["tolerance"], 3), "composite": round(jupiter_c, 3), "rationale": "Primary negative control. Giant gas envelope and extreme radiation belt trigger severe Fulton and non-terrestrial penalties.", "status": jupiter_row["status"]},
            ]

        evaluation_run = {
            "run_id": str(val_run["run_id"]),
            "engine_version": val_run["engine_version"],
            "orbital_version": val_run["orbital_version"],
            "biosig_version": val_run["biosig_version"],
            "evaluation_date": eval_date,
            "test_cases_evaluated": val_run["total_samples"],
            "total_confirmed_planets": total_confirmed_planets,
            "benchmark_dataset": val_run["dataset_version"],
            "pipeline_status": pipeline_status,
            "tracks": tracks,
            "solar_system_controls": solar_system_controls,
        }
    else:
        evaluation_run = {
            "engine_version": SCORE_VERSION,
            "orbital_version": PRED_VERSION,
            "biosig_version": BIOSIG_VERSION,
            "evaluation_date": eval_iso_date,
            "test_cases_evaluated": 0,
            "total_confirmed_planets": total_confirmed_planets,
            "benchmark_dataset": "UPR Published Catalog + NASA Exoplanet Archive + Gaia DR3",
            "pipeline_status": "Not evaluated",
            "tracks": [],
            "solar_system_controls": [],
        }

    return {
        "biosignatures": {
            "total_detections": total_detections,
            "total_screening_candidates": total_screening_candidates,
            "total_confirmed": total_confirmed,
            "by_molecule": biosig_by_molecule,
        },
        "orbital": orbital,
        "habitability": habitability,
        "anomalies": anomalies,
        "retrievals": retrievals,
        "evaluation_run": evaluation_run,
    }
