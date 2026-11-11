"""Pytest fixtures for HireOS backend tests."""

from __future__ import annotations

# Test configuration and private storage must precede application imports.
# ruff: noqa: E402
import os
import tempfile
import uuid

# Set test environment BEFORE any app imports
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://hireos:hireos_secret@localhost:5432/hireos_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "test")
# Upload tests must never write to application data or the read-only source mount.
TEST_UPLOADS = tempfile.TemporaryDirectory(prefix="flintplate-test-uploads-")
os.environ["UPLOAD_DIR"] = TEST_UPLOADS.name

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base, get_db
from app.main import app

# ── Test DB Engine ────────────────────────────────────────────────────────────
TEST_DB_URL = os.environ["DATABASE_URL"]
if not (make_url(TEST_DB_URL).database or "").endswith("_test"):
    raise RuntimeError("Tests require a dedicated database whose name ends with _test")
TEST_SCHEMA = f"test_{uuid.uuid4().hex}"

# asyncpg connections are bound to the event loop that created them.  Pytest
# may use a different loop for each async test, so a pooled engine can hand a
# connection from one loop to another and fail with "another operation is in
# progress".  NullPool keeps every connection local to its use and makes the
# fixture safe across pytest-asyncio loops.
test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    poolclass=NullPool,
    connect_args={"server_settings": {"search_path": f"{TEST_SCHEMA},public"}},
    execution_options={"schema_translate_map": {None: TEST_SCHEMA}},
)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── Session-scoped DB setup / teardown ───────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
async def create_tables() -> None:  # type: ignore[misc]
    async with test_engine.begin() as conn:
        # Extensions are database-wide dependencies. Keep them outside the
        # disposable schemas used by concurrent browser and migration checks.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public"))
        await conn.execute(text(f'CREATE SCHEMA "{TEST_SCHEMA}"'))
        await conn.run_sync(Base.metadata.create_all)
    yield  # type: ignore[misc]
    async with test_engine.begin() as conn:
        # The schema is unique to this run. CASCADE also handles the circular
        # users/company foreign keys without touching other test runs or data.
        await conn.execute(text(f'DROP SCHEMA "{TEST_SCHEMA}" CASCADE'))
    await test_engine.dispose()
    TEST_UPLOADS.cleanup()


# ── Per-test DB session with rollback isolation ───────────────────────────────
@pytest.fixture
async def db_session() -> AsyncSession:  # type: ignore[misc]
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session  # type: ignore[misc]
        await transaction.rollback()


# ── Override FastAPI get_db with test session ─────────────────────────────────
@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncClient:  # type: ignore[misc]
    async def override_get_db() -> AsyncSession:  # type: ignore[misc]
        yield db_session  # type: ignore[misc]

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac  # type: ignore[misc]
    app.dependency_overrides.clear()


# ── Shared test data ──────────────────────────────────────────────────────────
@pytest.fixture
def test_user_data() -> dict[str, str]:
    return {
        "email": "test@hireos.dev",
        "password": "SecurePass123!",
        "full_name": "Test User",
    }


from tests.hr_support import hr_workspace  # noqa: E402, F401
