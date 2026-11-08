"""
Pytest configuration — patches database connectivity and heavy dependencies
before any test module import.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# ── 1. Ensure project paths ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "modules")]:
    if p not in sys.path:
        sys.path.insert(0, p)


def pytest_configure(config):
    """Called before collection. Patch everything here."""
    # Set dummy DB URL
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/testdb"

    # Mock heavy native dependencies that may not be installed in test env
    if "rebound" not in sys.modules:
        sys.modules["rebound"] = MagicMock()

    # Monkey-patch sqlalchemy before any module can call create_engine()
    import sqlalchemy
    import sqlalchemy.orm
    sqlalchemy.create_engine = lambda *a, **kw: MagicMock()
    sqlalchemy.orm.sessionmaker = lambda *a, **kw: MagicMock()

    # Patch the async engine used by api/db.py
    try:
        import sqlalchemy.ext.asyncio
        mock_async_engine = MagicMock()
        sqlalchemy.ext.asyncio.create_async_engine = lambda *a, **kw: mock_async_engine

        # Also patch async_sessionmaker
        _orig_async_session = getattr(sqlalchemy.ext.asyncio, 'async_sessionmaker', None)
        if _orig_async_session:
            sqlalchemy.ext.asyncio.async_sessionmaker = lambda *a, **kw: MagicMock()
    except ImportError:
        pass

    # Ensure slowapi doesn't block tests — mock the limiter to be a no-op
    try:
        import slowapi
    except ImportError:
        # slowapi not installed — create a stub so api/main.py can import it
        mock_slowapi = MagicMock()
        # Make Limiter return a mock that has a .limit() decorator that passes through
        mock_limiter = MagicMock()
        mock_limiter.limit = lambda *a, **kw: (lambda fn: fn)  # no-op decorator
        mock_slowapi.Limiter = lambda *a, **kw: mock_limiter
        mock_slowapi._rate_limit_exceeded_handler = MagicMock()
        mock_slowapi.util = MagicMock()
        mock_slowapi.util.get_remote_address = MagicMock()
        mock_slowapi.errors = MagicMock()
        mock_slowapi.errors.RateLimitExceeded = Exception
        sys.modules["slowapi"] = mock_slowapi
        sys.modules["slowapi.util"] = mock_slowapi.util
        sys.modules["slowapi.errors"] = mock_slowapi.errors
