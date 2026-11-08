"""Tests for modules/db_url.py URL normalization."""
import pytest

from modules.db_url import (
    normalize_async_database_url,
    normalize_sync_database_url,
)


class TestDatabaseUrlNormalization:
    def test_sync_from_asyncpg(self):
        url = "postgresql+asyncpg://user:pass@localhost:5432/exo"
        assert normalize_sync_database_url(url) == "postgresql+psycopg2://user:pass@localhost:5432/exo"

    def test_sync_from_plain_postgres(self):
        url = "postgresql://user:pass@localhost:5432/exo"
        assert normalize_sync_database_url(url) == "postgresql+psycopg2://user:pass@localhost:5432/exo"

    def test_async_from_psycopg2(self):
        url = "postgresql+psycopg2://user:pass@localhost:5432/exo"
        assert normalize_async_database_url(url) == "postgresql+asyncpg://user:pass@localhost:5432/exo"

    def test_async_from_plain_postgres(self):
        url = "postgresql://user:pass@localhost:5432/exo"
        assert normalize_async_database_url(url) == "postgresql+asyncpg://user:pass@localhost:5432/exo"

    def test_missing_database_url_raises(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            normalize_sync_database_url()

    def test_reads_from_environment(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://exo:secret@db:5432/exoplanets")
        assert normalize_sync_database_url() == "postgresql+psycopg2://exo:secret@db:5432/exoplanets"
