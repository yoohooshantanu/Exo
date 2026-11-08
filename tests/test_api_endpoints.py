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
