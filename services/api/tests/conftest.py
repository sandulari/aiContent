"""Shared pytest fixtures for the FastAPI service.

DB-backed fixtures (`db_session`, `client`, `authed_client`, `other_authed_client`)
require a Postgres instance reachable at ``TEST_DATABASE_URL`` (default
``postgresql+asyncpg://vre_user:vre_pass@localhost:5432/vre_test``). Tests that
don't need the database — e.g. pure auth-helper unit tests — should not request
those fixtures and will run regardless.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

# Make ``services/api`` importable (`from main import app`, `from models...` …).
_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

# Force a known JWT secret so token sign/verify is deterministic in tests.
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-outside-tests")
os.environ.setdefault("COOKIE_SECURE", "false")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vre_user:vre_pass@localhost:5433/vre_test",
)
# Point the production engine (db.session) at the same test DB so FastAPI's
# lifespan can run migrations + seed master templates without hitting the
# real database. The override on `get_db` keeps actual test transactions on
# the conftest-managed engine instead.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest_asyncio.fixture(scope="session")
async def _engine():
    """Session-scoped async engine for the test DB.

    Creates the full schema on first use and drops everything at session end.
    Each test gets its own transaction-scoped session via ``db_session``.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    import models  # noqa: F401 — triggers SQLAlchemy registration
    from models.base import Base

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Apply incremental migrations so the schema matches production.
    from db.migrations import run_migrations
    await run_migrations(engine)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_engine):
    """A clean transactional session per test.

    Everything written rolls back at teardown so tests stay isolated without
    paying for a schema rebuild between cases.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with _engine.connect() as conn:
        trans = await conn.begin()
        # `join_transaction_mode="create_savepoint"` lets router code that
        # calls `db.rollback()` (e.g. IntegrityError handlers) only undo a
        # SAVEPOINT instead of nuking the test's outer transaction.
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI test client with ``get_db`` overridden to the transactional session."""
    from httpx import ASGITransport, AsyncClient

    from db.session import get_db
    from main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authed_user(db_session):
    """A persisted ``User`` row for tests that need an authenticated principal."""
    from middleware.auth import hash_password
    from models.user import User

    user = User(
        email=f"test-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("testpass123"),
        display_name="Test User",
        role="user",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def authed_client(client, authed_user):
    """Test client carrying a valid access-token cookie for ``authed_user``.

    Also pre-seeds a known ``csrf_token`` cookie and sends the matching
    ``X-CSRF-Token`` header on every request, so the CSRF middleware (Task
    2.1) doesn't 403 the existing mutating tests. Tests that want to
    exercise the CSRF rejection path should clear/override these directly.
    """
    from middleware.auth import create_access_token
    from middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME

    token = create_access_token(authed_user.id, role=authed_user.role)
    client.cookies.set("access_token", token)
    csrf = "test-csrf-token"
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    client.headers.update({CSRF_HEADER_NAME: csrf})
    return client


@pytest_asyncio.fixture
async def other_authed_user(db_session):
    """A second persisted user for cross-tenant ownership tests."""
    from middleware.auth import hash_password
    from models.user import User

    user = User(
        email=f"other-{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("testpass123"),
        display_name="Other User",
        role="user",
    )
    db_session.add(user)
    await db_session.flush()
    return user
