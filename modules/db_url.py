"""Database URL normalization for sync vs async SQLAlchemy engines."""
from __future__ import annotations

import os


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def normalize_sync_database_url(url: str | None = None) -> str:
    """Return a psycopg2-compatible URL for sync SQLAlchemy engines."""
    raw = url or get_database_url()
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw


def normalize_async_database_url(url: str | None = None) -> str:
    """Return an asyncpg-compatible URL for FastAPI / async SQLAlchemy."""
    raw = url or get_database_url()
    if raw.startswith("postgresql+psycopg2://"):
        return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw
