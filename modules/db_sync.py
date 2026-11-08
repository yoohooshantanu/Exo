"""Shared sync SQLAlchemy engine factory for pipeline modules."""
from __future__ import annotations

from modules.db_url import normalize_sync_database_url
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


def create_sync_engine(**kwargs) -> Engine:
    defaults = {"pool_pre_ping": True}
    defaults.update(kwargs)
    return create_engine(normalize_sync_database_url(), **defaults)


def get_sync_session_factory(**engine_kwargs):
    return sessionmaker(bind=create_sync_engine(**engine_kwargs))
