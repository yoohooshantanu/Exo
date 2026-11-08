"""Tests for posterior file path security in the API."""
import json
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from modules.config import RETRIEVAL_OUTPUT_DIR


def _get_test_client():
    from api.db import get_db
    from api.main import app

    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    result.mappings.return_value.one_or_none.return_value = None
    result.scalar.return_value = 0
    session.execute.return_value = result
    session.close = AsyncMock()

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session, app


class TestPosteriorPathSecurity:
    def test_rejects_path_outside_output_dir(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"ok": True}), encoding="utf-8")

        client, session, app = _get_test_client()
        row = MagicMock()
        row.__getitem__ = lambda self, idx: str(outside) if idx == 0 else None
        session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/retrievals/00000000-0000-0000-0000-000000000001/posterior")
        assert response.status_code == 403
        app.dependency_overrides.clear()

    def test_allows_file_inside_retrieval_output_dir(self):
        from modules.config import PROJECT_ROOT

        RETRIEVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        safe_file = RETRIEVAL_OUTPUT_DIR / "posterior_test.json"
        safe_file.write_text(json.dumps({"params": ["Rp"], "samples": []}), encoding="utf-8")
        rel = safe_file.relative_to(PROJECT_ROOT).as_posix()

        client, session, app = _get_test_client()
        session.execute.return_value.fetchone.return_value = (rel,)

        response = client.get("/api/retrievals/00000000-0000-0000-0000-000000000002/posterior")
        assert response.status_code == 200
        assert response.json()["params"] == ["Rp"]
        app.dependency_overrides.clear()

        if safe_file.exists():
            safe_file.unlink()
