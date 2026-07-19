"""Same rationale as apps/api/tests/integration/conftest.py: real Postgres,
not sqlite, because the schema uses citext/pg_trgm/PostGIS/pgvector. Migrations
are owned by apps/api's Alembic config; this just points the CLI at it and
runs it out-of-process (again, so it doesn't fight pytest-asyncio's loop)."""

import os
import subprocess
import sys
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://punerecpip:punerecpip_dev@localhost:5432/punerecpip_test",
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
API_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", "api"))


def _run_alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_schema() -> None:
    _run_alembic("upgrade", "head")
    yield
    _run_alembic("downgrade", "base")


@pytest_asyncio.fixture
async def engine(migrated_schema: None) -> AsyncGenerator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """DiscoveryService calls `session.commit()` mid-run by design (checkpoints
    must survive a crash), so a plain rollback-after-test wouldn't clean up.
    Binding to an outer connection-level transaction with
    join_transaction_mode="create_savepoint" makes every inner `commit()`
    release a SAVEPOINT instead of the real transaction; the final
    `connection.rollback()` then discards all of it regardless of how many
    times the code under test called commit()."""
    async with engine.connect() as connection:
        await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as s:
            yield s
        await connection.rollback()
