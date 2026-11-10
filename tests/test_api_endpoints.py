"""
Tests for API endpoints using FastAPI's TestClient.

Mocks the database session so tests run without a live PostgreSQL instance.
Tests verify HTTP status codes, response shapes, query parameters, and error handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ── Build a mock session that returns realistic data ─────────────────────────

def _make_mock_session():
    """Create an AsyncMock session that behaves like SQLAlchemy AsyncSession."""
    session = AsyncMock()

    # Default: return empty results for any query
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    result.mappings.return_value.one_or_none.return_value = None
    result.mappings.return_value.one.return_value = {
        "total_planets": 5000, "total_stars": 4000,
        "total_spectra": 200, "scored_planets": 3000,
        "predicted_systems": 500, "biosig_detections": 50,
        "anomaly_flags": 300, "avg_hab_score": 0.42,
    }
    result.scalar.return_value = 0
    session.execute.return_value = result
    session.close = AsyncMock()
    return session


def _get_test_client():
    """Build a TestClient with the DB dependency overridden."""
    # We need to import app AFTER conftest has patched sqlalchemy
    from api.main import app
    from api.db import get_db

    mock_session = _make_mock_session()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, mock_session, app


# ── Health Endpoint ──────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_ok(self):
        client, _, app = _get_test_client()
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        app.dependency_overrides.clear()


# ── Stats Endpoint ───────────────────────────────────────────────────────────

class TestStatsEndpoint:
    def test_stats_returns_200(self):
        from api.main import app
        from api.db import get_db

        # Build a mock session with the stats result pre-configured
        session = AsyncMock()
        stats_result = MagicMock()
        stats_result.mappings.return_value.one.return_value = {
            "stars": 4521,
            "planets": 5832,
            "habitability_scores": 3210,
            "orbital_predictions": 512,
            "molecule_detections": 67,
            "atmospheric_spectra": 247,
            "anomaly_flags": 318,
            "taxonomy_clusters": 42,
        }
        session.execute.return_value = stats_result
        session.close = AsyncMock()

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "stars" in data
        assert "planets" in data
        assert data["planets"] == 5832
        assert data["taxonomy_clusters"] == 42
        app.dependency_overrides.clear()


# ── Planets List Endpoint ────────────────────────────────────────────────────

class TestPlanetsListEndpoint:
    def test_planets_list_returns_200(self):
        client, session, app = _get_test_client()

        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        # Mock list query
        list_result = MagicMock()
        list_result.mappings.return_value.all.return_value = [
            {
                "planet_name": "TRAPPIST-1 e",
                "hostname": "TRAPPIST-1",
                "discovery_method": "Transit",
                "discovery_year": 2017,
                "radius_earth": 0.92,
                "mass_earth": 0.69,
                "period_days": 6.10,
                "eq_temperature_k": 251.0,
                "semi_major_axis_au": 0.029,
                "composite_score": 0.85,
                "discovery_score": 72.5,
                "hz_score": 0.91,
                "cluster_name": "Temperate Rocky",
            },
            {
                "planet_name": "Kepler-442 b",
                "hostname": "Kepler-442",
                "discovery_method": "Transit",
                "discovery_year": 2015,
                "radius_earth": 1.34,
                "mass_earth": None,
                "period_days": 112.3,
                "eq_temperature_k": 233.0,
                "semi_major_axis_au": 0.409,
                "composite_score": 0.72,
                "discovery_score": 55.1,
                "hz_score": 0.88,
                "cluster_name": "Cold Rocky",
            },
        ]

        # Return count first, then list
        session.execute.side_effect = [count_result, list_result]

        response = client.get("/api/planets?page=1&page_size=50")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["planet_name"] == "TRAPPIST-1 e"
        app.dependency_overrides.clear()

    def test_planets_list_pagination_params(self):
        client, session, app = _get_test_client()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        list_result = MagicMock()
        list_result.mappings.return_value.all.return_value = []
        session.execute.side_effect = [count_result, list_result]

        response = client.get("/api/planets?page=2&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10
        app.dependency_overrides.clear()

    def test_planets_list_invalid_page(self):
        client, _, app = _get_test_client()
        response = client.get("/api/planets?page=0")
        assert response.status_code == 422  # Validation error (ge=1)
        app.dependency_overrides.clear()

    def test_planets_list_oversized_page(self):
        client, _, app = _get_test_client()
        response = client.get("/api/planets?page_size=9999")
        assert response.status_code == 422  # Validation error (le=500)
        app.dependency_overrides.clear()


# ── Planet Detail Endpoint ───────────────────────────────────────────────────

class TestPlanetDetailEndpoint:
    def test_planet_not_found_returns_404(self):
        client, session, app = _get_test_client()

        # Mock: planet query returns None
        detail_result = MagicMock()
        detail_result.mappings.return_value.one_or_none.return_value = None
        session.execute.return_value = detail_result

        response = client.get("/api/planets/NonExistentPlanet-999z")
        assert response.status_code == 404
        app.dependency_overrides.clear()


# ── CORS Headers ─────────────────────────────────────────────────────────────

class TestCorsHeaders:
    def test_cors_allows_localhost(self):
        client, _, app = _get_test_client()
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            }
        )
        # CORS preflight should succeed
        assert response.status_code in (200, 204)
        app.dependency_overrides.clear()


# ── API Structure ────────────────────────────────────────────────────────────

class TestApiStructure:
    def test_docs_endpoint_exists(self):
        client, _, app = _get_test_client()
        response = client.get("/docs")
        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_redoc_endpoint_exists(self):
        client, _, app = _get_test_client()
        response = client.get("/redoc")
        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_openapi_json_exists(self):
        client, _, app = _get_test_client()
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "paths" in schema
        assert "/health" in schema["paths"]
        assert "/api/planets" in schema["paths"]
        assert "/api/stats" in schema["paths"]
        app.dependency_overrides.clear()

    def test_post_retrieval_endpoint_exists(self):
        """POST retrieval is available for validated planet/spectrum pairs."""
        client, session, app = _get_test_client()

        schema = client.get("/openapi.json").json()
        post_path = "/api/planets/{planet_name}/spectra/{spec_id}/retrieve"
        assert post_path in schema["paths"]
        assert "post" in schema["paths"][post_path]

        # Missing planet/spectrum should 404
        not_found = MagicMock()
        not_found.fetchone.return_value = None
        session.execute.return_value = not_found

        response = client.post("/api/planets/TRAPPIST-1%20e/spectra/spec-1/retrieve")
        assert response.status_code == 404
        app.dependency_overrides.clear()

    def test_start_retrieval_returns_202(self):
        from api.main import app
        from api.db import get_db

        session = AsyncMock()
        lookup = MagicMock()
        lookup.fetchone.return_value = ("planet-uuid",)

        running = MagicMock()
        running.mappings.return_value.one_or_none.return_value = None

        created = MagicMock()
        created.mappings.return_value.one.return_value = {
            "retrieval_id": "ret-1",
            "spec_id": "spec-1",
            "model_name": "PLATON_v1",
            "status": "running",
            "run_time_seconds": None,
            "best_fit_params": None,
            "evidence_ln_z": None,
            "error_message": None,
            "created_at": None,
        }

        session.execute.side_effect = [lookup, running, MagicMock(), created]
        session.commit = AsyncMock()
        session.close = AsyncMock()

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.post("/api/planets/TRAPPIST-1%20e/spectra/spec-1/retrieve")
        assert response.status_code == 202
        assert response.json()["status"] == "running"
        app.dependency_overrides.clear()


# ── Spectrum & Validation Integrity Integration Tests ───────────────────────

class TestSpectrumEndpointBinding:
    def test_get_spectrum_binds_spec_id_and_returns_view(self):
        """Verify that GET /api/planets/{planet_name}/spectrum binds spec_id and does not raise 500."""
        from api.main import app
        from api.db import get_db

        session = AsyncMock()

        # Mock spectra list with multiple observations
        mock_specs = MagicMock()
        mock_specs.mappings.return_value.all.return_value = [
            {"spec_id": "spec-obs-1", "instrument": "NIRSpec", "facility": "JWST", "obs_type": "transmission"},
            {"spec_id": "spec-obs-2", "instrument": "WFC3", "facility": "HST", "obs_type": "transmission"},
        ]

        mock_points = MagicMock()
        mock_points.mappings.return_value.all.return_value = [
            {"point_id": 1, "wavelength_um": 1.4, "depth_ppm": 1200.0, "depth_err_upper": 20.0, "depth_err_lower": 20.0}
        ]

        mock_detections = MagicMock()
        mock_detections.mappings.return_value.all.return_value = [
            {
                "molecule": "H2O", "detection_sigma": 4.2, "confidence": 0.95,
                "detection_tier": "screening_candidate", "hitran_match_count": 5,
                "features_analyzed": 6, "snr": 8.5, "model_version": "3.0.0",
                "abiotic_ruled_out": False
            }
        ]

        mock_hitran = MagicMock()
        mock_hitran.mappings.return_value.all.return_value = [
            {"molecule": "H2O", "wavelength_um": 1.4, "intensity": 0.8}
        ]

        session.execute.side_effect = [mock_specs, mock_points, mock_detections, mock_hitran]
        session.close = AsyncMock()

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/api/planets/K2-18%20b/spectrum")
        assert response.status_code == 200
        data = response.json()
        assert data["spec_id"] == "spec-obs-1"
        assert len(data["points"]) == 1
        assert len(data["detections"]) == 1
        assert data["detections"][0]["molecule"] == "H2O"

        # Verify that calls 3 and 4 received spec_id="spec-obs-1"
        call_args_list = session.execute.call_args_list
        assert len(call_args_list) == 4
        # call 2 is SPECTRUM_POINTS
        assert call_args_list[1][0][1] == {"spec_id": "spec-obs-1"}
        # call 3 is SPECTRUM_DETECTIONS -> must receive planet_name AND spec_id
        assert call_args_list[2][0][1] == {"planet_name": "K2-18 b", "spec_id": "spec-obs-1"}
        # call 4 is HITRAN_LINES_FOR_PLANET -> must receive planet_name AND spec_id
        assert call_args_list[3][0][1] == {"planet_name": "K2-18 b", "spec_id": "spec-obs-1"}

        app.dependency_overrides.clear()


class TestValidationIntegrityEndpoints:
    def test_solar_system_control_failure_cannot_display_as_pass(self):
        """Verify that if a Solar System control fails, the API does not mask it as PASS."""
        from api.main import app
        from api.db import get_db

        session = AsyncMock()

        # Mock validation_runs
        val_run_mock = MagicMock()
        val_run_mock.mappings.return_value.one_or_none.return_value = {
            "run_id": "mock-run-uuid",
            "engine_version": "5.0.0",
            "orbital_version": "3.1.0",
            "biosig_version": "3.0.0",
            "dataset_version": "UPR + NASA",
            "started_at": None,
            "completed_at": None,
            "total_samples": 4611,
            "status": "failed",
        }

        # Mock validation_results with a failed Earth control
        val_res_mock = MagicMock()
        val_res_mock.mappings.return_value.all.return_value = [
            {
                "benchmark_name": "Solar System Sanity Control",
                "metric_name": "Earth Composite Score",
                "expected_value": 1.0,
                "actual_value": 0.40,  # Below threshold
                "tolerance": 0.50,
                "sample_count": 1,
                "status": "FAIL",      # Explicitly failed
            },
            {
                "benchmark_name": "Solar System Sanity Control",
                "metric_name": "Mars Composite Score",
                "expected_value": 0.72,
                "actual_value": 0.74,
                "tolerance": 0.20,
                "sample_count": 1,
                "status": "PASS",
            },
            {
                "benchmark_name": "Solar System Sanity Control",
                "metric_name": "Venus Composite Score",
                "expected_value": 0.39,
                "actual_value": 0.41,
                "tolerance": 0.10,
                "sample_count": 1,
                "status": "PASS",
            },
            {
                "benchmark_name": "Solar System Sanity Control",
                "metric_name": "Jupiter Composite Score",
                "expected_value": 0.24,
                "actual_value": 0.0,
                "tolerance": 0.0,
                "sample_count": 1,
                "status": "PASS",
            },
        ]

        from datetime import datetime, timezone
        generic_scalar = MagicMock()
        generic_scalar.scalar.return_value = 100
        dt_scalar = MagicMock()
        dt_scalar.scalar.return_value = datetime.now(timezone.utc)
        generic_fetchall = MagicMock()
        generic_fetchall.fetchall.return_value = []
        generic_fetchone = MagicMock()
        generic_fetchone.fetchone.return_value = None

        def side_effect_fn(*args, **kwargs):
            query_str = str(args[0]) if args else ""
            if "FROM validation_runs" in query_str:
                return val_run_mock
            elif "FROM validation_results" in query_str:
                return val_res_mock
            elif "SELECT MAX(" in query_str:
                return dt_scalar
            elif "SELECT COUNT(*)" in query_str:
                return generic_scalar
            elif "GROUP BY" in query_str:
                return generic_fetchall
            else:
                return generic_fetchone

        session.execute.side_effect = side_effect_fn
        session.close = AsyncMock()

        async def override_get_db():
            yield session

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)

        response = client.get("/api/validation/metrics")
        assert response.status_code == 200
        data = response.json()
        eval_run = data["evaluation_run"]
        assert eval_run["pipeline_status"] == "Failed"

        controls = {c["planet"]: c for c in eval_run["solar_system_controls"]}
        assert controls["Earth"]["status"] == "FAIL"
        assert controls["Earth"]["status"] != "PASS"

        app.dependency_overrides.clear()
